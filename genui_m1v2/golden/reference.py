"""G4 對照版：依契約附件（v1 §C、v3 第一部分 §C）與 M1 演算法說明 v2 §3 獨立實作的 Python 版工具計算。

不匯入、不翻譯 JS 版；只吃 vectors.json 的輸入，輸出和 run_js.js 相同形狀的精簡結果。
執行：python3 -I genui_m1v2/golden/reference.py vectors_v3.json > py.json
版本 m1v2：依 v3 §C、§L-3 與 v3.1 草案 §C'、§D-6'、§L' 修改；舊版 genui_m1/golden 不動。
"""
import json, math, os, re, sys

STALE_S, FUTURE_S = 2.0, 1.0
W, N_MIN, COV_MIN, GAP_MAX, EPS, R2_MIN, DIS_MAX, ETA_MAX = 60.0, 10, 0.8, 10.0, 0.05, 0.8, 0.2, 600.0
JUMP = 5.0   # V3.1-2
K1, B, TOP_K, MAX_PTS = 1.2, 0.75, 5, 300
NUM_EPS, BUCKETS, DOC_MIN_COV, DOC_DF_MAX = 1e-9, 150, 0.5, 0.2
DOC_STOP = ["可不可以", "是什麼", "為什麼", "能不能", "會不會", "怎麼", "如何", "為何", "哪裡", "多少", "什麼", "是否", "請問", "怎樣", "哪", "幾", "嗎", "呢"]


