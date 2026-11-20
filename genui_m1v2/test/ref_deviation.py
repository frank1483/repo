"""F2 DEVIATION 的 Python 參考實作（與 GenuiTools.flightlogDeviation 同一演算法，各自獨立寫）。讀 f2_cases（由 node 轉成 JSON），
輸出與 JS 相同欄位，逐位比對（toPrecision(17)）。用法：python3 test/ref_deviation.py <cases.json> <js_out.json>"""
import json, math, sys
R, MIN_SEG, MAXP, BUCKETS = 6371008.8, 0.01, 300, 150
def fin(x): return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
def valid(p): return p is not None and fin(p.get("lat")) and fin(p.get("lon")) and abs(p["lat"]) <= 90 and abs(p["lon"]) <= 180
def segd(px, py, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
    u = ((px - a[0]) * dx + (py - a[1]) * dy) / L2; u = 0 if u < 0 else (1 if u > 1 else u)
    ex, ey = a[0] + u * dx - px, a[1] + u * dy - py
    return math.sqrt(ex * ex + ey * ey)
def dev(wp, smp, t0, t1, gaps):
    gaps = gaps or []
    origin = next((w for w in wp if valid(w)), None)
    if origin is None: return {"status": "INSUFFICIENT", "reason": "no_segment"}
    cos0 = math.cos(origin["lat"] * math.pi / 180)
    xy = lambda p: (R * (p["lon"] - origin["lon"]) * math.pi / 180 * cos0, R * (p["lat"] - origin["lat"]) * math.pi / 180)
    segs, breaks, last, broken = [], 0, None, False
    for w in wp:
        if not valid(w): broken = True; continue
        if last is not None and abs(w["lon"] - last["lon"]) > 180: return {"status": "INSUFFICIENT", "reason": "antimeridian"}
        if last is not None and broken: breaks += 1
        if last is not None and not broken:
            a, b = xy(last), xy(w)
            if math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) > MIN_SEG: segs.append((a, b))
        last, broken = w, False
    if not segs: return {"status": "INSUFFICIENT", "reason": "no_segment"}
    pts = []
    for i, s in enumerate(smp):
        if s is None or not fin(s.get("t")) or not valid(s) or s["t"] < t0 or s["t"] > t1: continue
        if abs(s["lon"] - origin["lon"]) > 180: return {"status": "INSUFFICIENT", "reason": "antimeridian"}
        pts.append((s["t"], i, s))
    pts.sort(key=lambda x: (x[0], x[1]))
    part = bool(gaps) or breaks > 0
    if not pts: return {"status": "PARTIAL" if part else "ERROR", "reason": None}
    d = []; tot = 0.0; best = 0
    for k, (t, i, s) in enumerate(pts):
        x, y = xy(s); m = math.inf
        for a, b in segs:
            v = segd(x, y, a, b)
            if v < m: m = v
        d.append((t, m)); tot += m
        if m > d[best][1]: best = k
    if len(d) > MAXP:
        tA = d[0][0]; width = (d[-1][0] - tA) / BUCKETS; bk = [None] * BUCKETS
        for i, (t, v) in enumerate(d):
            bi = min(BUCKETS - 1, math.floor((t - tA) / width)) if width > 0 else 0
            if bk[bi] is None: bk[bi] = [i, i]
            if v < d[bk[bi][0]][1]: bk[bi][0] = i
            if v > d[bk[bi][1]][1]: bk[bi][1] = i
        n = sum(1 if b[0] == b[1] else 2 for b in bk if b)
    else: n = len(d)
    return {"status": "PARTIAL" if part else "OK", "max": d[best][1], "mean": tot / len(d), "n_series": n, "reason": None}
def p17(v):
    # 與 JS toPrecision(17) 相同的寫法
    if v is None: return None
    s = "%.17g" % v
    if "e" not in s and "." not in s and len(s.lstrip("-")) < 17: s = s + "." + "0" * (17 - len(s.lstrip("-")))
    elif "e" not in s and "." in s:
        digits = len(s.lstrip("-").replace(".", "").lstrip("0")) if abs(v) >= 1 else len(s.split(".")[1].lstrip("0"))
        if abs(v) >= 1 and digits < 17: s = s + "0" * (17 - digits)
    return s
cases = json.load(open(sys.argv[1])); js = {x["name"]: x for x in json.load(open(sys.argv[2]))}
diff = 0
for c in cases:
    r = dev(c["wp"], c["s"], c["t0"], c["t1"], c.get("gaps"))
    j = js[c["name"]]
    for k in ("status", "reason"):
        if (r.get(k) if k in r else None) != j.get(k): diff += 1; print("DIFF", c["name"], k, r.get(k), j.get(k))
    for k in ("max", "mean"):
        a, b = r.get(k), j.get(k)
        if a is None and b is None: continue
        if a is None or b is None or float(b) != a: diff += 1; print("DIFF", c["name"], k, repr(a), b)
    if (r.get("n_series") or None) != (int(float(j["n_series"])) if j.get("n_series") else None): diff += 1; print("DIFF", c["name"], "n_series", r.get("n_series"), j.get("n_series"))
print(f"ref_deviation: cases {len(cases)}, bitwise diffs {diff}")
sys.exit(1 if diff else 0)
