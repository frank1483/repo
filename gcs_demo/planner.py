"""任務規劃：演算法產生候選航線、估能耗、檢查限制；模型（可有可無）在候選內挑選。

重規劃沿用 RQ2 的兩種策略：
  LOCAL：保留剩餘順序，只做局部修補（繞禁航區、刪尾端選配目標）
  FULL ：剩餘目標整個重新排序最佳化
再加上「立即返航」作為保底候選，交給 H-a（演算法產生候選、模型選擇）。
"""
from __future__ import annotations

import copy
import math

from .energy import Vehicle, Wind, route_estimate, haversine_m, best_speed
from . import llm as llm_mod


# ---------- 幾何：禁航區（圓）與繞行 ----------

def _to_xy(origin, p):
    lat0 = math.radians(origin[0])
    x = math.radians(p[1] - origin[1]) * 6371000.0 * math.cos(lat0)
    y = math.radians(p[0] - origin[0]) * 6371000.0
    return x, y


def _to_ll(origin, xy):
    lat0 = math.radians(origin[0])
    lat = origin[0] + math.degrees(xy[1] / 6371000.0)
    lon = origin[1] + math.degrees(xy[0] / (6371000.0 * math.cos(lat0)))
    return lat, lon


def _seg_circle_hit(a, b, c, r):
    """線段 ab（xy）是否穿過圓心 c 半徑 r；回傳最近點參數 t 或 None。"""
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / l2))
    px, py = ax + t * dx, ay + t * dy
    return t if math.hypot(px - cx, py - cy) < r else None


def insert_detours(points, zones, origin, margin=1.35):
    """在穿越禁航區的航段中間插入繞行點（往離圓心較遠的一側偏移）。"""
    out = [points[0]]
    n = 0
    for b in points[1:]:
        a = out[-1]
        for z in zones:
            A, B = _to_xy(origin, (a["lat"], a["lon"])), _to_xy(origin, (b["lat"], b["lon"]))
            C = _to_xy(origin, (z["lat"], z["lon"]))
            if _seg_circle_hit(A, B, C, z["radius_m"]) is None:
                continue
            dx, dy = B[0] - A[0], B[1] - A[1]
            L = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / L, dx / L
            mx, my = (A[0] + B[0]) / 2, (A[1] + B[1]) / 2
            side = 1.0 if (mx - C[0]) * nx + (my - C[1]) * ny >= 0 else -1.0
            # 投影到圓心再往外推
            t = ((C[0] - A[0]) * dx + (C[1] - A[1]) * dy) / (L * L)
            px, py = A[0] + t * dx, A[1] + t * dy
            r = z["radius_m"] * margin
            w = _to_ll(origin, (C[0] + side * nx * r + (px - C[0]) * 0, C[1] + side * ny * r))
            n += 1
            out.append({"id": f"繞{z['id']}-{n}", "lat": w[0], "lon": w[1],
                        "alt": max(a.get("alt", 0), b.get("alt", 0)), "kind": "detour"})
            break
        out.append(b)
    return out


def zone_violations(points, zones, origin):
    bad = []
    for i in range(len(points) - 1):
        A = _to_xy(origin, (points[i]["lat"], points[i]["lon"]))
        B = _to_xy(origin, (points[i + 1]["lat"], points[i + 1]["lon"]))
        for z in zones:
            if _seg_circle_hit(A, B, _to_xy(origin, (z["lat"], z["lon"])), z["radius_m"]) is not None:
                bad.append(f"{points[i]['id']}→{points[i+1]['id']} 穿越 {z['id']}")
    return bad


# ---------- 排序 ----------

def _cost_fn(vehicle, wind, speed, mode):
    def cost(a, b):
        if mode == "dist":
            return haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"]))
        e = route_estimate(vehicle, [a, b], speed, wind)
        return e["energy_wh"]
    return cost


def order_targets(start, targets, end, cost):
    """最近鄰居 + 2-opt。start、end 固定。"""
    remaining = list(targets)
    seq = []
    cur = start
    while remaining:
        nxt = min(remaining, key=lambda t: cost(cur, t))
        seq.append(nxt)
        remaining.remove(nxt)
        cur = nxt

    def total(s):
        path = [start] + s + [end]
        return sum(cost(path[i], path[i + 1]) for i in range(len(path) - 1))

    improved = True
    best = total(seq)
    while improved and len(seq) > 2:
        improved = False
        for i in range(len(seq) - 1):
            for j in range(i + 1, len(seq)):
                cand = seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]
                c = total(cand)
                if c < best - 1e-9:
                    seq, best, improved = cand, c, True
    return seq