def fin(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


ORDER = ["no_valid_samples", "n_valid", "coverage", "gap", "disorder", "zero_time_variance", "r2"]


def energy(samples, o):
    """v3.1c E1～E4：清理 → 亂序 → 排序去重（同時戳留後到）→ 名目窗 [t_end-60, t_end] 內找最近跳變（絕對差 > 5）→ 有效窗；
    覆蓋率分母 60；所有檢查都做；固定電量回歸前判；沒有趨勢 eta_reason = no_trend。"""
    res = o.get("reservePct")
    rv = fin(res) and 0 <= res <= 100
    d = dict(slope_pct_per_min=None, r2=None, n_valid=0, n_dropped=0, coverage_ratio=None, direction=None, eta_min=None, eta_reason="no_trend",
             disorder_ratio=None, reserve_valid=rv, reserve_invalid=not rv, reserve_pct=res if fin(res) else None,
             reserve_assumed=bool(o.get("reserveAssumed")), stale=False, insufficient_reasons=[], insufficient_reason="", reason="", jump_at=None)
    out = dict(status=None, detail=d, requested=None, covered=None, points=None, intercept=None)

    def why(c):
        if c not in d["insufficient_reasons"]: d["insufficient_reasons"].append(c)

    def ret(status):
        d["insufficient_reasons"].sort(key=ORDER.index)
        d["insufficient_reason"] = d["insufficient_reasons"][0] if d["insufficient_reasons"] else ""
        if not d["reason"]: d["reason"] = "stale" if status == "STALE" else d["insufficient_reason"]
        out["status"] = status; return out

    if o.get("vehicleType") and o["vehicleType"] != "multirotor":
        d["reason"] = "vehicle_type"; return ret("UNSUPPORTED")
    if samples is None:
        d["reason"] = "no_source"; return ret("UNAVAILABLE")
    now = o.get("now")
    kept = []
    for i, s in enumerate(samples):
        s = s if isinstance(s, dict) else {}
        t, soc = s.get("t"), s.get("soc")
        if not fin(t) or (fin(now) and t > now + FUTURE_S) or not fin(soc) or soc < 0 or soc > 100:
            d["n_dropped"] += 1
        else:
            kept.append((t, i, soc))
    if not kept:
        why("no_valid_samples"); return ret("INSUFFICIENT")
    seen_max, dis = -math.inf, 0
    for t, _, _ in kept:
        if t < seen_max: dis += 1
        else: seen_max = t
    d["disorder_ratio"] = dis / len(kept)
    if d["disorder_ratio"] > DIS_MAX: why("disorder")
    latest = {}
    for t, i, soc in sorted(kept):
        latest[t] = soc
    ts = sorted(latest)
    t_end = ts[-1]
    nom = [t for t in ts if t >= t_end - W]
    start = 0
    for k in range(1, len(nom)):
        if abs(latest[nom[k]] - latest[nom[k - 1]]) > JUMP: start = k
    d["jump_at"] = nom[start] if start > 0 else None
    win = [(t, latest[t]) for t in nom[start:]]
    d["n_valid"] = len(win)
    t0 = win[0][0]
    d["coverage_ratio"] = (t_end - t0) / W
    out["requested"], out["covered"] = [t_end - W, t_end], [t0, t_end]
    out["points"] = [[t, s] for t, s in win]
    d["stale"] = bool(o.get("checkStale") and fin(now) and now - t_end > STALE_S)
    gap = max([b[0] - a[0] for a, b in zip(win, win[1:])] or [0])
    if len(win) < N_MIN: why("n_valid")
    if d["coverage_ratio"] < COV_MIN: why("coverage")
    if gap > GAP_MAX: why("gap")
    n = len(win)
    ys = [s for _, s in win]
    slope = r2 = icpt = None
    if n >= 2 and len(set(ys)) == 1 and t_end > t0:
        slope, icpt, d["direction"] = 0, ys[0], "持平"
    elif n >= 2:
        xs = [t - t0 for t, _ in win]
        xb, yb = sum(xs) / n, sum(ys) / n
        sxx = sum((x - xb) ** 2 for x in xs); syy = sum((y - yb) ** 2 for y in ys)
        sxy = sum((x - xb) * (y - yb) for x, y in zip(xs, ys))
        if sxx == 0: why("zero_time_variance")
        else:
            slope, r2, icpt = sxy / sxx * 60, sxy * sxy / (sxx * syy), yb - (sxy / sxx) * xb
            if r2 < R2_MIN: why("r2")
            else: d["direction"] = "下降" if slope < -(EPS + NUM_EPS) else ("上升" if slope > EPS + NUM_EPS else "持平")
    else:
        why("zero_time_variance")
    d["slope_pct_per_min"], d["r2"] = slope, r2
    if d["stale"]:
        d["direction"], out["points"] = None, None; return ret("STALE")      # 過期不給可畫序列
    if d["insufficient_reasons"]:
        d["direction"] = None; return ret("INSUFFICIENT")
    out["intercept"] = icpt
    if d["direction"] != "下降": d["eta_reason"] = "not_falling"
    elif not rv: d["eta_reason"] = "reserve_invalid"
    elif not ys[-1] > res: d["eta_reason"] = "at_or_below_reserve"
    else:
        eta = (ys[-1] - res) / abs(slope)
        if eta <= ETA_MAX + NUM_EPS: d["eta_min"], d["eta_reason"] = eta, ""
        else: d["eta_reason"] = "over_limit"
    return ret("OK")


def telemetry(c):
    if c["samples"] is None: return dict(status="UNAVAILABLE", facts=[])
    now = c.get("now")
    ok = [(s["t"], k, s["value"]) for k, s in enumerate(c["samples"]) if isinstance(s, dict) and fin(s.get("t")) and fin(s.get("value")) and not (fin(now) and s["t"] > now + FUTURE_S)]
    if not ok: return dict(status="UNAVAILABLE", facts=[])
    t, _, v = max(ok)                        # 時間最大；同時間取後到的
    return dict(status="STALE" if fin(now) and now - t > STALE_S else "OK", facts=[["F1", "value", c["field"], v, t]])


def flightlog(c):
    """v3.1 §D-6'：同時戳保留到達順序、不去重；統計用全部原始值；超過 300 點等分 150 桶（依時間），每桶留最小與最大。"""
    if c["samples"] is None: return dict(status="ERROR", facts=[], points=[])            # v3.1c F3
    raw = sorted([(s["t"], k, s["value"]) for k, s in enumerate(c["samples"]) if isinstance(s, dict) and fin(s.get("t")) and fin(s.get("value")) and c["t0"] <= s["t"] <= c["t1"]],
                 key=lambda p: (p[0], p[1]))
    arrival = [k for _, k, _ in raw]
    pts = [(t, v) for t, _, v in raw]
    if not pts: return dict(status="PARTIAL" if c["gaps"] else "ERROR", facts=[], points=[])
    vals = [v for _, v in pts]
    total = 0.0
    for v in vals: total += v
    f = c["field"]
    facts = [["F2", "value", f + ".min", min(vals), None], ["F3", "value", f + ".max", max(vals), None], ["F4", "value", f + ".mean", total / len(vals), None],
             ["F5", "value", f + ".first", pts[0][1], pts[0][0]], ["F6", "value", f + ".last", pts[-1][1], pts[-1][0]], ["F7", "value", f + ".duration", pts[-1][0] - pts[0][0], None]]
    series = pts
    if len(pts) > MAX_PTS:
        ta, width = pts[0][0], (pts[-1][0] - pts[0][0]) / BUCKETS
        groups = {}
        for i, (t, v) in enumerate(pts):
            bi = min(BUCKETS - 1, math.floor((t - ta) / width)) if width > 0 else 0
            groups.setdefault(bi, []).append(i)
        series = []
        for bi in sorted(groups):
            idx = groups[bi]
            lo = min(idx, key=lambda i: (pts[i][1], arrival[i])); hi = max(idx, key=lambda i: (pts[i][1], -arrival[i]))   # 同值取最早到達
            series += [pts[i] for i in sorted({lo, hi})]
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


QUERY_STOP = ["如何", "設定", "怎麼", "請問"]
LEX = ["返航", "保留", "電量", "電池", "電壓", "電流", "高度", "速度", "航向", "姿態", "衛星", "訊號", "遙測", "位置",
       "距離", "溫度", "風速", "告警", "警告", "異常", "航線", "航點", "任務", "地圖", "報告", "紀錄", "日誌", "手冊", "參數",
       "起飛", "降落", "懸停", "解鎖", "上鎖", "低電量", "失控", "保護", "校準", "馬達", "螺旋槳", "遙控器", "電子圍籬", "禁航區"]


def content_terms(query):
    """v3.1c L2：停用詞去掉；詞表最長比對；剩下連續漢字切兩字（單字保留）；英數整詞。"""
    q = (query or "").lower()
    for w in DOC_STOP + QUERY_STOP: q = q.replace(w, " ")
    lex = sorted(LEX, key=lambda w: (-len(w), LEX.index(w)))
    out = []
    def push(t):
        if t not in out: out.append(t)
    for w in re.findall(r"[a-z0-9_]+|[一-鿿]+", q):
        if re.fullmatch(r"[a-z0-9_]+", w): push(w); continue
        i, rest = 0, ""
        def flush(r):
            if len(r) == 1: push(r)
            else:
                for k in range(len(r) - 1): push(r[k:k + 2])
        while i < len(w):
            hit = next((x for x in lex if w.startswith(x, i)), None)
            if hit:
                if rest: flush(rest); rest = ""
                push(hit); i += len(hit)
            else:
                rest += w[i]; i += 1
        if rest: flush(rest)
    return out


def manual(chunks, c, glossary):
    """v3.1c L1～L4：兩階段去重 → BM25 排名先截前 50 → 內容詞（規則 v1）合格 ≥ 一半 → 前 5。"""
    s1, ids = [], set()
    for ch in chunks:
        if str(ch["chunk_id"]) in ids: continue
        ids.add(str(ch["chunk_id"])); s1.append(ch)
    uniq, texts = [], set()
    for ch in s1:
        key = (ch["doc"], ("sha", ch["text_sha256"]) if ch.get("text_sha256") else ("raw", ch["text"]))
        if key in texts: continue
        texts.add(key); uniq.append(ch)
    q = c["query"] or ""
    for w in DOC_STOP: q = q.replace(w, " ")
    extra = [w for zh, ws in (glossary if c["use_glossary"] else {}).items() if zh in q for w in ws]
    terms = list(dict.fromkeys(tokens(q + " " + " ".join(extra) if extra else q)))
    docs = [tokens(ch["text"]) for ch in uniq]
    n = len(docs); avg = sum(len(d) for d in docs) / n if n else 0
    df = {}
    for d in docs:
        for t in set(d): df[t] = df.get(t, 0) + 1
    ct = content_terms(c["query"])
    cdf = {t: sum(1 for ch in uniq if t in ch["text"].lower()) for t in ct}
    content = [t for t in ct if not n or cdf[t] / n <= DOC_DF_MAX]
    if not any(cdf[t] for t in content): content = list(ct)
    need = min(len(ct), 2 if len(ct) >= 2 else 1)
    if len(content) < need:
        keep = set(sorted(ct, key=lambda t: (cdf[t], ct.index(t)))[:need])
        content = [t for t in ct if t in keep]
    ranked = []
    for k, (ch, d) in enumerate(zip(uniq, docs)):
        s = 0.0
        for t in terms:
            tf = d.count(t)
            if tf: s += math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf * (K1 + 1) / (tf + K1 * (1 - B + B * (len(d) / avg if avg else 0)))
        if s > 0: ranked.append((-s, k, ch))
    ranked.sort(key=lambda x: (x[0], x[1]))
    hits = []
    for negs, _, ch in ranked[:50]:
        hit = sum(1 for t in content if t in ch["text"].lower())
        if content and hit >= 1 and hit / len(content) >= DOC_MIN_COV: hits.append([ch["chunk_id"], -negs])
    hits = hits[:TOP_K]
    return dict(status="OK" if hits else "EMPTY_COMPLETE", hits=hits)


def main():
    V = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), sys.argv[1] if len(sys.argv) > 1 else "vectors.json"), encoding="utf-8"))
    C, out = V["cases"], {}
    for c in C["energy"]: out[c["id"]] = energy(c["samples"], c["opts"])
    for c in C["telemetry"]: out[c["id"]] = telemetry(c)
    for c in C["flightlog"]: out[c["id"]] = flightlog(c)
    for c in C["alerts"]: out[c["id"]] = alerts(c)
    for c in C["manual"]: out[c["id"]] = manual([k for k in V["chunks"] if not c.get("set") or k.get("set") == c["set"]], c, V["glossary"])
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
