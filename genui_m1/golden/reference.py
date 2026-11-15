"""G4 對照版：依契約附件（v1 §C、v3 第一部分 §C）與 M1 演算法說明 v2 §3 獨立實作的 Python 版工具計算。

不匯入、不翻譯 JS 版；只吃 vectors.json 的輸入，輸出和 run_js.js 相同形狀的精簡結果。
執行：python3 genui_m1/golden/reference.py > py.json
"""
import json, math, os, re, sys

STALE_S, FUTURE_S = 2.0, 1.0
W, N_MIN, COV_MIN, GAP_MAX, EPS, R2_MIN, DIS_MAX, ETA_MAX = 60.0, 10, 0.8, 10.0, 0.05, 0.5, 0.2, 600.0
K1, B, TOP_K, MAX_PTS = 1.2, 0.75, 5, 300


def fin(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def energy(samples, o):
    d = dict(slope_pct_per_min=None, r2=None, n_valid=0, n_dropped=0, coverage_ratio=None, direction=None, eta_min=None,
             disorder_ratio=None, reserve_invalid=False, reserve_assumed=bool(o.get("reserveAssumed")), reason="")

    def ret(status, covered=None):
        return dict(status=status, detail=d, covered=covered)

    if o.get("vehicleType") and o["vehicleType"] != "multirotor":
        d["reason"] = "vehicle_type"; return ret("UNSUPPORTED")
    if samples is None:
        d["reason"] = "no_source"; return ret("UNAVAILABLE")
    now = o.get("now")
    kept = []
    for i, s in enumerate(samples):
        t, soc = (s or {}).get("t"), (s or {}).get("soc")
        if not fin(t) or (fin(now) and t > now + FUTURE_S) or not fin(soc) or soc < 0 or soc > 100:
            d["n_dropped"] += 1
        else:
            kept.append((t, i, soc))
    if not kept:
        d["reason"] = "no_valid_samples"; return ret("INSUFFICIENT")
    seen_max, dis = -math.inf, 0
    for t, _, _ in kept:
        if t < seen_max: dis += 1
        else: seen_max = t
    d["disorder_ratio"] = dis / len(kept)
    if d["disorder_ratio"] > DIS_MAX:
        d["reason"] = "disorder"; return ret("INSUFFICIENT")
    latest = {}
    for t, i, soc in sorted(kept):          # 同一時間戳：到達序號大的蓋掉小的
        latest[t] = soc
    ts = sorted(latest)
    t_end = ts[-1]
    win = [(t, latest[t]) for t in ts if t >= t_end - W]
    d["n_valid"] = len(win)
    t0 = win[0][0]
    d["coverage_ratio"] = (t_end - t0) / W
    cov = [t0, t_end]
    if o.get("checkStale") and fin(now) and now - t_end > STALE_S:
        d["reason"] = "stale"; return ret("STALE", cov)
    gap = max([b[0] - a[0] for a, b in zip(win, win[1:])] or [0])
    if len(win) < N_MIN: d["reason"] = "n_valid"; return ret("INSUFFICIENT", cov)
    if d["coverage_ratio"] < COV_MIN: d["reason"] = "coverage"; return ret("INSUFFICIENT", cov)
    if gap > GAP_MAX: d["reason"] = "gap"; return ret("INSUFFICIENT", cov)
    n = len(win)
    xs, ys = [t - t0 for t, _ in win], [s for _, s in win]
    xb, yb = sum(xs) / n, sum(ys) / n
    sxx = sum((x - xb) ** 2 for x in xs); syy = sum((y - yb) ** 2 for y in ys)
    sxy = sum((x - xb) * (y - yb) for x, y in zip(xs, ys))
    if sxx == 0: d["reason"] = "zero_time_variance"; return ret("INSUFFICIENT", cov)
    if syy == 0:
        d["slope_pct_per_min"], d["direction"] = 0, "持平"; return ret("OK", cov)
    slope, r2 = sxy / sxx * 60, sxy * sxy / (sxx * syy)
    d["slope_pct_per_min"], d["r2"] = slope, r2
    if r2 < R2_MIN: d["reason"] = "r2"; return ret("INSUFFICIENT", cov)
    d["direction"] = "下降" if slope < -EPS else ("上升" if slope > EPS else "持平")
    res = o.get("reservePct")
    if not fin(res) or res < 0 or res >= 100:
        d["reserve_invalid"] = True
    elif d["direction"] == "下降" and ys[-1] > res:
        eta = (ys[-1] - res) / abs(slope)
        if eta <= ETA_MAX: d["eta_min"] = eta
    return ret("OK", cov)


def telemetry(c):
    if c["samples"] is None: return dict(status="UNAVAILABLE", facts=[])
    ok = [(s["t"], k, s["value"]) for k, s in enumerate(c["samples"]) if s and fin(s.get("t")) and fin(s.get("value")) and not (fin(c["now"]) and s["t"] > c["now"] + FUTURE_S)]
    if not ok: return dict(status="UNAVAILABLE", facts=[])
    t, _, v = max(ok)                        # 時間最大；同時間取後到的
    return dict(status="STALE" if c["now"] - t > STALE_S else "OK", facts=[["F1", "value", c["field"], v, t]])


def flightlog(c):
    if c["samples"] is None: return dict(status="UNAVAILABLE", facts=[], points=[])
    pts = sorted([(s["t"], k, s["value"]) for k, s in enumerate(c["samples"]) if fin(s.get("t")) and fin(s.get("value")) and c["t0"] <= s["t"] <= c["t1"]])
    pts = [(t, v) for t, _, v in pts]
    if not pts: return dict(status="PARTIAL" if c["gaps"] else "EMPTY_COMPLETE", facts=[], points=[])
    vals = [v for _, v in pts]
    total = 0.0
    for v in vals: total += v
    f = c["field"]
    facts = [["F2", "value", f + ".min", min(vals), None], ["F3", "value", f + ".max", max(vals), None], ["F4", "value", f + ".mean", total / len(vals), None],
             ["F5", "value", f + ".first", pts[0][1], pts[0][0]], ["F6", "value", f + ".last", pts[-1][1], pts[-1][0]], ["F7", "value", f + ".duration", pts[-1][0] - pts[0][0], None]]
    series = pts
    if len(pts) > MAX_PTS:
        nb, size, series = MAX_PTS // 2, len(pts) / (MAX_PTS // 2), []
        for b in range(nb):
            seg = pts[math.floor(b * size):min(len(pts), math.floor((b + 1) * size))]
            lo = min(range(len(seg)), key=lambda i: (seg[i][1], i)); hi = max(range(len(seg)), key=lambda i: (seg[i][1], -i))
            series += [seg[lo]] if lo == hi else [seg[i] for i in sorted((lo, hi))]
    return dict(status="PARTIAL" if c["gaps"] else "OK", facts=facts, points=[[t, v] for t, v in series])


def alerts(c):
    if c["events"] is None: return dict(status="UNAVAILABLE", count=None, by_level=None, rows=[], has_critical=False)
    f = c["filter"]
    rows = [e for e in c["events"] if fin(e.get("t")) and not (fin(f.get("t0")) and e["t"] < f["t0"]) and not (fin(f.get("t1")) and e["t"] > f["t1"])
            and (not f.get("level") or e["level"] == f["level"]) and (not f.get("predictor") or e["predictor"] == f["predictor"])]
    rows.sort(key=lambda e: -e["t"])         # 穩定排序：同時間維持原順序
    by = {}
    for e in rows: by[e["level"]] = by.get(e["level"], 0) + 1
    status = "PARTIAL" if c["gaps"] else ("OK" if rows else "EMPTY_COMPLETE")
    return dict(status=status, count=len(rows), by_level=by, rows=[[e["t"], e["text"]] for e in rows], has_critical=any(e["level"] == "critical" for e in rows))


def tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9_]+|[一-鿿]+", (text or "").lower()):
        if re.fullmatch(r"[a-z0-9_]+", w) or len(w) == 1: out.append(w)
        else: out += [w[i:i + 2] for i in range(len(w) - 1)]
    return out


