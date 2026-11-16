.pragma library
// GenUI M1 規則版：5 個唯讀工具的純計算部分（不讀檔、不連線、不對飛機下指令）。
// 依據：M1 演算法說明 v2 §3、契約附件 v1 §C 與 v3 第一部分 §C（電量斜率：先清理、再取視窗）。
// 版本 m1v2：依 v3 §C（已確認）與 v3.1 草案 §C'、§D-6'、§L' 修改；舊版 genui_m1/ 不動。
// 資料由呼叫端（重放器或紀錄讀取器）以陣列傳入；缺值一律不補。數值門檻都是候選值〔待凍結〕。

var TOOLS_VERSION = "tools-m1-0.2.2"
var STATUS = ["OK", "EMPTY_COMPLETE", "PARTIAL", "UNAVAILABLE", "STALE", "INSUFFICIENT", "UNSUPPORTED", "ERROR"]

var STALE_AFTER_S = 2          // 〔待凍結〕
var FUTURE_TOLERANCE_S = 1     // 〔待凍結〕
var ENERGY = { W: 60, N_MIN: 10, COVERAGE_MIN: 0.8, GAP_MAX_S: 10, EPS: 0.05, R2_MIN: 0.5, DISORDER_MAX: 0.2, ETA_MAX_MIN: 600 } // 〔待凍結〕
var SERIES_MAX_POINTS = 300
var ROUTE_MAX_POINTS = 500
var DOC_TOP_K = 5
var BM25 = { k1: 1.2, b: 0.75 }
var NUM_EPS = 1e-9             // 方向與 ETA 邊界的數值容差（v3.1 §C' 第 4 點）
var SERIES_BUCKETS = 150       // 〔待凍結〕
var DOC_QUALIFY = { MIN_COVERAGE: 0.5, DF_MAX: 0.2 }   // 〔待凍結〕v3.1 §L'
var DOC_STOP = ["可不可以", "是什麼", "為什麼", "能不能", "會不會", "怎麼", "如何", "為何", "哪裡", "多少", "什麼", "是否", "請問", "怎樣", "哪", "幾", "嗎", "呢"]   // 長的在前

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
        if (s && finite(s.t) && finite(s.value) && s.t >= t0 && s.t <= t1) pts.push({ t: s.t, value: s.value, arrival: i })
    }
    // 依 t 排序，同一時戳保留到達順序（不依賴 sort 是否穩定）；不去重（v3.1 §D-6'）
    pts.sort(function (a, b) { return a.t - b.t || a.arrival - b.arrival })
    var coverage = { requested: [t0, t1], covered: pts.length ? [pts[0].t, pts[pts.length - 1].t] : null, gaps: gaps || [] }
    if (!pts.length) return result("T_FLIGHTLOG", inputs, coverage.gaps.length ? "PARTIAL" : "EMPTY_COMPLETE", [], coverage)
    var min = pts[0].value, max = pts[0].value, sum = 0
    for (i = 0; i < pts.length; ++i) { min = Math.min(min, pts[i].value); max = Math.max(max, pts[i].value); sum += pts[i].value }
    var series = []
    if (pts.length > SERIES_MAX_POINTS) {
        // 減量只為顯示：[第一筆 t, 最後一筆 t] 等分 150 桶；每桶輸出最小、最大（同值取排序在前的）兩點，依排序先後
        var tA = pts[0].t, width = (pts[pts.length - 1].t - tA) / SERIES_BUCKETS, bucket = []
        for (i = 0; i < SERIES_BUCKETS; ++i) bucket.push(null)
        for (i = 0; i < pts.length; ++i) {
            var bi = width > 0 ? Math.min(SERIES_BUCKETS - 1, Math.floor((pts[i].t - tA) / width)) : 0
            var bk = bucket[bi] || (bucket[bi] = { mn: i, mx: i })
            if (pts[i].value < pts[bk.mn].value) bk.mn = i
            if (pts[i].value > pts[bk.mx].value) bk.mx = i
        }
        for (i = 0; i < SERIES_BUCKETS; ++i) {
            if (!bucket[i]) continue
            var lo = Math.min(bucket[i].mn, bucket[i].mx), hi = Math.max(bucket[i].mn, bucket[i].mx)
            series.push({ t: pts[lo].t, value: pts[lo].value })
            if (hi !== lo) series.push({ t: pts[hi].t, value: pts[hi].value })
        }
    } else for (i = 0; i < pts.length; ++i) series.push({ t: pts[i].t, value: pts[i].value })
    var downsampled = pts.length > SERIES_MAX_POINTS
    var last = pts[pts.length - 1]
    var facts = [
        fact("F1", "series", field, null, unit, last.t, { points: series, downsampled: downsampled }),
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
// samples: 依到達順序的 [{t, soc}]。opts: {now, reservePct, reserveAssumed, checkStale, vehicleType}
// W 固定 60 秒，不接受呼叫端覆寫（v3.1 §C' 第 1 點）。
function energyTrend(samples, opts) {
    opts = opts || {}
    var P = ENERGY, W = P.W, reserve = opts.reservePct
    var reserveValid = finite(reserve) && reserve >= 0 && reserve <= 100          // 100 有效（v3 §C）
    var inputs = { W: W, reserve_pct: finite(reserve) ? reserve : null }
    var out = { slope_pct_per_min: null, r2: null, n_valid: 0, n_dropped: 0, coverage_ratio: null, direction: null,
                eta_min: null, eta_reason: "", disorder_ratio: null, reserve_valid: reserveValid, reserve_invalid: !reserveValid,
                reserve_pct: finite(reserve) ? reserve : null, reserve_assumed: !!opts.reserveAssumed, stale: false, insufficient_reason: "", reason: "" }
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
    if (!clean.length) { out.reason = out.insufficient_reason = "no_valid_samples"; return done("INSUFFICIENT") }
    // 2 亂序比例（分母：清理後、去重前、取視窗前的全部筆數）
    var maxT = -Infinity, disorder = 0
    for (i = 0; i < clean.length; ++i) { if (clean[i].t < maxT) disorder++; else maxT = clean[i].t }
    out.disorder_ratio = disorder / clean.length
    if (out.disorder_ratio > P.DISORDER_MAX) out.insufficient_reason = "disorder"
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
    out.stale = !!(opts.checkStale && finite(opts.now) && opts.now - tEnd > STALE_AFTER_S)
    // 5 充分性（不論是否過期都檢查，結果都留在 detail；v3.1 §C' 第 5 點）
    var maxGap = 0
    for (i = 1; i < win.length; ++i) maxGap = Math.max(maxGap, win[i].t - win[i - 1].t)
    if (!out.insufficient_reason) {
        if (win.length < P.N_MIN) out.insufficient_reason = "n_valid"
        else if (out.coverage_ratio < P.COVERAGE_MIN) out.insufficient_reason = "coverage"
        else if (maxGap > P.GAP_MAX_S) { out.insufficient_reason = "gap"; cov.gaps.push({ max_gap_s: maxGap }) }
    }
    var last = win[win.length - 1]
    if (out.stale) { out.reason = "stale"; return done("STALE", [fact("F1", "value", "soc", last.soc, "%", tEnd)], cov) }
    if (out.insufficient_reason) { out.reason = out.insufficient_reason; return done("INSUFFICIENT", [], cov) }
    // 6 零變異
    var xb = 0, sb = 0, n = win.length
    for (i = 0; i < n; ++i) { xb += win[i].t - tFirst; sb += win[i].soc }
    xb /= n; sb /= n
    var sxx = 0, sxy = 0, syy = 0
    for (i = 0; i < n; ++i) { var dx = win[i].t - tFirst - xb, dy = win[i].soc - sb; sxx += dx * dx; sxy += dx * dy; syy += dy * dy }
    if (sxx === 0) { out.reason = out.insufficient_reason = "zero_time_variance"; return done("INSUFFICIENT", [], cov) }
    var windowLabel = { t0: tFirst, t1: tEnd }, points = []
    for (i = 0; i < n; ++i) points.push({ t: win[i].t, soc: win[i].soc })
    function trendFact(slope, r2, intercept) {
        return fact("F1", "trend", "soc", slope, "%/min", tEnd, { direction: out.direction, window: windowLabel, r2: r2,
                    intercept: intercept, t_ref: tFirst, eta_min: out.eta_min, eta_reason: out.eta_reason,
                    reserve_pct: out.reserve_pct, reserve_valid: reserveValid, reserve_assumed: !!opts.reserveAssumed })
    }
    function finish(slope, r2, intercept) {
        return done("OK", [trendFact(slope, r2, intercept), fact("F2", "value", "soc", last.soc, "%", tEnd),
                           fact("F3", "series", "soc", null, "%", tEnd, { points: points })], cov)
    }
    if (syy === 0) {
        out.slope_pct_per_min = 0; out.direction = "持平"; out.eta_reason = "not_falling"
        return finish(0, null, sb)
    }
    // 7 最小平方直線
    var slope = sxy / sxx * 60, r2 = (sxy * sxy) / (sxx * syy)
    out.slope_pct_per_min = slope; out.r2 = r2
    if (r2 < P.R2_MIN) { out.reason = out.insufficient_reason = "r2"; return done("INSUFFICIENT", [], cov) }
    // 8 方向（|斜率| ≤ 0.05 + 1e-9 為持平）
    out.direction = slope < -(P.EPS + NUM_EPS) ? "下降" : (slope > P.EPS + NUM_EPS ? "上升" : "持平")
    // 9 ETA（v3.1 §C' 第 3 點）
    if (out.direction !== "下降") out.eta_reason = "not_falling"
    else if (!reserveValid) out.eta_reason = "reserve_invalid"
    else if (!(last.soc > reserve)) out.eta_reason = "at_or_below_reserve"
    else {
        var eta = (last.soc - reserve) / Math.abs(slope)
        if (eta <= P.ETA_MAX_MIN + NUM_EPS) out.eta_min = eta
        else out.eta_reason = "over_limit"
    }
    return finish(slope, r2, sb - (sxy / sxx) * xb)
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
        rows.push({ e: e, arrival: i })
    }
    // 新的在前；同一時間依到達順序（Qt 的 sort 不穩定，qt_poc_run1 發現）
    rows.sort(function (a, b) { return b.e.t - a.e.t || a.arrival - b.arrival })
    for (i = 0; i < rows.length; ++i) rows[i] = rows[i].e
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
    // 去重（v3 §L-3，排名前做）：先依 chunk_id，再依「同文件且文字相同」，都保留第一次出現的
    var uniq = [], seenId = {}, seenText = {}
    for (var u = 0; u < chunks.length; ++u) {
        var ch = chunks[u], tk = String(ch.doc) + "\u0000" + String(ch.text)
        if (Object.prototype.hasOwnProperty.call(seenId, ch.chunk_id) || Object.prototype.hasOwnProperty.call(seenText, tk)) continue
        seenId[ch.chunk_id] = true; seenText[tk] = true; uniq.push(ch)
    }
    chunks = uniq
    var stripped = String(query || "")
    for (u = 0; u < DOC_STOP.length; ++u) stripped = stripped.split(DOC_STOP[u]).join(" ")
    var qTokens = tokenize(expandQuery(stripped, glossary)), seen = Object.create(null), terms = []
    for (var i = 0; i < qTokens.length; ++i) if (!seen[qTokens[i]]) { seen[qTokens[i]] = true; terms.push(qTokens[i]) }
    var docs = [], avg = 0, df = Object.create(null)
    for (i = 0; i < chunks.length; ++i) {
        var toks = tokenize(chunks[i].text), tf = Object.create(null)
        for (var j = 0; j < toks.length; ++j) tf[toks[j]] = (tf[toks[j]] || 0) + 1
        for (var t in tf) df[t] = (df[t] || 0) + 1
        docs.push({ chunk: chunks[i], tf: tf, len: toks.length }); avg += toks.length
    }
    avg = docs.length ? avg / docs.length : 0
    // 內容詞：去掉出現在超過 20% 片段裡的詞；去掉後一個都不剩就不做這一步（v3.1b §L'）
    var content = []
    for (j = 0; j < terms.length; ++j) if (!docs.length || (df[terms[j]] || 0) / docs.length <= DOC_QUALIFY.DF_MAX) content.push(terms[j])
    // 退路：剩下的詞沒有一個出現在手冊裡，就不做這一步（m1v2 run1 發現的漏洞，見 runs/m1v2_run1_20261116/RECORD.md）
    var anyPresent = false
    for (j = 0; j < content.length; ++j) if (df[content[j]]) anyPresent = true
    if (!anyPresent) content = terms.slice()
    var scored = []
    for (i = 0; i < docs.length; ++i) {
        var hitN = 0
        for (j = 0; j < content.length; ++j) if (docs[i].tf[content[j]]) hitN++
        var cover = content.length ? hitN / content.length : 0
        var score = 0
        for (j = 0; j < terms.length; ++j) {
            var f = docs[i].tf[terms[j]]
            if (!f) continue
            var idf = Math.log(1 + (docs.length - df[terms[j]] + 0.5) / (df[terms[j]] + 0.5))
            score += idf * f * (BM25.k1 + 1) / (f + BM25.k1 * (1 - BM25.b + BM25.b * (avg ? docs[i].len / avg : 0)))
        }
        // 合格：命中的內容詞 ≥ 一半（至少 1 個）。M1 只有關鍵字，屬降級路徑。
        if (score > 0 && hitN >= 1 && cover >= DOC_QUALIFY.MIN_COVERAGE) scored.push({ chunk: docs[i].chunk, score: score, cover: cover })
    }
    scored.sort(function (a, b) { return b.score - a.score || (a.chunk.chunk_id < b.chunk.chunk_id ? -1 : a.chunk.chunk_id > b.chunk.chunk_id ? 1 : 0) })
    var facts = []
    for (i = 0; i < scored.length && i < DOC_TOP_K; ++i) {
        var c = scored[i].chunk
        facts.push(fact("F" + (i + 1), "doc_quote", "manual", c.text, "", null,
                        { chunk_id: c.chunk_id, doc: c.doc, heading: c.heading, doc_version: c.version, score: scored[i].score, content_coverage: scored[i].cover }))
    }
    if (!facts.length) return result("T_MANUAL_SEARCH", inputs, "EMPTY_COMPLETE", [fact("F1", "not_found", "manual", null, "", null)], null, { degraded: true })
    return result("T_MANUAL_SEARCH", inputs, "OK", facts, null, { degraded: true })
}
