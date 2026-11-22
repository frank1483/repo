"""把 cg-v2 的 apply_check 包成提交層用的 recheck(S)，並加上聯合安全餘裕（提交層說明第 4 節步驟 4）。

S 是提交層一致快照：
  battery: 起飛電量 %、wind: {speed_mps, from_deg}、no_fly: [...]、
  limits: {reserve_req_pct, max_alt_m}、position: (dx_m, dy_m)（起飛點相對 home 的偏移）
判定順序（v1.2 §3）：不合格 → BLOCK；聯合最壞情況不合格 → BLOCK(JOINT_MARGIN)；
相對使用者已確認的顯示版本有差異 → REDISPLAY；其他 → WRITE。
"""
from __future__ import annotations

import dataclasses
import math

from .energy import Vehicle, Wind, bearing_rad, leg_estimate

_VEH_FIELDS = {"vehicle_id", "mass_kg", "battery_wh", "usable_frac", "p_hover_w", "cda_m2", "eta", "cruise_mps",
               "max_mps", "reserve_pct", "calib"}
from . import coverage as cv
from .commit_layer import TEST_VALUES


def _finite(*xs):
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in xs)


def domain_problem(vehicle, S, base):
    """0437 #6：上界的適用域。不符合就回原因字串，呼叫端一律 BLOCK/JOINT_MARGIN_UNVERIFIED。"""
    if getattr(vehicle, "airframe_profile", None) is not None or vehicle.type != "multirotor":
        return "airframe_not_legacy_multirotor"
    v = vehicle
    if not _finite(v.battery_wh, v.usable_frac, v.p_hover_w, v.cda_m2, v.eta, v.cruise_mps, v.max_mps, v.calib,
                   v.mass_kg, v.reserve_pct):
        return "vehicle_nonfinite"
    if not (v.battery_wh > 0 and 0 < v.usable_frac <= 1 and v.p_hover_w > 0 and v.cda_m2 >= 0 and v.eta > 0
            and v.calib > 0 and 0 < v.cruise_mps <= v.max_mps):
        return "vehicle_out_of_range"
    g = base.get("speed_mps")
    if g is not None and not (_finite(g) and 0 < g <= v.max_mps):
        return "speed_out_of_range"
    w = S.get("wind") or {}
    if not _finite(S.get("battery"), w.get("speed_mps"), w.get("from_deg")):
        return "snapshot_nonfinite"
    if not (0 <= S["battery"] <= 100 and 0 <= w["speed_mps"] <= v.max_mps):
        return "snapshot_out_of_range"
    pos = S.get("position")
    if not isinstance(pos, (list, tuple)) or len(pos) != 2 or not _finite(*pos):
        return "position_missing_or_nonfinite"          # 0438 #6：缺定位不以 (0,0) 放行
    if not v.battery_wh * v.usable_frac > 0:
        return "capacity_not_positive"
    return None


def headwind_bound_end_pct(points, vehicle, wind_speed_max, takeoff_pct, reserve_eff, speed_mps=None,
                           hover_s_per_wp=5.0):
    """G0-3（補件）：方向無關的保守上界。多旋翼舊版能耗模型中，地速固定、時間＝距離／地速與風無關，
    功率隨空速單調遞增；空速 |g−w| ≤ |g|＋|w|（三角不等式），等號在正逆風時成立。
    所以每一段都用「風速上限的正逆風」計算，得到的耗電對任何風向、任何不超過上限的風速都是上界。
    只適用於 legacy 多旋翼（airframe_profile 為 None）；其他機型回 None（呼叫端要擋下）。"""
    if vehicle.type != "multirotor" or vehicle.airframe_profile is not None:
        return None
    v2 = dataclasses.replace(vehicle, reserve_pct=reserve_eff)
    g = vehicle.cruise_mps if speed_mps is None else speed_mps
    cap = v2.battery_wh * v2.usable_frac
    pct = takeoff_pct
    for a, b in zip(points, points[1:]):
        pa, pb = (a["lat"], a["lon"]), (b["lat"], b["lon"])
        brg = math.degrees(bearing_rad(pa, pb)) % 360
        w = Wind(speed_mps=wind_speed_max, from_deg=brg)        # 風從前方來＝正逆風
        est = leg_estimate(v2, pa, pb, a.get("alt", 0), b.get("alt", 0), g, w)
        if b.get("kind") == "target":
            est["energy_wh"] += v2.p_hover_w * hover_s_per_wp / 3600.0 * v2.calib
        pct -= est["energy_wh"] / cap * 100.0
    return pct