# ---------- 候選與評估 ----------

def _evaluate(cid, label, how, mission, vehicle, wind, path, speed, start_pct, note=""):
    origin = (mission["home"]["lat"], mission["home"]["lon"])
    zones = mission.get("no_fly", [])
    path = insert_detours(path, zones, origin)
    est = route_estimate(vehicle, path, speed, wind, start_pct)
    viol = zone_violations(path, zones, origin)
    max_alt = mission.get("limits", {}).get("max_altitude_m", 120)
    viol += [f"{p['id']} 高度 {p['alt']} m 超過上限 {max_alt} m" for p in path if p.get("alt", 0) > max_alt]
    tids = [p["id"] for p in path if p.get("kind") == "target"]
    must = [t["id"] for t in mission["targets"] if t.get("priority", 1) == 1]
    done = set(mission.get("completed", []))
    missing_must = [m for m in must if m not in tids and m not in done]
    feasible = est["feasible"] and not viol and not missing_must
    must_rank = sum(i for i, t in enumerate(tids) if t in must)
    return {
        "id": cid, "label": label, "how": how, "note": note,
        "order": tids, "speed_mps": speed, "calib": vehicle.calib,
        "dist_km": round(est["dist_m"] / 1000, 2), "time_min": round(est["time_s"] / 60, 1),
        "energy_wh": round(est["energy_wh"], 1), "end_pct": round(est["end_pct"], 1),
        "margin_pct": round(est["margin_pct"], 1), "feasible": feasible,
        "violations": viol, "missing_must": missing_must, "must_rank": must_rank,
        "path": [{k: p[k] for k in ("id", "lat", "lon", "alt", "kind", "priority") if k in p} for p in path],
        "legs": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in leg.items()}
                 for leg in est["legs"]],
    }


def _home(mission, alt=None):
    h = dict(mission["home"])
    h.setdefault("id", "H")
    h["alt"] = 0 if alt is None else alt
    h["kind"] = "home"
    return h


def _targets(mission, ids=None):
    out = []
    for t in mission["targets"]:
        if ids is not None and t["id"] not in ids:
            continue
        p = dict(t)
        p["kind"] = "target"
        out.append(p)
    return out


def rule_choice(cands):
    feas = [c for c in cands if c["feasible"]]
    if not feas:
        return ""
    # 先比涵蓋目標數（多者優先），再比能耗
    best = min(feas, key=lambda c: (-len(c["order"]), c["energy_wh"]))
    # 能耗差 3% 以內視為同等，改選「必要目標較早完成」者：中途出狀況時損失較小
    near = [c for c in feas if len(c["order"]) == len(best["order"])
            and c["energy_wh"] <= best["energy_wh"] * 1.03]
    return min(near, key=lambda c: (c.get("must_rank", 0), c["energy_wh"]))["id"]


def evidence_for(cands, vehicle, wind, extra=None):
    ev = [{"id": "E1", "text": f"風速 {wind.speed_mps} m/s，風從 {wind.from_deg:.0f}° 吹來"},
          {"id": "E2", "text": f"電池 {vehicle.battery_wh} Wh，可用 {vehicle.usable_frac*100:.0f}%，"
                               f"落地保留 {vehicle.reserve_pct}%，耗電修正係數 {vehicle.calib:.2f}"}]
    for i, c in enumerate(cands, start=3):
        ev.append({"id": f"E{i}", "text": f"{c['id']} {c['label']}：落地剩 {c['end_pct']}%，"
                                          f"{'可行' if c['feasible'] else '不可行'}"
                                          + (f"（{'；'.join(c['violations'] + c['missing_must'])}）"
                                             if not c['feasible'] and (c['violations'] or c['missing_must']) else "")})
    for e in extra or []:
        ev.append({"id": f"E{len(ev)+1}", "text": e})
    return ev


def _brief(c):
    return {k: c[k] for k in ("id", "label", "order", "speed_mps", "dist_km", "time_min",
                              "energy_wh", "end_pct", "margin_pct", "feasible")}


