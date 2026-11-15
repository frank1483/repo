.pragma library
// GenUI M1 規則版：5 個唯讀工具的純計算部分（不讀檔、不連線、不對飛機下指令）。
// 依據：M1 演算法說明 v2 §3、契約附件 v1 §C 與 v3 第一部分 §C（電量斜率：先清理、再取視窗）。
// 資料由呼叫端（重放器或紀錄讀取器）以陣列傳入；缺值一律不補。數值門檻都是候選值〔待凍結〕。

var TOOLS_VERSION = "tools-m1-0.1"
var STATUS = ["OK", "EMPTY_COMPLETE", "PARTIAL", "UNAVAILABLE", "STALE", "INSUFFICIENT", "UNSUPPORTED", "ERROR"]

var STALE_AFTER_S = 2          // 〔待凍結〕
var FUTURE_TOLERANCE_S = 1     // 〔待凍結〕
var ENERGY = { W: 60, N_MIN: 10, COVERAGE_MIN: 0.8, GAP_MAX_S: 10, EPS: 0.05, R2_MIN: 0.5, DISORDER_MAX: 0.2, ETA_MAX_MIN: 600 } // 〔待凍結〕
var SERIES_MAX_POINTS = 300
var ROUTE_MAX_POINTS = 500
var DOC_TOP_K = 5
var BM25 = { k1: 1.2, b: 0.75 }

function finite(x) { return typeof x === "number" && isFinite(x) }
function result(tool, inputs, status, facts, coverage, extra) {
    var r = { tool: tool, version: TOOLS_VERSION, inputs: inputs || {}, facts: facts || [], source: (extra && extra.source) || null,
              coverage: coverage || { requested: null, covered: null, gaps: [] }, status: status }
    if (extra) for (var k in extra) if (k !== "source") r[k] = extra[k]
    return r
}
function fact(id, kind, subject, value, unit, time, more) {
    var f = { fact_id: id, kind: kind, subject: subject, value: value, unit: unit || "", time: time === undefined ? null : time }
    if (more) for (var k in more) f[k] = more[k]
    return f
}

// ---------------------------------------------------------------- T_TELEMETRY
// samples: [{t, value}]（同一欄位）；now: 重放目前的來源時間（秒）
function telemetryLatest(field, unit, samples, now) {
    var inputs = { field: field, now: now }
    if (!samples) return result("T_TELEMETRY", inputs, "UNAVAILABLE")
    var best = null
    for (var i = 0; i < samples.length; ++i) {
        var s = samples[i]
        if (!s || !finite(s.t) || !finite(s.value)) continue
        if (finite(now) && s.t > now + FUTURE_TOLERANCE_S) continue
        if (!best || s.t >= best.t) best = s
    }
    if (!best) return result("T_TELEMETRY", inputs, "UNAVAILABLE")
    var stale = finite(now) && now - best.t > STALE_AFTER_S
    return result("T_TELEMETRY", inputs, stale ? "STALE" : "OK", [fact("F1", "value", field, best.value, unit, best.t)])
}

