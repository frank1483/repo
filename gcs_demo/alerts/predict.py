"""預測型智慧告警引擎（演算法層）。

原則：數字全部由演算法算；LLM（explain.py）只把算好的事實說成白話，並從演算法
給的「可行建議」裡挑一個。每個告警都附 evidence（E*）與 candidates（C*），
告警升降級用遲滯，避免一閃一閃。

預測器：
  P1 航線電量：飛完剩餘航線＋返航後的落地電量，低於保留值就提前告警。
  P2 最晚返航點：沿剩餘航線找「過了就無法帶保留電量回家」的航點與到達時間。
  P3 電池實際容量：用電壓下降趨勢反推實際可用能量，和飛控電量% 不一致就告警。
  P4 鏈路沿航線預測：學「鏈路品質 vs 離家距離」，推估航線最遠段會不會斷線。
  P5 風速趨勢：線性外推，預估多久後超過機體抗風上限。
"""
from __future__ import annotations

import math
import json
from collections import deque
from dataclasses import dataclass, field, replace
from copy import deepcopy

from .display import landing_pct_text
from .core.state_machine import AlertEngine
from .core.freshness import TRUE, FALSE, UNKNOWN

from .energy_api import (Vehicle, Wind, air_power_w, leg_energy, rtl_energy,
                         with_calib, profile_limits)

# GcpAlertManager 用的 MAV_SEVERITY
SEV_CRITICAL, SEV_WARNING, SEV_NOTICE = 2, 4, 5


@dataclass
class Telemetry:
    t: float
    pos: tuple                # (x, y, alt) 本地公尺
    vel: tuple                # (vx, vy, vz) 地速 m/s
    soc_pct: float            # 飛控回報電量%
    voltage: float            # 電池總電壓
    current_a: float
    used_wh: float            # 飛控累計已用能量
    cell_count: int
    next_wp: int              # 目前要飛往的航點索引（route 內）
    link_pct: float           # 鏈路品質 0–100
    wind: Wind                # 飛控風速估測


@dataclass
class Config:
    """raise_ticks/clear_ticks are compatibility fields; v5 uses seconds."""
    reserve_pct: float = 20.0
    wind_limit_mps: float = 12.0
    link_min_pct: float = 35.0
    # 第一階段假設門檻，待回放敏感度驗證。
    link_warn_enter_s: float = 120.0
    link_warn_exit_s: float = 150.0
    cell_r_ohm: float = 0.004         # 單芯內阻（電壓補償用）
    cell_empty_v: float = 3.55        # 補償後單芯電壓到這裡視為 0%
    raise_ticks: int = 3              # 連續成立幾次才發
    clear_ticks: int = 10             # 連續不成立幾次才解除
    horizon_s: float = 300.0          # 趨勢預測看多遠
    emergency_rtl_min_pct: float = 10.0  # HOLD 中顯示返航備選的門檻，不是飛行批准


def linfit(xs, ys):
    """最小平方直線；回傳 (slope, intercept, r2)。"""
    n = len(xs)
    if n < 3:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return 0.0, my, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    sst = sum((y - my) ** 2 for y in ys)
    sse = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    return b, a, (1 - sse / sst) if sst > 1e-12 else 0.0


@dataclass
class Finding:
    """單一預測器這一刻的判斷。"""
    key: str
    active: bool
    severity: int = SEV_NOTICE
    title: str = ""
    value: str = ""
    evidence: list = field(default_factory=list)     # [{"id","text","value"}]
    candidates: list = field(default_factory=list)   # [{"id","action","label","end_pct","completion_pct","feasible"}]
    rule_choice: str | None = None
    lead_s: float | None = None                       # 距離問題發生還有多久
    prediction_expired: bool = False