def plan_mission(mission: dict, vehicle: Vehicle, wind: Wind, backend=None) -> dict:
    alt_cruise = mission.get("cruise_alt_m", 50)
    home_g = _home(mission)
    tg = _targets(mission)
    for t in tg:
        t.setdefault("alt", alt_cruise)
    v0 = mission.get("speed_mps", vehicle.cruise_mps)
    end = _home(mission)
    cands = []
    cands.append(_evaluate("C1", "照輸入順序", "使用者給的順序", mission, vehicle, wind,
                           [home_g] + tg + [end], v0, 100.0))
    s_dist = order_targets(home_g, tg, end, _cost_fn(vehicle, wind, v0, "dist"))
    cands.append(_evaluate("C2", "最短距離", "最近鄰居＋2-opt（距離）", mission, vehicle, wind,
                           [home_g] + s_dist + [end], v0, 100.0))
    s_en = order_targets(home_g, tg, end, _cost_fn(vehicle, wind, v0, "energy"))
    cands.append(_evaluate("C3", "最省電順序", "最近鄰居＋2-opt（含風的能耗）", mission, vehicle, wind,
                           [home_g] + s_en + [end], v0, 100.0))
    bs = best_speed(vehicle, wind, heading_deg=(wind.from_deg) % 360)["speed_mps"]
    if abs(bs - v0) >= 0.5:
        cands.append(_evaluate("C4", f"最省電順序＋改速 {bs} m/s", "能耗最低地速", mission, vehicle,
                               wind, [home_g] + s_en + [end], bs, 100.0))
    must_ids = [t["id"] for t in tg if t.get("priority", 1) == 1]
    if len(must_ids) < len(tg):
        tm = [t for t in tg if t["id"] in must_ids]
        s_m = order_targets(home_g, tm, end, _cost_fn(vehicle, wind, v0, "energy"))
        cands.append(_evaluate("C5", "只做必要目標", "刪除選配目標後重排", mission, vehicle, wind,
                               [home_g] + s_m + [end], v0, 100.0))
    rc = rule_choice(cands)
    ev = evidence_for(cands, vehicle, wind)
    backend = backend or llm_mod.get_backend()
    if rc:
        pick = llm_mod.pick_candidate(backend, "出發前任務規劃：選一條航線。必要目標都要做到，落地電量要高於保留值。",
                                      [_brief(c) for c in cands], ev, rc)
    else:
        pick = {"choice_id": "", "source": "rule", "decision": "HOLD",
                "reason_zh": "所有候選都不可行（電量或限制不符），建議換電池、分兩趟或減少目標。",
                "evidence_ids": [], "llm": None}
    return {"kind": "plan", "candidates": cands, "rule_choice": rc, "pick": pick, "evidence": ev,
            "vehicle": vehicle.to_dict(), "wind": {"speed_mps": wind.speed_mps, "from_deg": wind.from_deg}}