// ---------------------------------------------------------------- T_FLIGHTLOG
// samples: [{t, value}]；回傳統計與（必要時分桶的）序列。gaps: 呼叫端已知的缺段 [{t0,t1}]
function flightlogSeries(field, unit, samples, t0, t1, gaps) {
    var inputs = { field: field, t0: t0, t1: t1 }
    if (!samples) return result("T_FLIGHTLOG", inputs, "UNAVAILABLE")
    var pts = []
    for (var i = 0; i < samples.length; ++i) {
        var s = samples[i]
        if (s && finite(s.t) && finite(s.value) && s.t >= t0 && s.t <= t1) pts.push({ t: s.t, value: s.value })
    }
    pts.sort(function (a, b) { return a.t - b.t })
    var coverage = { requested: [t0, t1], covered: pts.length ? [pts[0].t, pts[pts.length - 1].t] : null, gaps: gaps || [] }
    if (!pts.length) return result("T_FLIGHTLOG", inputs, coverage.gaps.length ? "PARTIAL" : "EMPTY_COMPLETE", [], coverage)
    var min = pts[0].value, max = pts[0].value, sum = 0
    for (i = 0; i < pts.length; ++i) { min = Math.min(min, pts[i].value); max = Math.max(max, pts[i].value); sum += pts[i].value }
    var series = pts
    if (pts.length > SERIES_MAX_POINTS) {          // 分桶，每桶保留最小與最大值
        var buckets = Math.floor(SERIES_MAX_POINTS / 2), size = pts.length / buckets
        series = []
        for (var b = 0; b < buckets; ++b) {
            var lo = Math.floor(b * size), hi = Math.min(pts.length, Math.floor((b + 1) * size)), mn = pts[lo], mx = pts[lo]
            for (var j = lo; j < hi; ++j) { if (pts[j].value < mn.value) mn = pts[j]; if (pts[j].value > mx.value) mx = pts[j] }
            if (mn === mx) series.push(mn)
            else if (mn.t < mx.t) series.push(mn, mx)
            else series.push(mx, mn)
        }
    }
    var last = pts[pts.length - 1]
    var facts = [
        fact("F1", "series", field, null, unit, last.t, { points: series, downsampled: series !== pts }),
        fact("F2", "value", field + ".min", min, unit, null),
        fact("F3", "value", field + ".max", max, unit, null),
        fact("F4", "value", field + ".mean", sum / pts.length, unit, null),
        fact("F5", "value", field + ".first", pts[0].value, unit, pts[0].t),
        fact("F6", "value", field + ".last", last.value, unit, last.t),
        fact("F7", "value", field + ".duration", last.t - pts[0].t, "s", null)
    ]
    return result("T_FLIGHTLOG", inputs, coverage.gaps.length ? "PARTIAL" : "OK", facts, coverage)
}

