"""把 cg-v2 的 apply_check 包成提交層用的 recheck(S)，並加上聯合安全餘裕（提交層說明第 4 節步驟 4）。

S 是提交層一致快照：
  battery: 起飛電量 %、wind: {speed_mps, from_deg}、no_fly: [...]、
  limits: {reserve_req_pct, max_alt_m}、position: (dx_m, dy_m)（起飛點相對 home 的偏移）
判定順序（v1.2 §3）：不合格 → BLOCK；聯合最壞情況不合格 → BLOCK(JOINT_MARGIN)；
相對使用者已確認的顯示版本有差異 → REDISPLAY；其他 → WRITE。
"""
from __future__ import annotations

from .energy import Wind
from . import coverage as cv
from .commit_layer import TEST_VALUES


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
        cur = _current(vehicle, S, base)
        chk = cv.apply_check(record, **cur)
        if chk["decision"] == "BLOCK":
            return {"action": "BLOCK", "reasons": [r["code"] for r in chk["reasons"] if r["code"] != "HINT"],
                    "hint": chk.get("hint")}
        # 聯合最壞情況：電量少 ε、風速多 ε、風向兩側各偏 ε、禁航區半徑再加定位 ε
        worst_end = None
        for ddir in (-e["wind_dir"], 0.0, e["wind_dir"]):
            w = {"speed_mps": S["wind"]["speed_mps"] + e["wind_speed"],
                 "from_deg": (S["wind"]["from_deg"] + ddir) % 360}
            nf = [dict(z, radius_m=z["radius_m"] + e["position_m"]) for z in cur["no_fly"]]
            wc = dict(cur, wind=Wind(**w), takeoff_pct=S["battery"] - e["battery"], no_fly=nf)
            wchk = cv.apply_check(record, **wc)
            if wchk["evaluation"]["nfz_crossings"]:
                return {"action": "BLOCK", "reasons": ["JOINT_MARGIN_NFZ"]}
            end = wchk["evaluation"]["est_end_pct"]
            worst_end = end if worst_end is None else min(worst_end, end)
        reserve_eff = chk["evaluation"]["reserve_eff_pct"]
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