def manual(chunks, c, glossary):
    q = c["query"] or ""
    extra = [w for zh, ws in (glossary if c["use_glossary"] else {}).items() if zh in q for w in ws]
    terms = list(dict.fromkeys(tokens(q + " " + " ".join(extra) if extra else q)))
    docs = [tokens(ch["text"]) for ch in chunks]
    n = len(docs); avg = sum(len(d) for d in docs) / n if n else 0
    df = {}
    for d in docs:
        for t in set(d): df[t] = df.get(t, 0) + 1
    scored = []
    for ch, d in zip(chunks, docs):
        s = 0.0
        for t in terms:
            tf = d.count(t)
            if tf: s += math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf * (K1 + 1) / (tf + K1 * (1 - B + B * (len(d) / avg if avg else 0)))
        if s > 0: scored.append((-s, ch["chunk_id"]))
    scored.sort()
    hits = [[cid, -s] for s, cid in scored[:TOP_K]]
    return dict(status="OK" if hits else "EMPTY_COMPLETE", hits=hits)


def main():
    V = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), sys.argv[1] if len(sys.argv) > 1 else "vectors.json"), encoding="utf-8"))
    C, out = V["cases"], {}
    for c in C["energy"]: out[c["id"]] = energy(c["samples"], c["opts"])
    for c in C["telemetry"]: out[c["id"]] = telemetry(c)
    for c in C["flightlog"]: out[c["id"]] = flightlog(c)
    for c in C["alerts"]: out[c["id"]] = alerts(c)
    for c in C["manual"]: out[c["id"]] = manual(V["chunks"], c, V["glossary"])
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
