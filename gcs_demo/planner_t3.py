"""T3 version/apply contract and two independent preflight sorties (no executor)."""
from __future__ import annotations

import copy
import hashlib
import math
import struct

from .energy import Wind


def _canonical(value):
    # Same byte contract as JS: finite IEEE754 doubles, UTF-8 hex strings/keys.
    if value is None:
        return "z"
    if isinstance(value, bool):
        return "t" if value else "f"
    if isinstance(value, (int, float)):
        x = float(value)
        if not math.isfinite(x):
            raise ValueError("nonfinite mission version input")
        return "n" + struct.pack(">d", 0.0 if x == 0 else x).hex()
    if isinstance(value, str):
        return "s" + value.encode("utf-8").hex()
    if isinstance(value, (list, tuple)):
        return "a[" + ",".join(_canonical(x) for x in value) + "]"
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        keys = sorted(value, key=lambda k: k.encode("utf-8").hex())
        return "o{" + ",".join(_canonical(k) + ":" + _canonical(value[k]) for k in keys) + "}"
    raise ValueError("unsupported mission version input")


def mission_version(mission, vehicle, wind, state=None):
    v = vehicle.to_dict() if hasattr(vehicle, "to_dict") else vehicle
    w = {"speed_mps": wind.speed_mps, "from_deg": wind.from_deg} if isinstance(wind, Wind) else wind
    raw = _canonical({"mission": mission, "vehicle": v, "wind": w, "state": state})
    return "t3-v1:" + hashlib.sha256(raw.encode("ascii")).hexdigest()


def check_apply(result, mission, vehicle, wind, state=None):
    try:
        ok = isinstance(result, dict) and result.get("mission_version") == mission_version(mission, vehicle, wind, state)
    except (ValueError, TypeError, OverflowError, UnicodeError):
        ok = False
    return {"ok": True} if ok else {"ok": False, "reason_zh": "任務已變更，請重新規劃"}


def replan_context(mission, vehicle, wind, state, event):
    """Pure effective inputs; use both at planning and immediately before apply."""
    m, v, s = copy.deepcopy(mission), copy.copy(vehicle), copy.deepcopy(state)
    v.calib = math.floor(s.get("observed_ratio", v.calib) * 1000 + 0.5) / 1000
    if event["type"] == "wind":
        wind = Wind(event["speed_mps"], event["from_deg"])
    elif event["type"] == "no_fly":
        m.setdefault("no_fly", []).append(copy.deepcopy(event["zone"]))
    elif event["type"] == "add_target":
        m["targets"].append(copy.deepcopy(event["target"]))
        s["remaining"] = s["remaining"] + [event["target"]["id"]]
    elif event["type"] == "battery":
        s["battery_pct"] = event["battery_pct"]
    m["completed"] = s["completed"]
    return m, v, wind, s


def constraint_deltas(mission, vehicle, path, est, missing, to_xy):
    out = []
    if est["margin_pct"] < 0:
        out.append({"violated": "reserve", "short_pct": -est["margin_pct"]})
    maximum = mission.get("limits", {}).get("max_altitude_m", 120)
    for point in path:
        if point.get("alt", 0) > maximum:
            out.append({"violated": "altitude", "point_id": point["id"],
                        "over_m": point["alt"] - maximum})
    origin = (mission["home"]["lat"], mission["home"]["lon"])
    for a, b in zip(path, path[1:]):
        ax, ay = to_xy(origin, (a["lat"], a["lon"]))
        bx, by = to_xy(origin, (b["lat"], b["lon"]))
        dx, dy = bx - ax, by - ay
        for zone in mission.get("no_fly", []):
            cx, cy = to_xy(origin, (zone["lat"], zone["lon"]))
            t = max(0, min(1, ((cx - ax) * dx + (cy - ay) * dy) / (dx * dx + dy * dy))) if dx or dy else 0
            short = zone["radius_m"] - math.hypot(ax + t * dx - cx, ay + t * dy - cy)
            if short > 0:
                out.append({"violated": "no_fly", "zone_id": zone["id"],
                            "from": a["id"], "to": b["id"], "short_m": short})
    if missing:
        out.append({"violated": "required_targets", "missing_count": len(missing), "target_ids": missing})
    return out


def split_sorties(mission, vehicle, wind, sequences, speeds, evaluate, home):
    """Bounded heuristic: all contiguous cuts of supplied input/dist/energy orders.

    Each sortie starts with a separate full battery and returns home. Each subset
    has its own must-target contract; the union is checked against ALL targets.
    Failure to find a cut is not a proof of global two-sortie infeasibility.
    """
    best, seen = None, set()
    ids = [t["id"] for t in mission["targets"]]
    if len(ids) < 2:
        return None
    for seq in sequences:
        for k in range(1, len(seq)):
            groups = (seq[:k], seq[k:])
            key = tuple(tuple(t["id"] for t in g) for g in groups)
            if key in seen:
                continue
            seen.add(key)
            for speed in dict.fromkeys(speeds):
                sorties = []
                for i, group in enumerate(groups, 1):
                    sub = dict(mission, targets=group, completed=[])
                    c = evaluate("S1-" + str(i), "分兩趟第 " + str(i) + " 趟", "獨立滿電、返航", sub,
                                 vehicle, wind, [home(mission)] + group + [home(mission)], speed, 100.0)
                    sorties.append(c)
                order = [tid for s in sorties for tid in s["order"]]
                if not all(s["feasible"] for s in sorties) or sorted(order) != sorted(ids):
                    continue
                energy = round(sum(s["energy_wh"] for s in sorties), 1)
                if best is not None and energy >= best["energy_wh"]:
                    continue
                must = {t["id"] for t in mission["targets"] if t.get("priority", 1) == 1}
                best = {"id": "S1", "label": "分兩趟完成全部目標", "how": "兩個獨立返航架次，中間更換滿電電池",
                        "note": "須分別檢視兩趟；尚無自動跨架次執行器；分割搜尋非窮舉最佳化",
                        "order": order, "speed_mps": speed, "calib": vehicle.calib,
                        "dist_km": round(sum(s["dist_km"] for s in sorties), 2),
                        "time_min": round(sum(s["time_min"] for s in sorties), 1),
                        "energy_wh": round(energy, 1), "end_pct": min(s["end_pct"] for s in sorties),
                        "margin_pct": min(s["margin_pct"] for s in sorties), "feasible": True,
                        "must_rank": sum(i for i, tid in enumerate(order) if tid in must),
                        "violations": [], "missing_must": [], "constraint_deltas": [], "sorties": sorties,
                        "requires_battery_swap": True, "path": [], "legs": []}
    return best
