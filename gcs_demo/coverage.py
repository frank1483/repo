"""ADR-0002 覆蓋航點生成（cg-v1）、預覽驗算（pc-v1）與套用判定（ac-v1）。

依「演算法說明 v1：覆蓋航點生成與預覽驗算」（使用者 2026-11-16 23:00 台灣時間回「照建議」）。
- 不動 /api/plan、planner.py 的 insert_detours，也不碰 server.SESSION。
- 禁航區在生成階段就從掃描線上切掉；預覽與套用只驗算同一條航線，不改順序、不繞行（條文 A）。
- 第一階段：凸多邊形＋圓形禁航區；凹多邊形回 UNSUPPORTED_CONCAVE。

與說明 v1 的一處實作差異（已在回報中說明）：連接段用兩個連接點（沿外擴圓的外切方框繞過），
而不是 insert_detours 的單一偏移點。單點在掃描線穿過圓心時，弦到圓心距離只有 R/√2≈0.95r，
會穿過原始禁航區；兩點方框到圓心的距離恆為 R＝r×margin＞r。
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import os

from .energy import route_estimate
from .planner import _to_xy, _to_ll, zone_violations
from .planner_t3 import _canonical

CG_VERSION = "cg-v1"
PC_VERSION = "pc-v1"
AC_VERSION = "ac-v1"

DEFAULTS = {
    "alt_m": 50.0,
    "nfz_margin": 1.35,
    "line_threshold": 0.95,
    "total_threshold": 0.98,
    "diff_end_pct": 3.0,       # 明顯變化：|Δ預估落地電量| ≥ 3 個百分點
    "diff_coverage": 0.01,     # 明顯變化：|Δ總覆蓋率| ≥ 1 個百分點
}
MIN_PIECE_M = 1e-6
COVERAGE_HINT_ZH = "使用者可縮小巡檢範圍或調整覆蓋要求，再重新驗算。禁航區以系統採用的授權資料為準。"


def _sha(obj):
    return hashlib.sha256(_canonical(obj).encode("ascii")).hexdigest()


# ---------- 平面幾何 ----------

def _rot(p, ang):
    """把點旋轉 −ang（讓掃描方向變成 +x）。"""
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c + p[1] * s, -p[0] * s + p[1] * c)


def _unrot(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def _area(poly):
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segs_intersect(p1, p2, p3, p4):
    d1, d2 = _cross(p3, p4, p1), _cross(p3, p4, p2)
    d3, d4 = _cross(p1, p2, p3), _cross(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 * d2 < 0 and d3 * d4 < 0


def _self_intersecting(poly):
    n = len(poly)
    for i in range(n):
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue
            if _segs_intersect(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                return True
    return False


def _is_convex(poly):
    sign = 0
    n = len(poly)
    for i in range(n):
        c = _cross(poly[i], poly[(i + 1) % n], poly[(i + 2) % n])
        if abs(c) < 1e-9:
            continue
        s = 1 if c > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def _hline_span(poly, y):
    xs = []
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    if len(xs) < 2:
        return None
    return min(xs), max(xs)


def _subtract(pieces, lo, hi):
    out = []
    for a, b in pieces:
        if hi <= a or lo >= b:
            out.append((a, b))
            continue
        if lo > a:
            out.append((a, lo))
        if hi < b:
            out.append((hi, b))
    return [(a, b) for a, b in out if b - a > MIN_PIECE_M]


# ---------- 生成 ----------

def resolve_spacing(spacing_m=None, camera=None, alt_m=None):
    """依序：相機換算 → 任務配置 spacing_m → None（MISSING）。"""
    keys = ("sensor_width_mm", "focal_mm", "side_overlap")
    if camera and all(isinstance(camera.get(k), (int, float)) for k in keys) and alt_m:
        f = camera["focal_mm"]
        ov = camera["side_overlap"]
        if f > 0 and 0 <= ov < 1:
            ground_w = alt_m * camera["sensor_width_mm"] / f
            return ground_w * (1 - ov), "camera"
    if isinstance(spacing_m, (int, float)):
        return float(spacing_m), "mission"
    return None, None


def coverage_generate(area, home, spacing_m=None, camera=None, alt_m=None, angle_deg=None,
                      no_fly=None, nfz_margin=None):
    alt = DEFAULTS["alt_m"] if alt_m is None else float(alt_m)
    margin = DEFAULTS["nfz_margin"] if nfz_margin is None else float(nfz_margin)
    no_fly = list(no_fly or [])
    params = {"area": area, "home": home, "spacing_m": spacing_m, "camera": camera, "alt_m": alt,
              "angle_deg": angle_deg, "no_fly": no_fly, "nfz_margin": margin}

    missing = []
    if not area:
        missing.append("area")
    if not home:
        missing.append("home")
    spacing, spacing_src = resolve_spacing(spacing_m, camera, alt)
    if spacing is None:
        missing.append("spacing_m")
    if missing:
        return {"status": "MISSING", "missing": missing, "params": params}
    if spacing <= 0 or len(area) < 3 or margin < 1.0:
        return {"status": "INVALID", "reason": "spacing<=0、區域少於 3 點或 margin<1", "params": params}

    origin = (home["lat"], home["lon"])
    poly = [_to_xy(origin, (p["lat"], p["lon"])) for p in area]
    if abs(_area(poly)) < 1e-6 or _self_intersecting(poly):
        return {"status": "INVALID", "reason": "多邊形面積為 0 或自我交叉", "params": params}
    if not _is_convex(poly):
        return {"status": "UNSUPPORTED_CONCAVE", "params": params}

    if angle_deg is None:
        best = max(range(len(poly)), key=lambda i: math.dist(poly[i], poly[(i + 1) % len(poly)]))
        (x1, y1), (x2, y2) = poly[best], poly[(best + 1) % len(poly)]
        ang = math.atan2(y2 - y1, x2 - x1)
    else:
        ang = math.radians(angle_deg)
    rpoly = [_rot(p, ang) for p in poly]
    circles = []
    for z in no_fly:
        c = _rot(_to_xy(origin, (z["lat"], z["lon"])), ang)
        circles.append((z.get("id", "?"), c, z["radius_m"] * margin))

    ymin = min(p[1] for p in rpoly)
    ymax = max(p[1] for p in rpoly)
    lines = []
    y = ymin + spacing / 2.0
    while y < ymax - MIN_PIECE_M:
        span = _hline_span(rpoly, y)
        if span and span[1] - span[0] > MIN_PIECE_M:
            x0, x1 = span
            pieces = [(x0, x1)]
            gaps = []
            for zid, (cx, cy), R in circles:
                dy = abs(y - cy)
                if dy >= R:
                    continue
                h = math.sqrt(R * R - dy * dy)
                lo, hi = max(x0, cx - h), min(x1, cx + h)
                if hi > lo:
                    gaps.append({"from_m": lo - x0, "to_m": hi - x0, "reason": f"NFZ:{zid}"})
                    pieces = _subtract(pieces, cx - h, cx + h)
            lines.append({"y": y, "x0": x0, "x1": x1, "pieces": pieces, "gaps": gaps})
        y += spacing
    for i, ln in enumerate(lines, 1):
        ln["line_no"] = i

    # 依序串接：四種起點，取 home→首點＋末點→home 最短
    def build(bottom_up, first_ltr):
        seq = lines if bottom_up else lines[::-1]
        pts = []
        for k, ln in enumerate(seq):
            ltr = first_ltr if k % 2 == 0 else not first_ltr
            pieces = ln["pieces"] if ltr else [(b, a) for a, b in ln["pieces"][::-1]]
            for pi, (a, b) in enumerate(pieces, 1):
                if pi > 1:
                    prev_end = pts[-1]["xy"]
                    # 連接段：兩點方框，繞到外擴圓外側
                    side_y = _connector_y(ln["y"], prev_end[0], a, circles)
                    pts.append({"xy": (prev_end[0], side_y), "kind": "connector", "line_no": ln["line_no"], "piece_no": pi - 1})
                    pts.append({"xy": (a, side_y), "kind": "connector", "line_no": ln["line_no"], "piece_no": pi - 1})
                pts.append({"xy": (a, ln["y"]), "kind": "survey", "line_no": ln["line_no"], "piece_no": pi})
                pts.append({"xy": (b, ln["y"]), "kind": "survey", "line_no": ln["line_no"], "piece_no": pi})
        return pts

    hxy = _rot((0.0, 0.0), ang)
    best_pts, best_cost = None, None
    for bu, ltr in ((True, True), (True, False), (False, True), (False, False)):
        pts = build(bu, ltr)
        if not pts:
            continue
        cost = math.dist(hxy, pts[0]["xy"]) + math.dist(pts[-1]["xy"], hxy)
        if best_cost is None or cost < best_cost - 1e-9:
            best_pts, best_cost = pts, cost
    if not best_pts:
        return {"status": "INVALID", "reason": "間距過大，區域內沒有掃描線", "params": params}

    points = [{"id": "H", "lat": home["lat"], "lon": home["lon"], "alt": 0, "kind": "home"}]
    counters = {}
    for p in best_pts:
        lat, lon = _to_ll(origin, _unrot(p["xy"], ang))
        key = (p["line_no"], p["kind"])
        counters[key] = counters.get(key, 0) + 1
        tag = "S" if p["kind"] == "survey" else "C"
        points.append({"id": f"L{p['line_no']:02d}{tag}{counters[key]}", "lat": lat, "lon": lon,
                       "alt": alt, "kind": p["kind"], "line_no": p["line_no"], "piece_no": p["piece_no"]})
    points.append({"id": "H_end", "lat": home["lat"], "lon": home["lon"], "alt": 0, "kind": "home"})

    out_lines = [{"line_no": ln["line_no"], "planned_len_m": ln["x1"] - ln["x0"],
                  "kept_len_m": sum(b - a for a, b in ln["pieces"]), "gaps": ln["gaps"]} for ln in lines]
    conn_len = 0.0
    for i in range(1, len(best_pts)):
        if best_pts[i]["kind"] == "connector" or best_pts[i - 1]["kind"] == "connector":
            conn_len += math.dist(best_pts[i - 1]["xy"], best_pts[i]["xy"])
    stats = {"area_m2": abs(_area(poly)), "n_lines": len(lines),
             "survey_len_m": sum(l["kept_len_m"] for l in out_lines), "connector_len_m": conn_len,
             "spacing_m": spacing, "spacing_source": spacing_src, "angle_deg": math.degrees(ang)}
    route_id = f"{CG_VERSION}:" + _sha({"points": points})[:16]
    return {"status": "OK", "route_id": route_id, "points": points, "lines": out_lines,
            "stats": stats, "params": params, "algo_version": CG_VERSION}


def _connector_y(y, xa, xb, circles):
    """連接段要繞過的圓：取覆蓋 xa..xb 之間、且與掃描線相交的圓，往遠離圓心的一側推到 R 外。"""
    lo, hi = min(xa, xb), max(xa, xb)
    best = None
    for _, (cx, cy), R in circles:
        if abs(y - cy) < R:
            h = math.sqrt(R * R - (y - cy) ** 2)
            if cx - h <= hi + 1e-6 and cx + h >= lo - 1e-6:
                side = 1.0 if y - cy >= 0 else -1.0
                cand = cy + side * R
                if best is None or abs(cand - y) > abs(best - y):
                    best = cand
    return y if best is None else best


# ---------- 預覽驗算 ----------

def _coverage(lines, line_th, total_th):
    per = []
    planned = kept = 0.0
    for l in lines:
        ratio = l["kept_len_m"] / l["planned_len_m"] if l["planned_len_m"] > 0 else 1.0
        per.append({"line_no": l["line_no"], "ratio": ratio, "planned_len_m": l["planned_len_m"],
                    "kept_len_m": l["kept_len_m"], "missed_m": l["planned_len_m"] - l["kept_len_m"],
                    "gaps": l.get("gaps", []), "ok": ratio >= line_th - 1e-12})
        planned += l["planned_len_m"]
        kept += l["kept_len_m"]
    total = kept / planned if planned > 0 else 0.0
    return {"per_line": per, "total": total, "ok": total >= total_th - 1e-12 and all(p["ok"] for p in per)}


def _evaluate_route(points, lines, origin, vehicle, wind, takeoff_pct, reserve_req_pct, no_fly,
                    max_alt_m, line_threshold, total_threshold, speed_mps):
    reserve_eff = max(vehicle.reserve_pct, reserve_req_pct)
    v2 = dataclasses.replace(copy.deepcopy(vehicle), reserve_pct=reserve_eff)
    speed = vehicle.cruise_mps if speed_mps is None else speed_mps
    est = route_estimate(v2, points, speed, wind, start_pct=takeoff_pct)
    reasons = []
    if est["end_pct"] < reserve_eff:
        reasons.append({"code": "BATTERY_BELOW_RESERVE",
                        "detail": f"預估落地電量 {est['end_pct']:.1f}% 低於保留 {reserve_eff:.1f}%"})
    zv = zone_violations(points, no_fly, origin)
    for z in zv:
        reasons.append({"code": "NFZ_CROSSING", "detail": z})
    for p in points:
        if p.get("alt", 0) > max_alt_m:
            reasons.append({"code": "ALT_OVER_LIMIT", "detail": f"{p['id']} 高度 {p['alt']} m 超過上限 {max_alt_m} m"})
    cov = _coverage(lines, line_threshold, total_threshold)
    for pl in cov["per_line"]:
        if not pl["ok"]:
            reasons.append({"code": "LINE_COVERAGE_LOW",
                            "detail": f"L{pl['line_no']:02d} 預計完成 {pl['ratio'] * 100:.0f}%，漏掃 {pl['missed_m']:.0f} m"})
    if cov["total"] < total_threshold - 1e-12:
        reasons.append({"code": "TOTAL_COVERAGE_LOW",
                        "detail": f"總覆蓋率 {cov['total'] * 100:.1f}% 低於門檻 {total_threshold * 100:.0f}%"})
    if any(r["code"].endswith("COVERAGE_LOW") for r in reasons):
        reasons.append({"code": "HINT", "detail": COVERAGE_HINT_ZH})
    blocking = [r for r in reasons if r["code"] != "HINT"]
    return {"result": "fail" if blocking else "pass", "reasons": reasons,
            "est_end_pct": est["end_pct"], "reserve_eff_pct": reserve_eff,
            "energy_wh": est["energy_wh"], "dist_m": est["dist_m"], "time_s": est["time_s"],
            "coverage": cov, "nfz_crossings": zv}


def _inputs(vehicle, wind, takeoff_pct, reserve_req_pct, no_fly, max_alt_m, line_threshold,
            total_threshold, speed_mps):
    return {"vehicle": vehicle.to_dict(), "wind": {"speed_mps": wind.speed_mps, "from_deg": wind.from_deg},
            "takeoff_pct": takeoff_pct, "reserve_req_pct": reserve_req_pct, "no_fly": list(no_fly or []),
            "max_alt_m": max_alt_m, "line_threshold": line_threshold,
            "total_threshold": total_threshold, "speed_mps": speed_mps}


def preview_check(gen, vehicle, wind, takeoff_pct, reserve_req_pct, no_fly=None, max_alt_m=120,
                  line_threshold=None, total_threshold=None, speed_mps=None, created_at=None):
    """對 coverage_generate 的輸出做預覽驗算，回傳一筆預覽紀錄（不寫入任何狀態）。"""
    if gen.get("status") != "OK":
        raise ValueError("只能預覽 status=OK 的生成結果")
    lt = DEFAULTS["line_threshold"] if line_threshold is None else line_threshold
    tt = DEFAULTS["total_threshold"] if total_threshold is None else total_threshold
    no_fly = list(no_fly or [])
    points = copy.deepcopy(gen["points"])
    origin = (points[0]["lat"], points[0]["lon"])
    ev = _evaluate_route(points, gen["lines"], origin, vehicle, wind, takeoff_pct, reserve_req_pct,
                         no_fly, max_alt_m, lt, tt, speed_mps)
    inputs = _inputs(vehicle, wind, takeoff_pct, reserve_req_pct, no_fly, max_alt_m, lt, tt, speed_mps)
    algo = {"coverage_generate": gen.get("algo_version", CG_VERSION), "preview_check": PC_VERSION}
    pv = f"pv-v1:" + _sha({"route": points, "lines": gen["lines"], "inputs": inputs, "algo_versions": algo})
    return {"artifact_id": "rp-" + pv.split(":")[1][:16], "kind": "route_preview",
            "route_id": gen["route_id"], "route": points, "lines": copy.deepcopy(gen["lines"]),
            "inputs": inputs, "algo_versions": algo, "preview_version": pv,
            "created_at": created_at, **ev}


def recompute_version(record):
    """AC-9：由紀錄本身重算 preview_version。"""
    return "pv-v1:" + _sha({"route": record["route"], "lines": record["lines"],
                            "inputs": record["inputs"], "algo_versions": record["algo_versions"]})


class PreviewStore:
    """只追加的預覽紀錄（JSON Lines）。不碰 server.SESSION。"""

    def __init__(self, path):
        self.path = path

    def append(self, record):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record["artifact_id"]

    def get(self, artifact_id):
        found = None
        if not os.path.exists(self.path):
            return None
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("artifact_id") == artifact_id:
                    found = r
        return found


# ---------- 套用判定（條文 A、B） ----------

def apply_check(record, vehicle, wind, takeoff_pct, reserve_req_pct, no_fly=None, max_alt_m=120,
                line_threshold=None, total_threshold=None, speed_mps=None):
    """用當下精確值重驗算紀錄裡的原航線。回傳 BLOCK／CONFIRM_WITH_DIFF／CONFIRM。"""
    rin = record["inputs"]
    lt = rin["line_threshold"] if line_threshold is None else line_threshold
    tt = rin["total_threshold"] if total_threshold is None else total_threshold
    no_fly = list(no_fly or [])
    points = copy.deepcopy(record["route"])
    origin = (points[0]["lat"], points[0]["lon"])
    ev = _evaluate_route(points, record["lines"], origin, vehicle, wind, takeoff_pct, reserve_req_pct,
                         no_fly, max_alt_m, lt, tt, speed_mps)
    now = _inputs(vehicle, wind, takeoff_pct, reserve_req_pct, no_fly, max_alt_m, lt, tt, speed_mps)
    diffs = []
    for k in ("reserve_req_pct", "max_alt_m", "line_threshold", "total_threshold"):
        if now[k] != rin[k]:
            diffs.append({"field": k, "before": rin[k], "after": now[k], "kind": "limit"})
    d_end = ev["est_end_pct"] - record["est_end_pct"]
    if abs(d_end) >= DEFAULTS["diff_end_pct"] - 1e-12:
        diffs.append({"field": "est_end_pct", "before": record["est_end_pct"], "after": ev["est_end_pct"], "kind": "estimate"})
    d_cov = ev["coverage"]["total"] - record["coverage"]["total"]
    if abs(d_cov) >= DEFAULTS["diff_coverage"] - 1e-12:
        diffs.append({"field": "coverage_total", "before": record["coverage"]["total"],
                      "after": ev["coverage"]["total"], "kind": "estimate"})
    if ev["result"] == "fail":
        decision = "BLOCK"
        hint = "NEW_PREVIEW" if ev["nfz_crossings"] else None
    else:
        decision = "CONFIRM_WITH_DIFF" if diffs else "CONFIRM"
        hint = None
    return {"decision": decision, "artifact_id": record["artifact_id"], "route_id": record["route_id"],
            "reasons": ev["reasons"], "diffs": diffs, "hint": hint, "algo_version": AC_VERSION,
            "evaluation": ev, "inputs_now": now}


def confirm_and_write(record, writer, **current):
    """條文 B：使用者按下確認後、寫入前，再用當下值檢查一次；BLOCK 就不呼叫 writer。"""
    chk = apply_check(record, **current)
    if chk["decision"] == "BLOCK":
        return {"written": False, "check": chk}
    writer(copy.deepcopy(record["route"]))
    return {"written": True, "check": chk}