// ---------------------------------------------------------------- T_ENERGY（電量斜率）
// samples: 依到達順序的 [{t, soc}]。opts: {now, reservePct, reserveAssumed, checkStale, vehicleType, W}
function energyTrend(samples, opts) {
    opts = opts || {}
    var P = ENERGY, W = finite(opts.W) ? opts.W : P.W, inputs = { W: W, reserve_pct: opts.reservePct }
    var out = { slope_pct_per_min: null, r2: null, n_valid: 0, n_dropped: 0, coverage_ratio: null, direction: null,
                eta_min: null, disorder_ratio: null, reserve_invalid: false, reserve_assumed: !!opts.reserveAssumed, reason: "" }
    function done(status, facts, cov) { return result("T_ENERGY", inputs, status, facts || [], cov, { detail: out }) }
    if (opts.vehicleType && opts.vehicleType !== "multirotor") { out.reason = "vehicle_type"; return done("UNSUPPORTED") }
    if (!samples) { out.reason = "no_source"; return done("UNAVAILABLE") }
    // 1 清理
    var clean = []
    for (var i = 0; i < samples.length; ++i) {
        var s = samples[i]
        if (!s || !finite(s.t)) { out.n_dropped++; continue }
        if (finite(opts.now) && s.t > opts.now + FUTURE_TOLERANCE_S) { out.n_dropped++; continue }
        if (!finite(s.soc) || s.soc < 0 || s.soc > 100) { out.n_dropped++; continue }
        clean.push({ t: s.t, soc: s.soc, arrival: i })
    }
    if (!clean.length) { out.reason = "no_valid_samples"; return done("INSUFFICIENT") }
    // 2 亂序比例（去重前；照到達順序，時間小於先前出現過的最大時間就算亂序）
    var maxT = -Infinity, disorder = 0
    for (i = 0; i < clean.length; ++i) { if (clean[i].t < maxT) disorder++; else maxT = clean[i].t }
    out.disorder_ratio = disorder / clean.length
    if (out.disorder_ratio > P.DISORDER_MAX) { out.reason = "disorder"; return done("INSUFFICIENT") }
    // 3 排序與去重（時間戳相同只留最後到達的一筆）
    clean.sort(function (a, b) { return a.t - b.t || a.arrival - b.arrival })
    var dedup = []
    for (i = 0; i < clean.length; ++i) {
        if (dedup.length && dedup[dedup.length - 1].t === clean[i].t) dedup[dedup.length - 1] = clean[i]
        else dedup.push(clean[i])
    }
    // 4 取視窗
    var tEnd = dedup[dedup.length - 1].t, win = []
    for (i = 0; i < dedup.length; ++i) if (dedup[i].t >= tEnd - W) win.push(dedup[i])
    out.n_valid = win.length
    var tFirst = win[0].t, cov = { requested: [tEnd - W, tEnd], covered: [tFirst, tEnd], gaps: [] }
    out.coverage_ratio = (tEnd - tFirst) / W
    if (opts.checkStale && finite(opts.now) && opts.now - tEnd > STALE_AFTER_S) { out.reason = "stale"; return done("STALE", [fact("F1", "value", "soc", win[win.length - 1].soc, "%", tEnd)], cov) }
    // 5 充分性
    var maxGap = 0
    for (i = 1; i < win.length; ++i) maxGap = Math.max(maxGap, win[i].t - win[i - 1].t)
    if (win.length < P.N_MIN) { out.reason = "n_valid"; return done("INSUFFICIENT", [], cov) }
    if (out.coverage_ratio < P.COVERAGE_MIN) { out.reason = "coverage"; return done("INSUFFICIENT", [], cov) }
    if (maxGap > P.GAP_MAX_S) { out.reason = "gap"; cov.gaps.push({ max_gap_s: maxGap }); return done("INSUFFICIENT", [], cov) }
    // 6 零變異
    var xb = 0, sb = 0, n = win.length
    for (i = 0; i < n; ++i) { xb += win[i].t - tFirst; sb += win[i].soc }
    xb /= n; sb /= n
    var sxx = 0, sxy = 0, syy = 0
    for (i = 0; i < n; ++i) { var dx = win[i].t - tFirst - xb, dy = win[i].soc - sb; sxx += dx * dx; sxy += dx * dy; syy += dy * dy }
    if (sxx === 0) { out.reason = "zero_time_variance"; return done("INSUFFICIENT", [], cov) }
    var last = win[n - 1], windowLabel = { t0: tFirst, t1: tEnd }
    if (syy === 0) {
        out.slope_pct_per_min = 0; out.direction = "持平"
        return done("OK", [fact("F1", "trend", "soc", 0, "%/min", tEnd, { direction: "持平", window: windowLabel, r2: null }),
                           fact("F2", "value", "soc", last.soc, "%", tEnd)], cov)
    }
    // 7 最小平方直線
    var slope = sxy / sxx * 60, r2 = (sxy * sxy) / (sxx * syy)
    out.slope_pct_per_min = slope; out.r2 = r2
    if (r2 < P.R2_MIN) { out.reason = "r2"; return done("INSUFFICIENT", [], cov) }
    // 8 方向
    out.direction = slope < -P.EPS ? "下降" : (slope > P.EPS ? "上升" : "持平")
    var facts = [fact("F1", "trend", "soc", slope, "%/min", tEnd, { direction: out.direction, window: windowLabel, r2: r2 }),
                 fact("F2", "value", "soc", last.soc, "%", tEnd)]
    // 9 ETA
    var reserve = opts.reservePct
    if (!finite(reserve) || reserve < 0 || reserve >= 100) out.reserve_invalid = true
    else if (out.direction === "下降" && last.soc > reserve) {
        var eta = (last.soc - reserve) / Math.abs(slope)
        if (eta <= P.ETA_MAX_MIN) { out.eta_min = eta; facts[0].eta_min = eta; facts[0].reserve_pct = reserve; facts[0].reserve_assumed = !!opts.reserveAssumed }
    }
    return done("OK", facts, cov)
}

// ---------------------------------------------------------------- T_ALERT_HISTORY
// events: [{t, level, predictor, text}]；filter: {t0, t1, level, predictor}；gaps: 引擎缺段
function alertHistory(events, filter, gaps) {
    filter = filter || {}
    var inputs = { t0: filter.t0, t1: filter.t1, level: filter.level || null, predictor: filter.predictor || null }
    if (!events) return result("T_ALERT_HISTORY", inputs, "UNAVAILABLE")
    var rows = []
    for (var i = 0; i < events.length; ++i) {
        var e = events[i]
        if (!e || !finite(e.t)) continue
        if (finite(filter.t0) && e.t < filter.t0) continue
        if (finite(filter.t1) && e.t > filter.t1) continue
        if (filter.level && e.level !== filter.level) continue
        if (filter.predictor && e.predictor !== filter.predictor) continue
        rows.push(e)
    }
    rows.sort(function (a, b) { return b.t - a.t })
    var coverage = { requested: [filter.t0, filter.t1], covered: [filter.t0, filter.t1], gaps: gaps || [] }
    var partial = coverage.gaps.length > 0
    var byLevel = {}, hasCritical = false
    for (i = 0; i < rows.length; ++i) { byLevel[rows[i].level] = (byLevel[rows[i].level] || 0) + 1; if (rows[i].level === "critical") hasCritical = true }
    var facts = [fact("F1", "count", "alerts", rows.length, "", null, { level: filter.level || "all", interval: [filter.t0, filter.t1], by_level: byLevel })]
    if (rows.length) facts.push(fact("F2", "series", "alert_events", null, "", rows[0].t, { rows: rows, has_critical: hasCritical }))
    var status = partial ? "PARTIAL" : (rows.length ? "OK" : "EMPTY_COMPLETE")
    return result("T_ALERT_HISTORY", inputs, status, facts, coverage)
}