def _current(vehicle, S, base):
    lim = S.get("limits") or {}
    return dict(vehicle=vehicle, wind=Wind(**S["wind"]), takeoff_pct=S["battery"],
                reserve_req_pct=base["reserve_req_pct"],   # 本次任務要求的保留值（使用者已確認），不取任務預設
                no_fly=list(S.get("no_fly") or []), max_alt_m=lim.get("max_alt_m", base["max_alt_m"]),
                line_threshold=base.get("line_threshold"), total_threshold=base.get("total_threshold"),
                speed_mps=base.get("speed_mps"))


def make_route_recheck(record, vehicle, base, shown=None, eps=None, margin_pct=None):
    e = dict(TEST_VALUES["eps"], **(eps or {}))
    margin = TEST_VALUES["joint_margin_battery_pct"] if margin_pct is None else margin_pct

    def recheck(S):
        veh, sv = vehicle, S.get("vehicle")
        if isinstance(sv, dict) and _VEH_FIELDS <= set(sv):   # 0438 #6：快照帶完整機型 → 以快照為準
            try:
                veh = Vehicle(**sv)
            except TypeError:
                return {"action": "BLOCK", "reasons": ["JOINT_MARGIN_UNVERIFIED"], "domain": "vehicle_unparsable"}
        elif isinstance(sv, dict):                        # 只帶身分 → 必須與重驗綁定的機型是同一台
            if sv.get("vehicle_id", sv.get("id")) != vehicle.vehicle_id:
                return {"action": "BLOCK", "reasons": ["JOINT_MARGIN_UNVERIFIED"], "domain": "vehicle_mismatch"}
        elif "vehicle" in S:                              # 快照有這個來源卻沒有值 → 不放行
            return {"action": "BLOCK", "reasons": ["JOINT_MARGIN_UNVERIFIED"], "domain": "vehicle_missing"}
        # 呼叫端沒有提供機型來源（直接呼叫 helper）→ 沿用綁定的機型
        bad = domain_problem(veh, S, base)                # 0437 #6：適用域在任何估算之前判定
        if bad:
            return {"action": "BLOCK", "reasons": ["JOINT_MARGIN_UNVERIFIED"], "domain": bad}
        cur = _current(veh, S, base)
        chk = cv.apply_check(record, **cur)
        if chk["decision"] == "BLOCK":
            return {"action": "BLOCK", "reasons": [r["code"] for r in chk["reasons"] if r["code"] != "HINT"],
                    "hint": chk.get("hint")}
        # 聯合最壞情況（G0-3 補件）：
        # - 禁航區：所有點的位移 ≤ 定位 ε，所以把禁航區半徑加 ε 是幾何上界（與風無關，只算一次）；
        # - 電量：起飛電量取 −ε；風取「風速＋ε 的逐段正逆風」，對整段風向區間都是上界（不再只取三個方向樣本）。
        nf = [dict(z, radius_m=z["radius_m"] + e["position_m"]) for z in cur["no_fly"]]
        wchk = cv.apply_check(record, **dict(cur, no_fly=nf))
        if wchk["evaluation"]["nfz_crossings"]:
            return {"action": "BLOCK", "reasons": ["JOINT_MARGIN_NFZ"]}
        reserve_eff = chk["evaluation"]["reserve_eff_pct"]
        worst_end = headwind_bound_end_pct(record["route"], veh, S["wind"]["speed_mps"] + e["wind_speed"],
                                           S["battery"] - e["battery"], reserve_eff, base.get("speed_mps"))
        if worst_end is None or not math.isfinite(worst_end):   # 0438 #6：衍生結果也要有限
            return {"action": "BLOCK", "reasons": ["JOINT_MARGIN_UNVERIFIED"], "domain": "bound_not_finite"}
        if worst_end < reserve_eff + margin:
            return {"action": "BLOCK", "reasons": ["JOINT_MARGIN_BATTERY"], "worst_end_pct": worst_end}
        if shown is None:
            diffs = chk["diffs"]
        else:
            sev = shown["evaluation"]
            diffs = cv._diffs(shown["inputs_now"], sev["est_end_pct"], sev["coverage"]["total"],
                              chk["inputs_now"], chk["evaluation"])
        if diffs:
            return {"action": "REDISPLAY", "reasons": ["DIFF"], "diffs": diffs, "check": chk}
        return {"action": "WRITE", "reasons": [], "check": chk}

    return recheck
