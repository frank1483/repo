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
from collections import deque
from dataclasses import dataclass, field

from .energy_api import Vehicle, Wind, air_power_w, leg_energy, rtl_energy, with_calib

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
    reserve_pct: float = 20.0
    wind_limit_mps: float = 12.0
    link_min_pct: float = 35.0
    cell_r_ohm: float = 0.004         # 單芯內阻（電壓補償用）
    cell_empty_v: float = 3.55        # 補償後單芯電壓到這裡視為 0%
    raise_ticks: int = 3              # 連續成立幾次才發
    clear_ticks: int = 10             # 連續不成立幾次才解除
    horizon_s: float = 300.0          # 趨勢預測看多遠


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


class PredictiveAlertEngine:
    def __init__(self, route, home, vehicle: Vehicle, config: Config | None = None):
        self.route = [tuple(p) for p in route]
        self.total_wps = len(self.route)       # 完成度一律對原始航線算
        self.home = tuple(home)
        self.v = vehicle
        self.cfg = config or Config()
        self.calib = vehicle.calib
        self._cell_hist = deque(maxlen=600)    # (used_wh, 補償後單芯電壓)
        self._link_hist = deque(maxlen=900)    # (離家距離, 品質)
        self._wind_hist = deque(maxlen=180)    # (t, 風速)
        self._streak: dict[str, int] = {}
        self._active: dict[str, Finding] = {}
        self._announced: dict[str, tuple] = {}   # key -> (severity, choice) 最後一次說明時
        self._pending_choice: dict[str, tuple] = {}
        self._wind_trend = (0.0, 0.0)            # (每秒變化, R²)
        self.last_state: dict = {}

    def set_route(self, route):
        """操作員改了航線（例如採用「飛完 WPn 後返航」）。航點索引沿用原航線。"""
        self.route = [tuple(p) for p in route]

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
        self._cell_hist.append((tm.used_wh, cell_v))
        pts = list(self._cell_hist)
        if len(pts) < 90 or pts[-1][0] - pts[0][0] < 0.08 * self.v.battery_wh:
            return e_soc, "soc", None
        b, a, r2 = linfit([p[0] for p in pts], [p[1] for p in pts])
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
            out.append((i, cum_e, cum_t, rtl_energy(p, self.home, veh, wind)["energy_wh"]))
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
        veh = self._vehicle()
        wind = self._plan_wind(tm)
        reserve_wh = self.cfg.reserve_pct / 100.0 * self.v.battery_wh
        path = self._remaining(tm)
        walk = self._walk(path, veh, wind)
        self.last_state["rem_s"] = walk[-1][2]
        need_end = walk[-1][1] + walk[-1][3]
        end_pct = (avail_wh - need_end) / self.v.battery_wh * 100.0
        n_rem = len(path) - 1
        total_wps = len(self.route)

        # 最晚返航點：最後一個「飛到這裡再返航仍有保留電量」的點
        pnr = None
        for i, cum_e, cum_t, rtl_e in walk:
            if avail_wh - cum_e - rtl_e >= reserve_wh:
                pnr = (i, cum_e, cum_t, rtl_e)
        # 遲滯：低於保留值 0.5% 才發，回到保留值 +2% 以上才解除
        was = "battery_route" in self._active
        feasible = end_pct >= self.cfg.reserve_pct + (2.0 if was else -0.5)

        ev = [
            {"id": "E1", "text": "預估完成航線並返航後的落地電量", "value": f"{end_pct:.1f}%"},
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
            f1.value = f"預估落地 {end_pct:.0f}%（保留 {self.cfg.reserve_pct:.0f}%，差 {max(0.0, short):.0f}%）"
            f1.rule_choice = self._rule_pick(cands)
        out.append(f1)

        # P2：只有航線本身不可行時，最晚返航點才有意義
        f2 = Finding("rtl_point", active=False, candidates=cands)
        if not feasible and n_rem > 0:
            if pnr is None or pnr[0] == 0:
                f2.active = True
                f2.severity = SEV_CRITICAL
                f2.title = "已到最晚返航點"
                f2.value = "現在返航才能保住保留電量"
                f2.lead_s = 0.0
            else:
                wp_idx = tm.next_wp + pnr[0] - 1
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
            f2.rule_choice = self._rule_pick(cands)
        out.append(f2)

        # P3：電壓推估的實際容量比標稱少很多
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
                    {"id": "C1", "action": "A_USE_VOLTAGE_ESTIMATE", "label": "後續預測改用電壓推估", "feasible": True},
                    {"id": "C2", "action": "A_CONTINUE_MONITOR", "label": "持續觀察", "feasible": True},
                ]
                f3.rule_choice = "C1"
        out.append(f3)
        return out

    def _candidates(self, tm, path, walk, avail_wh, reserve_wh, pnr, wind):
        veh = self._vehicle()
        total = self.total_wps
        done = tm.next_wp
        cands = []

        def pct(e):
            return (avail_wh - e) / self.v.battery_wh * 100.0

        end_e = walk[-1][1] + walk[-1][3]
        cands.append({"id": "C1", "action": "A_CONTINUE", "label": "照原航線繼續",
                      "end_pct": round(pct(end_e), 1), "completion_pct": 100.0})
        # 降速到最省電空速
        best = None
        for a10 in range(40, int(veh.cruise_mps * 10) + 1, 5):
            a = a10 / 10.0
            w = self._walk(path, veh, wind, speed=a)
            e = w[-1][1] + w[-1][3]
            if best is None or e < best[1]:
                best = (a, e)
        if best and len(path) > 2 and best[0] < veh.cruise_mps - 0.4 and pct(best[1]) > pct(end_e) + 1.0:
            cands.append({"id": "C2", "action": "A_REDUCE_SPEED", "label": f"降速到 {best[0]:.1f} m/s 飛完",
                          "end_pct": round(pct(best[1]), 1), "completion_pct": 100.0, "param": best[0]})
        # 飛到最晚返航點後返航
        if pnr is not None and 0 < pnr[0] < len(path) - 1:
            wp_idx = done + pnr[0] - 1
            comp = (wp_idx + 1) / total * 100.0
            cands.append({"id": "C3", "action": "A_RTL_AFTER_WP", "label": f"飛完 WP{wp_idx + 1} 後返航",
                          "end_pct": round(pct(pnr[1] + pnr[3]), 1), "completion_pct": round(comp, 0),
                          "param": wp_idx})
        # 立即返航
        cands.append({"id": "C4", "action": "A_RTL_NOW", "label": "立即返航",
                      "end_pct": round(pct(walk[0][3]), 1),
                      "completion_pct": round(done / total * 100.0, 0)})
        # 就地降落（回不了家時）
        land = leg_energy(veh, tm.pos, (tm.pos[0], tm.pos[1], self.home[2]), wind)["energy_wh"]
        cands.append({"id": "C5", "action": "A_LAND_NOW", "label": "就地降落",
                      "end_pct": round(pct(land), 1),
                      "completion_pct": round(done / total * 100.0, 0)})
        # 告警持續中要多 2% 才算可行，跟告警解除的遲滯一致，避免建議來回跳
        need = self.cfg.reserve_pct + (2.0 if "battery_route" in self._active else 0.0)
        for c in cands:
            c["feasible"] = c["end_pct"] >= need
        return cands

    @staticmethod
    def _rule_pick(cands):
        """規則：可行選項（不含就地降落）裡完成度最高者，同分取電量多者；
        都不可行時，返航落地還有 10% 以上就返航，否則才就地降落。"""
        ok = [c for c in cands if c["feasible"] and c["action"] != "A_LAND_NOW"]
        if ok:
            return max(ok, key=lambda c: (c.get("completion_pct", 0), c["end_pct"]))["id"]
        rtl = next((c for c in cands if c["action"] == "A_RTL_NOW"), None)
        if rtl and rtl["end_pct"] >= 10.0:
            return rtl["id"]
        return max(cands, key=lambda c: c["end_pct"])["id"]

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
                wp = tm.next_wp + i - 1
                f.active = True
                f.severity = SEV_WARNING if t_cum < 120 else SEV_NOTICE
                f.title = "航線前方可能斷訊"
                f.value = f"WP{wp + 1}（離家 {d / 1000:.2f} km）預估鏈路 {max(0, q):.0f}%，約 {t_cum / 60:.1f} 分鐘後"
                f.lead_s = t_cum
                f.evidence = [
                    {"id": "E1", "text": "目前鏈路品質／離家距離", "value": f"{tm.link_pct:.0f}%／{d_now / 1000:.2f} km"},
                    {"id": "E2", "text": "每遠 1 km 鏈路下降", "value": f"{-b * 1000:.0f}%（R²={r2:.2f}）"},
                    {"id": "E3", "text": "預估最差航點", "value": f"WP{wp + 1}，{max(0, q):.0f}%"},
                    {"id": "E4", "text": "斷訊門檻", "value": f"{self.cfg.link_min_pct:.0f}%"},
                ]
                f.candidates = [
                    {"id": "C1", "action": "A_CONTINUE_MONITOR", "label": "繼續並確認失聯保護（RTL）已開", "feasible": True},
                    {"id": "C2", "action": "A_RTL_AFTER_WP", "label": f"飛完 WP{wp} 後返航", "feasible": True, "param": wp - 1},
                ]
                f.rule_choice = "C1"
                break
        return f

    # ---------- P5 風速 ----------
    def _wind(self, tm: Telemetry) -> Finding:
        self._wind_hist.append((tm.t, tm.wind.speed_mps))
        f = Finding("wind_trend", active=False)
        pts = list(self._wind_hist)
        if len(pts) < 60:
            return f
        b, a, r2 = linfit([p[0] for p in pts], [p[1] for p in pts])
        self._wind_trend = (b, r2)
        lim = self.cfg.wind_limit_mps
        if tm.wind.speed_mps >= lim:
            tts = 0.0
        elif b > 0.002 and r2 > 0.6:
            tts = (lim - (a + b * tm.t)) / b
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
                {"id": "C1", "action": "A_CONTINUE_MONITOR", "label": "持續觀察風速", "feasible": True},
                {"id": "C2", "action": "A_RTL_NOW", "label": "立即返航", "feasible": True},
            ]
            f.rule_choice = "C1" if tts > 120 else "C2"
        return f

    # ---------- 主流程 ----------
    def update(self, tm: Telemetry) -> list[dict]:
        """吃一筆遙測，回傳這一刻的告警事件（raise / update / resolve）。"""
        self._update_calib(tm)
        avail, basis, cap = self._available_wh(tm)
        wind_f = self._wind(tm)                 # 先算風速趨勢，電量預測要用
        findings = self._battery_route(tm, avail, basis, cap)
        findings.append(self._link(tm))
        findings.append(wind_f)
        events = []
        for f in findings:
            events.extend(self._debounce(tm.t, f))
        return events

    def _debounce(self, t, f: Finding):
        """連續成立 raise_ticks 次才發、連續不成立 clear_ticks 次才解除；
        持續中只有「嚴重度升級」或「建議改變且維持 raise_ticks 次」才重新說明。"""
        k = f.key
        prev = self._active.get(k)
        s = self._streak.get(k, 0)
        s = (s + 1 if s >= 0 else 1) if f.active else (s - 1 if s <= 0 else -1)
        self._streak[k] = s
        ev = []
        if prev is None and f.active and s >= self.cfg.raise_ticks:
            self._active[k] = f
            self._announced[k] = (f.severity, f.rule_choice)
            ev.append(self._event(t, "raise", f))
        elif prev is not None and f.active:
            self._active[k] = f
            sev0, ch0 = self._announced[k]
            if f.rule_choice != ch0:
                pc = self._pending_choice.get(k)
                n = pc[1] + 1 if pc and pc[0] == f.rule_choice else 1
                self._pending_choice[k] = (f.rule_choice, n)
            else:
                self._pending_choice.pop(k, None)
                n = 0
            if f.severity < sev0 or n >= self.cfg.raise_ticks:
                self._announced[k] = (min(sev0, f.severity), f.rule_choice)
                self._pending_choice.pop(k, None)
                ev.append(self._event(t, "update", f))
        elif prev is not None and not f.active and -s >= self.cfg.clear_ticks:
            del self._active[k]
            self._announced.pop(k, None)
            ev.append(self._event(t, "resolve", prev))
        return ev

    @staticmethod
    def _event(t, kind, f: Finding):
        return {"t": t, "type": kind, "key": f.key, "severity": f.severity, "title": f.title,
                "value": f.value, "lead_s": f.lead_s, "evidence": f.evidence,
                "candidates": f.candidates, "rule_choice": f.rule_choice}

    def active(self):
        return dict(self._active)