class PredictiveAlertEngine:
    def __init__(self, route, home, vehicle: Vehicle, config: Config | None = None, priorities=None):
        """priorities：每個航點的優先級（1 必要、2 選配），None 表示全部一樣重要。"""
        # Tuple routes do not encode modes, FW turns or a landing approach.
        # Do not issue MC-only landing/slowdown advice for other airframes.
        if vehicle.type != "multirotor":
            raise NotImplementedError(
                f"{vehicle.type}: typed alert routes/candidates are not supported yet")
        self.route = [tuple(p) for p in route]
        self.route_idx = list(range(len(self.route)))   # 目前航線每點對應原航線的索引
        self.total_wps = len(self.route)       # 完成度一律對原始航線算
        self._reached: set[int] = set()        # 已到過的原航點，換航線仍保留
        self.prio = list(priorities) if priorities else None
        self.home = tuple(home)
        self.v = vehicle
        self.cfg = replace(config or Config(), **profile_limits(vehicle))
        self.calib = vehicle.calib
        self._cell_hist = deque()             # (t, used_wh, 補償後單芯電壓)，僅留 600 秒
        self._link_hist = deque(maxlen=900)    # (離家距離, 品質)
        self._wind_hist = deque(maxlen=180)    # (t, 風速)
        self._route_revision = 0
        self._option_energy_ok: dict[str, bool] = {}  # option identity, independent of alerts
        self._states = AlertEngine()
        self._last_tm_t = None
        self._streak: dict[str, int] = {}  # compatibility only; never used for timing
        self._active: dict[str, Finding] = {}
        self._announced: dict[str, tuple] = {}   # key -> (severity, choice) 最後一次說明時
        self._pending_choice: dict[str, tuple] = {}
        self._wind_trend = (0.0, 0.0)            # (每秒變化, R²)
        self.last_state: dict = {}

    def set_route(self, route, indices=None):
        """操作員改了航線。indices＝新航線每點在原航線的索引（省略則視為原航線前段）。
        之後 Telemetry.next_wp 指的是新航線的位置。"""
        new_route = [tuple(p) for p in route]
        new_idx = list(indices) if indices is not None else list(range(len(new_route)))
        if (len(new_route) != len(new_idx)
                or any(not isinstance(k, int) or isinstance(k, bool)
                       or not 0 <= k < self.total_wps for k in new_idx)
                or any(len(p) != 3 or not all(self._finite(x) for x in p) for p in new_route)):
            raise ValueError("航線須為有限三維座標，並逐點對應有效的原航點索引")
        if new_route != self.route or new_idx != self.route_idx:
            self._route_revision += 1
            self._option_energy_ok.clear()
        self.route, self.route_idx = new_route, new_idx

    def _orig(self, pos_in_route: int) -> int:
        """目前航線第 pos 點 → 原航線索引（給畫面顯示 WP 編號）。"""
        if not 0 <= pos_in_route < len(self.route_idx):
            raise IndexError("航點位置不在目前航線內")
        return self.route_idx[pos_in_route]

    def _required_left(self, from_pos: int) -> int:
        """目前航線從 from_pos 起還沒飛的必要目標數。"""
        if not self.prio:
            return 0
        return sum(1 for k in set(self.route_idx[from_pos:]) - self._reached if self.prio[k] == 1)

    def _completion(self, planned=()):
        """已到達 ∪ 計畫會到達的原索引；不把被刪除的航點當成已完成。"""
        return len(self._reached | set(planned)) / self.total_wps * 100.0 if self.total_wps else 0.0

    def _option_identity(self, ident, action, param=None, scope="battery"):
        # Numeric predictions change each sample; only execution parameters and
        # route revision distinguish options. Do not round parameters together.
        if scope == "battery" and param is None and self._route_revision == 0:
            return ident
        return json.dumps([scope, self._route_revision, ident, action, param],
                          ensure_ascii=True, separators=(",", ":"), allow_nan=False)

    @staticmethod
    def _recommendation_key(candidate):
        return candidate.get("option_identity", candidate["id"])

    def _is_feasible(self, end_pct_raw, option_id="C1"):
        """Energy qualification, contract 5.2; this is not joint feasibility.

        First qualification and retention use reserve (normally 20%). Once an
        option loses qualification it needs reserve + 2 (normally 22%) to regain
        it. Alert state and rounding never affect this per-option memory.
        Invalid/missing estimates reject this assessment without rewriting memory.
        Advisory IDs are namespaced because their C1/C2 are different options.
        """
        if not isinstance(option_id, str) or not option_id:
            raise ValueError("nonempty option identity required")
        if not self._finite(end_pct_raw):
            return False
        previous = self._option_energy_ok.get(option_id)
        threshold = self.cfg.reserve_pct + (2.0 if previous is False else 0.0)
        qualified = end_pct_raw >= threshold
        self._option_energy_ok[option_id] = qualified
        return qualified

    @staticmethod
    def _finite(value):
        try:
            return not isinstance(value, bool) and math.isfinite(value)
        except (TypeError, ValueError, OverflowError):
            return False

    def _input_error(self, tm):
        """先檢核完整快照；壞資料不寫入歷史、不宣告恢復正常。"""
        try:
            if not isinstance(tm, Telemetry):
                return "遙測須為 Telemetry 快照"
            if len(tm.pos) != 3 or len(tm.vel) != 3:
                return "位置／速度須為三維"
            values = [tm.t, *tm.pos, *tm.vel, tm.soc_pct, tm.voltage, tm.current_a,
                      tm.used_wh, tm.cell_count, tm.next_wp, tm.link_pct,
                      tm.wind.speed_mps, tm.wind.from_deg]
            values += [v for k, v in vars(self.v).items() if k not in ("vehicle_id", "airframe_profile")]  # 機型檔由 load_airframe 驗證
            values += list(vars(self.cfg).values()) + [self.calib, *self.home]
            if not all(self._finite(x) for x in values):
                return "遙測／機型／設定含非有限數值"
            if (tm.cell_count <= 0 or tm.cell_count != int(tm.cell_count)
                    or self.v.battery_wh <= 0 or self.v.eta <= 0 or self.v.cruise_mps <= 0
                    or self.calib <= 0 or self.v.calib <= 0):
                return "芯數、容量、效率、速度與校正係數須為正值"
            if (tm.next_wp != int(tm.next_wp) or not 0 <= tm.soc_pct <= 100
                    or not 0 <= tm.link_pct <= 100 or tm.voltage <= 0
                    or tm.used_wh < 0 or tm.wind.speed_mps < 0):
                return "遙測超出有效範圍"
            if (self.cfg.wind_limit_mps <= 0 or self.cfg.horizon_s < 0
                    or not 0 <= self.cfg.reserve_pct <= 100
                    or not 0 <= self.cfg.emergency_rtl_min_pct <= 100):
                return "告警設定超出有效範圍"
            if (len(self.home) != 3 or len(self.route_idx) != len(self.route)
                    or any(len(p) != 3 or not all(self._finite(x) for x in p) for p in self.route)
                    or any(not isinstance(k, int) or isinstance(k, bool)
                           or not 0 <= k < self.total_wps for k in self.route_idx)
                    or (self.prio is not None and len(self.prio) != self.total_wps)):
                return "航線／原索引／優先級不一致"
        except (AttributeError, TypeError, ValueError, OverflowError):
            return "遙測／機型／航線格式不符"
        return None

    def _validate_next_wp(self, tm):
        """Reject invalid route cursors before mutating any engine state.

        len(route) is the existing completed-route sentinel; zero is valid for
        an empty route. Integral numeric inputs retain legacy normalization.
        Contract v5 batch 1 replaces silent boundary clamping with ValueError.
        """
        index = tm.next_wp
        if (not self._finite(index) or index != int(index)
                or not 0 <= index <= len(self.route)):
            raise ValueError("next_wp must be an integer in [0, len(route)]")
        return replace(tm, next_wp=int(index))

    # ---------- 線上校正 ----------
    def _update_calib(self, tm: Telemetry):
        gs = math.hypot(tm.vel[0], tm.vel[1])
        if gs < 2.0 or tm.pos[2] < 5.0:
            return
        wx, wy = tm.wind.vector()
        air = math.hypot(tm.vel[0] - wx, tm.vel[1] - wy)
        p_model = air_power_w(self.v, air)
        if abs(tm.vel[2]) > 0.5 or p_model <= 0:
            return
        ratio = (tm.voltage * tm.current_a) / p_model
        self.calib += 0.02 * (min(2.0, max(0.6, ratio)) - self.calib)

    def _vehicle(self) -> Vehicle:
        return with_calib(self.v, self.calib)

    # ---------- 可用能量 ----------
    def _available_wh(self, tm: Telemetry):
        """回傳 (可用 Wh, 依據, 電壓推估總容量 Wh 或 None)。"""
        e_soc = tm.soc_pct / 100.0 * self.v.battery_wh
        cell_v = tm.voltage / tm.cell_count + tm.current_a * self.cfg.cell_r_ohm
        if self._cell_hist and (tm.used_wh < self._cell_hist[-1][1] or tm.t < self._cell_hist[-1][0]):
            self._cell_hist.clear()           # 換電池／能量計或時鐘重設，禁止跨段擬合
        self._cell_hist.append((tm.t, tm.used_wh, cell_v))
        while self._cell_hist and self._cell_hist[0][0] < tm.t - 600.0:
            self._cell_hist.popleft()
        pts = list(self._cell_hist)
        if len(pts) < 90 or pts[-1][1] - pts[0][1] < 0.08 * self.v.battery_wh:
            return e_soc, "soc", None
        b, a, r2 = linfit([p[1] for p in pts], [p[2] for p in pts])
        if b >= -1e-6 or r2 < 0.8:
            return e_soc, "soc", None
        total = (self.cfg.cell_empty_v - a) / b       # 用到多少 Wh 時電壓到 0%
        e_volt = max(0.0, total - tm.used_wh)
        if e_volt < e_soc:
            return e_volt, "voltage", total
        return e_soc, "soc", total

    # ---------- 剩餘航線 ----------
    def _remaining(self, tm: Telemetry):
        return [tuple(tm.pos)] + self.route[tm.next_wp:]

    def _walk(self, path, veh: Vehicle, wind: Wind, speed=None):
        """沿 path 累計，回傳每個點 [(idx_in_path, cum_wh, cum_s, rtl_wh_from_here)]。"""
        out, cum_e, cum_t = [], 0.0, 0.0
        for i, p in enumerate(path):
            if i > 0:
                lg = leg_energy(veh, path[i - 1], p, wind, speed)
                cum_e += lg["energy_wh"]
                cum_t += lg["time_s"]
            rtl_e = rtl_energy(p, self.home, veh, wind)["energy_wh"]
            if not all(self._finite(x) and x >= 0 for x in (cum_e, cum_t, rtl_e)):
                raise ValueError("航段估計須為有限非負值")
            out.append((i, cum_e, cum_t, rtl_e))
        return out

    def _plan_wind(self, tm: Telemetry) -> Wind:
        """預測剩餘航線用的風：風速有穩定上升趨勢時，外推到剩餘航程的一半（不超過抗風上限）。"""
        b, r2 = self._wind_trend
        if b <= 0.002 or r2 < 0.6:
            return tm.wind
        horizon = min(self.last_state.get("rem_s", 0.0), 900.0) / 2.0
        s = min(self.cfg.wind_limit_mps, tm.wind.speed_mps + b * horizon)
        return Wind(max(s, tm.wind.speed_mps), tm.wind.from_deg)

    # ---------- P1 + P2 ----------
    def _battery_route(self, tm: Telemetry, avail_wh, basis, total_cap) -> list[Finding]:
        if not self.route:
            return []                        # P1/P2 無航線時不成立，P3/P4/P5 另行處理
        veh = self._vehicle()
        wind = self._plan_wind(tm)
        reserve_wh = self.cfg.reserve_pct / 100.0 * self.v.battery_wh
        path = self._remaining(tm)
        walk = self._walk(path, veh, wind)
        self.last_state["rem_s"] = walk[-1][2]
        need_end = walk[-1][1] + walk[-1][3]
        end_pct = (avail_wh - need_end) / self.v.battery_wh * 100.0
        if not self._finite(end_pct):
            raise ValueError("落地電量估計非有限數值")
        n_rem = len(path) - 1
        # 第一個不安全點即停止，不能跨過不安全航段選到更後面的安全點。
        pnr = None
        unsafe = False
        for i, cum_e, cum_t, rtl_e in walk:
            ident = (self._option_identity("C4", "A_RTL_NOW") if i == 0 else
                     self._option_identity("C3", "A_RTL_AFTER_WP",
                                           self._orig(tm.next_wp + i - 1)))
            raw = (avail_wh - cum_e - rtl_e) / self.v.battery_wh * 100.0
            # Apply each physical return point's 20/22 memory BEFORE selection.
            # Stop at the first disqualified point; never leap over an unsafe leg.
            if not self._is_feasible(raw, ident):
                unsafe = True
                break
            pnr = (i, cum_e, cum_t, rtl_e)
        # 遲滯：低於保留值 0.5% 才發，回到保留值 +2% 以上才解除
        was = "battery_route" in self._active
        feasible = end_pct >= self.cfg.reserve_pct + (2.0 if was else -0.5)

        ev = [
            {"id": "E1", "text": "預估完成航線並返航後的落地電量", "value": f"{end_pct:.1f}%",
             "display_value": landing_pct_text(end_pct)},
            {"id": "E2", "text": "落地保留電量設定", "value": f"{self.cfg.reserve_pct:.0f}%"},
            {"id": "E3", "text": "目前可用能量（依據）", "value": f"{avail_wh:.0f} Wh（{'電壓趨勢' if basis == 'voltage' else '飛控電量%'}）"},
            {"id": "E4", "text": "實測耗電 / 模型耗電", "value": f"{self.calib:.2f} 倍"},
            {"id": "E5", "text": "預測用風速（目前＋趨勢外推）、風向", "value": f"{wind.speed_mps:.1f} m/s（目前 {tm.wind.speed_mps:.1f}）、{wind.from_deg:.0f}°"},
            {"id": "E6", "text": "剩餘航點數", "value": f"{n_rem}"},
        ]
        self.last_state.update({"end_pct": end_pct, "avail_wh": avail_wh, "basis": basis,
                                "calib": self.calib, "pnr_wp": None, "pnr_eta_s": None})

        cands = self._candidates(tm, path, walk, avail_wh, reserve_wh, pnr, wind)
        out = []
        f1 = Finding("battery_route", active=not feasible, evidence=ev, candidates=cands)
        if not feasible:
            short = self.cfg.reserve_pct - end_pct
            f1.severity = SEV_WARNING if end_pct > 5 else SEV_CRITICAL
            f1.title = "電量不足以飛完航線" if n_rem > 0 else "返航落地電量將低於保留值"
            f1.value = f"預估落地 {landing_pct_text(end_pct)}（保留 {self.cfg.reserve_pct:.0f}%，差 {max(0.0, short):.0f}%）"
            f1.rule_choice = self._rule_pick(cands, self.cfg.emergency_rtl_min_pct)
        out.append(f1)

        # P2：沿途出現首個不安全點就提示，不能被更後方的安全點掩蓋。
        f2 = Finding("rtl_point", active=False, candidates=cands)
        if unsafe and n_rem > 0:
            if pnr is None:
                f2.active = True
                f2.severity = SEV_CRITICAL
                f2.title = "已無足夠返航餘裕"
                f2.value = "目前位置返航也無法保住保留電量，請人工判斷"
                f2.lead_s = 0.0
            elif pnr[0] == 0:
                f2.active = True
                f2.severity = SEV_CRITICAL
                f2.title = "已到最晚返航點"
                f2.value = "現在返航才能保住保留電量"
                f2.lead_s = 0.0
            else:
                wp_idx = self._orig(tm.next_wp + pnr[0] - 1)
                eta = pnr[2]
                self.last_state.update({"pnr_wp": wp_idx, "pnr_eta_s": eta})
                if eta <= self.cfg.horizon_s:
                    f2.active = True
                    f2.severity = SEV_WARNING if eta > 60 else SEV_CRITICAL
                    f2.title = "即將到達最晚返航點"
                    f2.value = f"WP{wp_idx + 1}，約 {eta / 60:.1f} 分鐘後"
                    f2.lead_s = eta
            f2.evidence = ev + [{"id": "E7", "text": "最晚返航點與到達時間",
                                 "value": f2.value or "—"}]
            f2.rule_choice = self._rule_pick(cands, self.cfg.emergency_rtl_min_pct)
        out.append(f2)

        return out

    def _battery_capacity(self, tm, avail_wh, total_cap):
        # P3 獨立處理，P1/P2 例外或空航線時仍能更新。
        f3 = Finding("battery_capacity", active=False)
        if total_cap is not None:
            ratio = total_cap / self.v.battery_wh
            self.last_state["capacity_ratio"] = ratio
            e_soc = tm.soc_pct / 100.0 * self.v.battery_wh
            gap_pct = (e_soc - avail_wh) / self.v.battery_wh * 100.0
            if ratio < 0.9 and gap_pct > 3:
                f3.active = True
                f3.severity = SEV_WARNING
                f3.title = "電池實際容量低於標稱"
                f3.value = f"約為標稱 {ratio * 100:.0f}%，飛控電量% 偏高約 {gap_pct:.0f}%"
                f3.evidence = [
                    {"id": "E1", "text": "電壓趨勢推估的總容量", "value": f"{total_cap:.0f} Wh"},
                    {"id": "E2", "text": "電池標稱容量", "value": f"{self.v.battery_wh:.0f} Wh"},
                    {"id": "E3", "text": "飛控電量%", "value": f"{tm.soc_pct:.0f}%"},
                    {"id": "E4", "text": "電壓推估的實際剩餘", "value": f"{avail_wh / self.v.battery_wh * 100:.0f}%"},
                ]
                f3.candidates = [
                    {"id": "C1", "action": "A_USE_VOLTAGE_ESTIMATE", "label": "後續預測改用電壓推估", "energy_feasible": None, "feasible": True},
                    {"id": "C2", "action": "A_CONTINUE_MONITOR", "label": "持續觀察", "energy_feasible": None, "feasible": True},
                ]
                f3.rule_choice = "C1"
        return f3

    def _candidates(self, tm, path, walk, avail_wh, reserve_wh, pnr, wind):
        veh = self._vehicle()
        done = tm.next_wp
        cands = []

        def pct(e):
            return (avail_wh - e) / self.v.battery_wh * 100.0

        def candidate(ident, action, label, energy, planned=(), **extra):
            raw = pct(energy)
            if not self._finite(raw):
                raise ValueError("候選電量估計非有限數值")
            identity = self._option_identity(ident, action, extra.get("param"))
            energy_ok = self._is_feasible(raw, identity)
            c = {"id": ident, "option_identity": identity, "action": action, "label": label, "end_pct_raw": raw,
                 "end_pct": round(raw, 1), "end_pct_zh": landing_pct_text(raw), "completion_pct": round(self._completion(planned), 1),
                 "energy_feasible": energy_ok, "feasible": energy_ok, **extra}
            if action == "A_LAND_NOW":
                c.update(operational_status="unknown", feasible=False)
            return c

        end_e = walk[-1][1] + walk[-1][3]
        cands.append(candidate("C1", "A_CONTINUE", "照原航線繼續", end_e, self.route_idx[done:]))
        # 降速到最省電空速
        best = None
        for a10 in range(40, int(veh.cruise_mps * 10) + 1, 5):
            a = a10 / 10.0
            w = self._walk(path, veh, wind, speed=a)
            e = w[-1][1] + w[-1][3]
            if best is None or e < best[1]:
                best = (a, e)
        if best and len(path) > 2 and best[0] < veh.cruise_mps - 0.4 and pct(best[1]) > pct(end_e) + 1.0:
            cands.append(candidate("C2", "A_REDUCE_SPEED", f"降速到 {best[0]:.1f} m/s 飛完",
                                   best[1], self.route_idx[done:], param=best[0]))
        # 飛到最晚返航點後返航
        if pnr is not None and 0 < pnr[0] < len(path) - 1:
            pos = done + pnr[0] - 1
            wp_idx = self._orig(pos)
            miss = self._required_left(pos + 1)
            label = f"飛完 WP{wp_idx + 1} 後返航" + (f"（漏掉必要目標 {miss} 個）" if miss else "")
            cands.append(candidate("C3", "A_RTL_AFTER_WP", label, pnr[1] + pnr[3],
                                   self.route_idx[done:pos + 1], param=wp_idx, param_pos=pos, missed_required=miss))
        # 跳過選配目標，只飛必要的
        if self.prio:
            keep = [k for k in range(done, len(self.route)) if self.prio[self.route_idx[k]] == 1]
            if len(keep) < len(self.route) - done:
                sub = [tuple(tm.pos)] + [self.route[k] for k in keep]
                w = self._walk(sub, veh, wind)
                skipped = len(self.route) - done - len(keep)
                cands.append(candidate("C6", "A_SKIP_OPTIONAL", f"跳過 {skipped} 個選配目標，只飛必要的",
                                       w[-1][1] + w[-1][3], [self.route_idx[k] for k in keep],
                                       param=[self.route_idx[k] for k in keep], missed_required=0))
        miss_now = self._required_left(done)
        # 立即返航
        cands.append(candidate("C4", "A_RTL_NOW", "立即返航", walk[0][3], missed_required=miss_now))
        # 就地降落（回不了家時）
        land = leg_energy(veh, tm.pos, (tm.pos[0], tm.pos[1], self.home[2]), wind)["energy_wh"]
        cands.append(candidate("C5", "A_LAND_NOW", "就地降落", land, missed_required=miss_now))
        return cands

    @staticmethod
    def _rule_pick(cands, emergency_rtl_min_pct=None):
        """規則：可行選項（不含就地降落）裡漏掉必要目標最少、完成度最高者，同分取電量多者；
        都不可行時，只給緊急備選供 HOLD 顯示，不授權套用。"""
        if not cands:
            return None
        if emergency_rtl_min_pct is None:
            emergency_rtl_min_pct = Config().emergency_rtl_min_pct
        ok = [c for c in cands if c["feasible"] and c["action"] != "A_LAND_NOW"]
        if ok:   # 先保住必要目標，再看完成度、剩餘電量
            return max(ok, key=lambda c: (-c.get("missed_required", 0), c.get("completion_pct", 0),
                                          c.get("end_pct_raw", c.get("end_pct", -math.inf))))["id"]
        rtl = next((c for c in cands if c["action"] == "A_RTL_NOW"), None)
        if rtl and rtl.get("end_pct_raw", rtl.get("end_pct", -math.inf)) >= emergency_rtl_min_pct:
            return rtl["id"]
        return max(cands, key=lambda c: c.get("end_pct_raw", c.get("end_pct", -math.inf)))["id"]

    # ---------- P4 鏈路 ----------
    def _link(self, tm: Telemetry) -> Finding:
        d_now = math.hypot(tm.pos[0] - self.home[0], tm.pos[1] - self.home[1])
        self._link_hist.append((d_now, tm.link_pct))
        f = Finding("link_route", active=False)
        pts = list(self._link_hist)
        ds = [p[0] for p in pts]
        if len(pts) < 60 or max(ds) - min(ds) < 300:
            return f
        b, a, r2 = linfit(ds, [p[1] for p in pts])
        if b >= 0 or r2 < 0.5:
            return f
        # 沿剩餘航線找第一個預估品質低於門檻的航點
        veh, wind = self._vehicle(), tm.wind
        path = self._remaining(tm)
        t_cum = 0.0
        for i in range(1, len(path)):
            t_cum += leg_energy(veh, path[i - 1], path[i], wind)["time_s"]
            d = math.hypot(path[i][0] - self.home[0], path[i][1] - self.home[1])
            q = a + b * d
            if q < self.cfg.link_min_pct:
                wp = self._orig(tm.next_wp + i - 1)
                f.active = True
                # The committed alert level owns hysteresis; the core still
                # requires ten continuous seconds before a downgrade commits.
                state = self._states.states.get(f.key)
                was_warning = (state is not None and state.active
                               and state.severity <= SEV_WARNING)
                warn = (t_cum <= self.cfg.link_warn_enter_s
                        or (was_warning and t_cum <= self.cfg.link_warn_exit_s))
                f.severity = SEV_WARNING if warn else SEV_NOTICE
                f.title = "航線前方可能斷訊"
                f.value = f"WP{wp + 1}（離家 {d / 1000:.2f} km）預估鏈路 {max(0, q):.0f}%，約 {t_cum / 60:.1f} 分鐘後"
                f.lead_s = t_cum
                f.evidence = [
                    {"id": "E1", "text": "目前鏈路品質／離家距離", "value": f"{tm.link_pct:.0f}%／{d_now / 1000:.2f} km"},
                    {"id": "E2", "text": "每遠 1 km 鏈路下降", "value": f"{-b * 1000:.0f}%（R²={r2:.2f}）"},
                    {"id": "E3", "text": "預估最差航點", "value": f"WP{wp + 1}，{max(0, q):.0f}%"},
                    {"id": "E4", "text": "弱鏈路門檻", "value": f"{self.cfg.link_min_pct:.0f}%"},
                ]
                f.candidates = [
                    {"id": "C1", "action": "A_CONTINUE_MONITOR", "label": "繼續並確認失聯保護（RTL）已開", "energy_feasible": None, "feasible": True},
                ]
                prev_pos = tm.next_wp + i - 2
                if prev_pos >= 0:
                    prev_wp = self._orig(prev_pos)
                    f.candidates.append({"id": "C2", "action": "A_RTL_AFTER_WP",
                                         "label": f"飛完 WP{prev_wp + 1} 後返航", "energy_feasible": None,
                                         "feasible": False, "param": prev_wp, "param_pos": prev_pos})
                else:
                    f.candidates.append({"id": "C2", "action": "A_RTL_NOW", "label": "立即返航",
                                         "energy_feasible": None, "feasible": False})
                f.rule_choice = "C1"
                break
        return f

    # ---------- P5 風速 ----------
    def _wind(self, tm: Telemetry) -> Finding:
        self._wind_hist.append((tm.t, tm.wind.speed_mps))
        f = Finding("wind_trend", active=False)
        pts = list(self._wind_hist)
        b, a, r2 = (linfit([p[0] for p in pts], [p[1] for p in pts])
                    if len(pts) >= 60 else (0.0, tm.wind.speed_mps, 0.0))
        self._wind_trend = (b, r2)
        lim = self.cfg.wind_limit_mps
        if tm.wind.speed_mps >= lim:
            tts = 0.0
        elif b > 0.002 and r2 > 0.6:
            tts = max(0.0, (lim - (a + b * tm.t)) / b)
        else:
            return f
        if tts <= self.cfg.horizon_s:
            f.active = True
            f.severity = SEV_WARNING if tts > 0 else SEV_CRITICAL
            f.title = "風速將超過抗風上限" if tts > 0 else "風速已超過抗風上限"
            f.value = f"現在 {tm.wind.speed_mps:.1f} m/s，每分鐘 +{b * 60:.1f}，約 {tts / 60:.1f} 分鐘後達 {lim:.0f} m/s"
            f.lead_s = tts
            f.evidence = [
                {"id": "E1", "text": "目前風速", "value": f"{tm.wind.speed_mps:.1f} m/s"},
                {"id": "E2", "text": "近 3 分鐘風速趨勢", "value": f"+{b * 60:.2f} m/s/分（R²={r2:.2f}）"},
                {"id": "E3", "text": "機體抗風上限", "value": f"{lim:.0f} m/s"},
            ]
            f.candidates = [
                {"id": "C1", "action": "A_CONTINUE_MONITOR", "label": "持續觀察風速", "energy_feasible": None, "feasible": True},
                {"id": "C2", "action": "A_RTL_NOW", "label": "立即返航", "energy_feasible": None, "feasible": False},
            ]
            f.rule_choice = "C1" if tts > 120 else "C2"
        return f

    # ---------- 主流程 ----------
    def update(self, tm: Telemetry) -> list[dict]:
        """吃一筆遙測，回傳這一刻的告警事件（raise / update / resolve）。"""
        if isinstance(tm, Telemetry):
            tm = self._validate_next_wp(tm)
        if isinstance(tm, Telemetry) and self._finite(tm.t):
            if self._last_tm_t is not None and tm.t <= self._last_tm_t:
                return []  # duplicate/out-of-order snapshots never mutate histories
            self._last_tm_t = tm.t
        error = self._input_error(tm)
        self.last_state.update({"data_status": "insufficient" if error else "ok", "input_error": error,
                                "predictor_errors": {}, "end_pct": None, "pnr_wp": None,
                                "pnr_eta_s": None,
                                "rem_s": self.last_state.get("rem_s", 0.0) if not error and self.route else 0.0,
                                "capacity_ratio": None, "avail_wh": None})
        if error:
            self._pending_choice.clear()       # 資料缺口不算建議連續成立
            self._streak.clear()
            return (self._unknown_all(tm.t) if isinstance(tm, Telemetry)
                    and self._finite(tm.t) else [])
        self._reached.update(self.route_idx[:tm.next_wp])

        def attempt(key, fn):
            try:
                return fn()
            except Exception as exc:
                self.last_state["predictor_errors"][key] = type(exc).__name__
                self._pending_choice.pop(key, None)
                self._streak.pop(key, None)
                return None

        def calibrate():
            before = self.calib
            try:
                self._update_calib(tm)
                if not self._finite(self.calib) or self.calib <= 0:
                    raise ValueError("校正係數非有限正值")
            except Exception:
                self.calib = before
                raise

        attempt("calibration", calibrate)
        wind_f = attempt("wind_trend", lambda: self._wind(tm))  # 先算趨勢，P1/P2 要用
        if wind_f is None:
            self._wind_trend = (0.0, 0.0)
        available = attempt("available_energy", lambda: self._available_wh(tm))
        findings = []
        avail = None
        if available is not None:
            avail, basis, cap = available
            if not self._finite(avail) or (cap is not None and not self._finite(cap)):
                self.last_state["predictor_errors"]["available_energy"] = "ValueError"
                avail = None
            else:
                self.last_state.update(avail_wh=avail, basis=basis, calib=self.calib)
                if self.route:
                    battery = attempt("battery_route", lambda: self._battery_route(tm, avail, basis, cap))
                    if battery is not None:
                        findings.extend(battery)
                    else:
                        self.last_state.update(end_pct=None, pnr_wp=None, pnr_eta_s=None, rem_s=0.0)
                capacity = attempt("battery_capacity", lambda: self._battery_capacity(tm, avail, cap))
                if capacity is not None:
                    findings.append(capacity)
        link_f = attempt("link_route", lambda: self._link(tm))
        findings.extend(f for f in (link_f, wind_f) if f is not None)
        # P4/P5 的返航建議亦須有能量證據；監控/估計類選項不代表飛行操作可行。
        for f in (link_f, wind_f):
            if f is not None and f.active:
                attempt(f.key, lambda f=f: self._assess_advisory(f, tm, avail))
                pick = next((c for c in f.candidates if c["id"] == f.rule_choice), None)
                if pick is None or pick.get("feasible") is not True:
                    f.rule_choice = self._rule_pick(f.candidates, self.cfg.emergency_rtl_min_pct)
        events = []
        seen = {f.key for f in findings}
        for key in ("battery_route", "rtl_point", "battery_capacity", "link_route", "wind_trend"):
            if key not in seen:               # 預測器缺資料／例外不跨缺口累積遲滯
                self._pending_choice.pop(key, None)
                self._streak.pop(key, None)
                events.extend(self._unknown(tm.t, key))
        if self.last_state["predictor_errors"]:
            self.last_state["data_status"] = "partial"
        for f in findings:
            events.extend(self._debounce(tm.t, f))
        return events

    def _assess_advisory(self, f, tm, avail):
        """補齊 P4/P5 飛行候選的能量判斷；失敗保持不可行。"""
        for c in f.candidates:
            if c["action"] not in ("A_RTL_NOW", "A_RTL_AFTER_WP") or avail is None:
                continue
            pos = c.get("param_pos", tm.next_wp - 1)
            path = [tuple(tm.pos)] + self.route[tm.next_wp:pos + 1]
            walk = self._walk(path, self._vehicle(), tm.wind)
            raw = (avail - walk[-1][1] - walk[-1][3]) / self.v.battery_wh * 100.0
            if not self._finite(raw):
                raise ValueError("返航候選能量非有限數值")
            identity = self._option_identity(c["id"], c["action"], c.get("param"), scope=f.key)
            c["option_identity"] = identity
            energy_ok = self._is_feasible(raw, identity)
            c.update(end_pct_raw=raw, end_pct=round(raw, 1), end_pct_zh=landing_pct_text(raw),
                     energy_feasible=energy_ok, feasible=energy_ok,
                     completion_pct=round(self._completion(self.route_idx[tm.next_wp:pos + 1]), 1))
        pick = next((c for c in f.candidates if c["id"] == f.rule_choice), None)
        if pick is None or not pick.get("feasible"):
            f.rule_choice = self._rule_pick(f.candidates, self.cfg.emergency_rtl_min_pct)

    def _unknown_all(self, t):
        events = []
        for key in list(self._states.states):
            events.extend(self._unknown(t, key))
        return events

    def _unknown(self, t, key):
        if key not in self._states.states:
            return []
        previous = self._active.get(key)
        facts = self._event(t, "update", previous) if previous else {}
        rows = self._states.step(key, t, UNKNOWN, **self._state_facts(facts))
        return self._sync_state(key, previous, rows)

    @staticmethod
    def _state_facts(facts):
        # step owns these explicit arguments and event metadata.
        return {k: v for k, v in facts.items()
                if k not in ("key", "t", "type", "severity")}

    def _sync_state(self, key, finding, rows):
        state = self._states.states[key]
        candidates = finding.candidates if finding is not None else []
        choice = next((c["id"] for c in candidates
                       if self._recommendation_key(c) == state.recommendation), None)
        if state.active and finding is not None:
            self._active[key] = replace(finding, severity=state.severity,
                                        rule_choice=choice,
                                        prediction_expired=state.prediction_expired)
        elif not state.active:
            self._active.pop(key, None)
        for row in rows:
            row["t"] = row["output_t"]
            identity = row["recommendation"]
            row["recommendation_identity"] = identity
            row["rule_choice"] = row["recommendation"] = next(
                (c["id"] for c in row.get("candidates", [])
                 if self._recommendation_key(c) == identity), None)
            row["rule_decision"] = "SELECT" if any(
                c["id"] == row["rule_choice"] and c.get("feasible") is True
                for c in row.get("candidates", [])) else "HOLD"
        return rows

    def _recommendation_eligible(self, candidate, retained=False):
        """Joint feasibility is necessary; new energy advice also needs +2%.

        Option energy qualification is shared with PNR/route calculations and
        deliberately remains unchanged. Recommendation entry is per alert, so
        an option qualified long ago cannot enter a new recommendation at 21%.
        Monitoring/estimation advice carries no landing estimate.
        """
        if candidate.get("feasible") is not True:
            return False
        if candidate.get("action") in ("A_CONTINUE_MONITOR", "A_USE_VOLTAGE_ESTIMATE"):
            return True
        raw = candidate.get("end_pct_raw")
        return (self._finite(raw)
                and raw >= self.cfg.reserve_pct + (0.0 if retained else 2.0))

    def _debounce(self, t, f: Finding):
        """Contract v5 seconds, cooling, downgrade and recommendation timing.

        This adapter still receives legacy complete snapshots. Per-source TTL,
        separate sensed/recv timestamps and battery merging are the next batch.
        """
        state = self._states.states.get(f.key)
        if state is not None and state.last_t is not None and t <= state.last_t:
            return []
        previous = self._active.get(f.key)
        payload = f if f.active or previous is None else previous
        facts = self._state_facts(self._event(t, "update", payload))
        facts["route_version"] = self._route_revision
        retained = state.recommendation if state is not None and state.active else None
        eligible = [c for c in f.candidates if self._recommendation_eligible(
            c, retained=retained is not None and self._recommendation_key(c) == retained)]
        selected = next((c for c in eligible if c["id"] == f.rule_choice), None)
        if selected is None and eligible:
            # Re-rank genuinely eligible alternatives; never hide a 23% option
            # behind the old rank winner that now needs 22% to enter.
            choice = self._rule_pick(eligible, self.cfg.emergency_rtl_min_pct)
            selected = next((c for c in eligible if c["id"] == choice), None)
        recommendation = self._recommendation_key(selected) if selected else None
        rows = self._states.step(
            f.key, t, TRUE if f.active else FALSE, f.severity, recommendation,
            {self._recommendation_key(c) for c in eligible},
            max_gap_s=10.0 if f.key == "wind_trend" else 3.0,
            **facts)
        return self._sync_state(f.key, payload, rows)

    @staticmethod
    def _rule_decision(f):
        return "SELECT" if any(c.get("feasible") is True for c in f.candidates) else "HOLD"

    @staticmethod
    def _event(t, kind, f: Finding):
        return {"t": t, "type": kind, "key": f.key, "severity": f.severity, "title": f.title,
                "value": f.value, "lead_s": f.lead_s, "evidence": f.evidence,
                "candidates": f.candidates, "rule_choice": f.rule_choice,
                "rule_decision": PredictiveAlertEngine._rule_decision(f)}

    def current_state(self, key):
        """Live explainer gate, including changes that emitted no rule event."""
        state = self._states.states.get(key)
        finding = self._active.get(key)
        if state is None:
            return None
        return {"active": bool(state.active and not state.prediction_expired
                               and state.facts.get("route_version") == self._route_revision),
                "alert_version": state.version,
                "feasible_ids": [c["id"] for c in finding.candidates
                                 if c.get("feasible") is True] if finding else []}

    def apply_explanation(self, key, expected_version, result):
        """Recheck the live state; append a new engine output, never edit history."""
        current = self.current_state(key)
        if (current is None or current["active"] is not True
                or current["alert_version"] != expected_version
                or not isinstance(result, dict)
                or result.get("source") not in ("llm", "rule")
                or not isinstance(result.get("text"), dict)):
            return None
        state = self._states.states[key]
        finding = self._active.get(key)
        if finding is None:
            return None
        from .explain import validate, rule_text
        event = {**deepcopy(state.facts), "key": key, "active": True,
                 "alert_version": state.version, "severity": state.severity}
        if result["source"] == "llm":
            if validate(result.get("text"), event, current):
                return None
        else:
            # A completed fallback must use today's rule choice, not the
            # request's possibly obsolete feasible set or numeric predictions.
            event.update(rule_choice=finding.rule_choice,
                         rule_decision="SELECT" if finding.rule_choice in current["feasible_ids"] else "HOLD")
            result = {**deepcopy(result), "text": rule_text(event)}
        row = self._states.explanation_update(key, expected_version, state.last_t, result)
        if row is None:
            return None
        return self._sync_state(key, finding, [row])[0]

    def close_explanation(self, original, reason):
        """Allocate a terminal journal row for an invalidated request only."""
        state = self._states.states.get(original["key"])
        when = max(original["output_t"], state.last_t if state and state.last_t is not None
                   else original["output_t"])
        return self._states.explanation_closed(original, when, reason)

    def active(self):
        return dict(self._active)