def replan(mission: dict, vehicle: Vehicle, wind: Wind, state: dict, event: dict, backend=None) -> dict:
    """state：{"lat","lon","alt","battery_pct","completed":[ids],"remaining":[ids]}
    event：{"type": "wind"|"battery"|"no_fly"|"add_target", ...}
    """
    m = copy.deepcopy(mission)
    note = event.get("text_zh", "")
    # 線上學習：用目前為止「實際/預估」耗電比修正剩餘航線的估算
    vehicle = copy.copy(vehicle)
    ratio = state.get("observed_ratio", vehicle.calib)
    vehicle.calib = round(ratio, 3)  # observed_ratio = 實際 / 未修正物理模型
    if event["type"] == "wind":
        wind = Wind(event["speed_mps"], event["from_deg"])
    elif event["type"] == "no_fly":
        m.setdefault("no_fly", []).append(event["zone"])
    elif event["type"] == "add_target":
        m["targets"].append(event["target"])
        state = dict(state, remaining=state["remaining"] + [event["target"]["id"]])
    elif event["type"] == "battery":
        state = dict(state, battery_pct=event["battery_pct"])
    m["completed"] = state["completed"]
    cur = {"id": "現在位置", "lat": state["lat"], "lon": state["lon"],
           "alt": state.get("alt", m.get("cruise_alt_m", 50)), "kind": "current"}
    end = _home(m)
    rem = [t for t in _targets(m) if t["id"] in state["remaining"]]
    order = {tid: i for i, tid in enumerate(state["remaining"])}
    rem.sort(key=lambda t: order.get(t["id"], 99))
    for t in rem:
        t.setdefault("alt", m.get("cruise_alt_m", 50))
    v0 = m.get("speed_mps", vehicle.cruise_mps)
    pct = state["battery_pct"]
    cands = []
    local = _evaluate("L1", "LOCAL 局部修補", "保留剩餘順序，只繞禁航區", m, vehicle, wind,
                      [cur] + rem + [end], v0, pct)
    cands.append(local)
    if not local["feasible"]:
        # 局部修補：從尾端刪選配目標直到可行
        trimmed = list(rem)
        while trimmed and any(t.get("priority", 1) == 2 for t in trimmed):
            idx = max(i for i, t in enumerate(trimmed) if t.get("priority", 1) == 2)
            trimmed.pop(idx)
            c = _evaluate("L2", "LOCAL 刪選配目標", "保留順序，刪掉尾端選配目標", m, vehicle, wind,
                          [cur] + trimmed + [end], v0, pct)
            if c["feasible"]:
                break
        if trimmed != rem:
            cands.append(c)
        must_only = [t for t in rem if t.get("priority", 1) == 1]
        if must_only and len(must_only) < len(rem) and [t["id"] for t in must_only] != [t["id"] for t in trimmed]:
            cands.append(_evaluate("L3", "LOCAL 只留必要目標", "保留順序，刪掉所有選配目標", m, vehicle,
                                   wind, [cur] + must_only + [end], v0, pct))
    s_full = order_targets(cur, rem, end, _cost_fn(vehicle, wind, v0, "energy"))
    cands.append(_evaluate("F1", "FULL 全部重排", "剩餘目標以能耗重新排序", m, vehicle, wind,
                           [cur] + s_full + [end], v0, pct))
    bs = best_speed(vehicle, wind, heading_deg=wind.from_deg % 360)["speed_mps"]
    if abs(bs - v0) >= 0.5:
        cands.append(_evaluate("F2", f"FULL 重排＋改速 {bs} m/s", "重排並改用最省電速度", m, vehicle,
                               wind, [cur] + s_full + [end], bs, pct))
    if not any(c["feasible"] for c in cands) and len(rem) > 1:
        # 部分完成：在 LOCAL 與 FULL 兩種順序中，找能安全做完的最長前綴再返航
        best = None
        for label, seq in (("LOCAL", rem), ("FULL", s_full)):
            for k in range(len(seq) - 1, 0, -1):
                c = _evaluate("P1", f"{label} 做 {k} 個後返航", f"依 {label} 順序完成前 {k} 個再回家",
                              m, vehicle, wind, [cur] + seq[:k] + [end], v0, pct)
                c["feasible"] = c["end_pct"] >= vehicle.reserve_pct and not c["violations"]
                c["partial"] = True
                if c["feasible"]:
                    if best is None or (len(c["order"]), -c["energy_wh"]) > (len(best["order"]), -best["energy_wh"]):
                        best = c
                    break
        if best:
            cands.append(best)
    rtl = _evaluate("R1", "立即返航", "放棄剩餘目標直接回家", m, vehicle, wind, [cur, end], v0, pct)
    rtl["feasible"] = rtl["end_pct"] >= vehicle.reserve_pct and not rtl["violations"]
    cands.append(rtl)
    rc = rule_choice([c for c in cands if c["id"] != "R1"]) or ("R1" if rtl["end_pct"] > 0 else "")
    ev = evidence_for(cands, vehicle, wind, extra=[f"觸發事件：{note}", f"目前電量 {pct}%",
                                                     f"起飛後實際耗電是預估的 {ratio*100:.0f}%，剩餘航線已用此比例修正"])
    backend = backend or llm_mod.get_backend()
    pick = llm_mod.pick_candidate(
        backend, "飛行中重規劃：事件發生後選一條剩餘航線。必要目標盡量完成，但落地電量必須高於保留值；"
                 "都不行就選立即返航。", [_brief(c) for c in cands], ev, rc)
    return {"kind": "replan", "event": event, "state": state, "candidates": cands, "rule_choice": rc,
            "pick": pick, "evidence": ev, "vehicle": vehicle.to_dict(),
            "wind": {"speed_mps": wind.speed_mps, "from_deg": wind.from_deg}}