// ---------------------------------------------------------------- T_MANUAL_SEARCH（M1：只有 BM25，標「降級」）
function tokenize(text) {
    var s = String(text || "").toLowerCase(), out = [], m, re = /[a-z0-9_]+|[一-鿿]+/g
    while ((m = re.exec(s))) {
        var w = m[0]
        if (/^[a-z0-9_]+$/.test(w)) out.push(w)
        else if (w.length === 1) out.push(w)
        else for (var i = 0; i + 1 < w.length; ++i) out.push(w.substr(i, 2))   // 中文用相鄰兩字
    }
    return out
}
// glossary: {中文詞: [英文詞, ...]}；查詢含中文詞就補上英文詞
function expandQuery(query, glossary) {
    var extra = [], q = String(query || "")
    for (var zh in (glossary || {})) if (q.indexOf(zh) >= 0) extra = extra.concat(glossary[zh])
    return extra.length ? q + " " + extra.join(" ") : q
}
// chunks: [{chunk_id, doc, heading, version, text}]
function manualSearch(chunks, query, glossary) {
    var inputs = { query: query, k: DOC_TOP_K }
    if (!chunks) return result("T_MANUAL_SEARCH", inputs, "UNAVAILABLE", [], null, { degraded: true })
    var qTokens = tokenize(expandQuery(query, glossary)), seen = {}, terms = []
    for (var i = 0; i < qTokens.length; ++i) if (!seen[qTokens[i]]) { seen[qTokens[i]] = true; terms.push(qTokens[i]) }
    var docs = [], avg = 0, df = {}
    for (i = 0; i < chunks.length; ++i) {
        var toks = tokenize(chunks[i].text), tf = {}
        for (var j = 0; j < toks.length; ++j) tf[toks[j]] = (tf[toks[j]] || 0) + 1
        for (var t in tf) df[t] = (df[t] || 0) + 1
        docs.push({ chunk: chunks[i], tf: tf, len: toks.length }); avg += toks.length
    }
    avg = docs.length ? avg / docs.length : 0
    var scored = []
    for (i = 0; i < docs.length; ++i) {
        var score = 0
        for (j = 0; j < terms.length; ++j) {
            var f = docs[i].tf[terms[j]]
            if (!f) continue
            var idf = Math.log(1 + (docs.length - df[terms[j]] + 0.5) / (df[terms[j]] + 0.5))
            score += idf * f * (BM25.k1 + 1) / (f + BM25.k1 * (1 - BM25.b + BM25.b * (avg ? docs[i].len / avg : 0)))
        }
        if (score > 0) scored.push({ chunk: docs[i].chunk, score: score })
    }
    scored.sort(function (a, b) { return b.score - a.score || (a.chunk.chunk_id < b.chunk.chunk_id ? -1 : a.chunk.chunk_id > b.chunk.chunk_id ? 1 : 0) })
    var facts = []
    for (i = 0; i < scored.length && i < DOC_TOP_K; ++i) {
        var c = scored[i].chunk
        facts.push(fact("F" + (i + 1), "doc_quote", "manual", c.text, "", null,
                        { chunk_id: c.chunk_id, doc: c.doc, heading: c.heading, doc_version: c.version, score: scored[i].score }))
    }
    if (!facts.length) return result("T_MANUAL_SEARCH", inputs, "EMPTY_COMPLETE", [fact("F1", "not_found", "manual", null, "", null)], null, { degraded: true })
    return result("T_MANUAL_SEARCH", inputs, "OK", facts, null, { degraded: true })
}
