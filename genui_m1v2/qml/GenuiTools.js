.pragma library
// GenUI M1 規則版：5 個唯讀工具的純計算部分（不讀檔、不連線、不對飛機下指令）。
// 依據：M1 演算法說明 v2 §3、契約附件 v1 §C 與 v3 第一部分 §C（電量斜率：先清理、再取視窗）。
// 版本 m1v2：依 v3 §C（已確認）與 v3.1 草案 §C'、§D-6'、§L' 修改；舊版 genui_m1/ 不動。
// 資料由呼叫端（重放器或紀錄讀取器）以陣列傳入；缺值一律不補。數值門檻都是候選值〔待凍結〕。

var TOOLS_VERSION = "tools-m1-0.5"   // 0.5：F2 DEVIATION（說明 f2_deviation_v1，使用者 11/21 03:08 裁決）
var STATUS = ["OK", "EMPTY_COMPLETE", "PARTIAL", "UNAVAILABLE", "STALE", "INSUFFICIENT", "UNSUPPORTED", "ERROR"]

var STALE_AFTER_S = 2          // 〔待凍結〕
var FUTURE_TOLERANCE_S = 1     // 〔待凍結〕
var ENERGY = { W: 60, N_MIN: 10, COVERAGE_MIN: 0.8, GAP_MAX_S: 10, EPS: 0.05, R2_MIN: 0.8, JUMP_PCT: 5, DISORDER_MAX: 0.2, ETA_MAX_MIN: 600 } // 〔待凍結〕
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
    // v3.1c F3：SAMPLES 對外狀態只能是 OK／PARTIAL／INSUFFICIENT／ERROR；沒有來源或區間內沒有資料（且無缺段）一律 ERROR
    if (!samples) return result("T_FLIGHTLOG", inputs, "ERROR", [], null, { internal_status: "UNAVAILABLE" })
    var pts = []
    for (var i = 0; i < samples.length; ++i) {
        var s = samples[i]
        if (s && finite(s.t) && finite(s.value) && s.t >= t0 && s.t <= t1) pts.push({ t: s.t, value: s.value, arrival: i })
    }
    // 依 t 排序，同一時戳保留到達順序（不依賴 sort 是否穩定）；不去重（v3.1 §D-6'）
    pts.sort(function (a, b) { return a.t - b.t || a.arrival - b.arrival })
    var coverage = { requested: [t0, t1], covered: pts.length ? [pts[0].t, pts[pts.length - 1].t] : null, gaps: gaps || [] }
    if (!pts.length) return result("T_FLIGHTLOG", inputs, coverage.gaps.length ? "PARTIAL" : "ERROR", [], coverage, coverage.gaps.length ? null : { internal_status: "EMPTY_COMPLETE" })
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
            // v3.1c F1：同值極值取最早到達的那一列
            if (pts[i].value < pts[bk.mn].value || (pts[i].value === pts[bk.mn].value && pts[i].arrival < pts[bk.mn].arrival)) bk.mn = i
            if (pts[i].value > pts[bk.mx].value || (pts[i].value === pts[bk.mx].value && pts[i].arrival < pts[bk.mx].arrival)) bk.mx = i
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
// 0.4（v3.1c E1～E4，使用者 11/18 20:58「v3.1c 照草案」）：
//   處理順序固定；跳變只在名目窗內找、取最近一次；覆蓋率分母固定 60 秒；
//   所有檢查都做完（過期不提早結束），不足原因記成陣列；固定電量在回歸前判；沒有趨勢時 eta_reason = no_trend。
//   名目窗沿用 v3 第一部分 §C 第 4 步：t_end = 去重後最後一筆的時間，窗為 [t_end − W, t_end]。
var INSUFFICIENT_ORDER = ["no_valid_samples", "n_valid", "coverage", "gap", "disorder", "zero_time_variance", "r2"]
function energyTrend(samples, opts) {
    opts = opts || {}
    var P = ENERGY, W = P.W, reserve = opts.reservePct
    var reserveValid = finite(reserve) && reserve >= 0 && reserve <= 100          // 100 有效（v3 §C）
    var reservePct = finite(reserve) ? reserve : null
    var inputs = { W: W, reserve_pct: reservePct }
    var out = { slope_pct_per_min: null, r2: null, n_valid: 0, n_dropped: 0, coverage_ratio: null, direction: null,
                eta_min: null, eta_reason: "no_trend", disorder_ratio: null, reserve_valid: reserveValid, reserve_invalid: !reserveValid,
                reserve_pct: reservePct, reserve_assumed: !!opts.reserveAssumed, stale: false, insufficient_reasons: [],
                insufficient_reason: "", reason: "", jump_at: null }
    var R = { reserve_pct: reservePct, reserve_valid: reserveValid, reserve_assumed: !!opts.reserveAssumed }
    function why(code) { if (out.insufficient_reasons.indexOf(code) < 0) out.insufficient_reasons.push(code) }
    function done(status, facts, cov) {
        out.insufficient_reasons.sort(function (x, y) { return INSUFFICIENT_ORDER.indexOf(x) - INSUFFICIENT_ORDER.indexOf(y) })
        out.insufficient_reason = out.insufficient_reasons.length ? out.insufficient_reasons[0] : ""
        if (!out.reason) out.reason = status === "STALE" ? "stale" : out.insufficient_reason
        return result("T_ENERGY", inputs, status, facts || [], cov, { detail: out })
    }
    function more(extra) { var m = {}, k; for (k in R) m[k] = R[k]; if (extra) for (k in extra) m[k] = extra[k]; return m }
    if (opts.vehicleType && opts.vehicleType !== "multirotor") { out.reason = "vehicle_type"; return done("UNSUPPORTED") }
    if (!samples) { out.reason = "no_source"; return done("UNAVAILABLE") }
    // E1-1 清理
    var clean = []
    for (var i = 0; i < samples.length; ++i) {
        var s = samples[i]
        if (!s || !finite(s.t)) { out.n_dropped++; continue }
        if (finite(opts.now) && s.t > opts.now + FUTURE_TOLERANCE_S) { out.n_dropped++; continue }
        if (!finite(s.soc) || s.soc < 0 || s.soc > 100) { out.n_dropped++; continue }
        clean.push({ t: s.t, soc: s.soc, arrival: i })
    }
    if (!clean.length) { why("no_valid_samples"); return done("INSUFFICIENT") }
    // E1-2 亂序比例（清理後、依到達順序的完整序列）
    var maxT = -Infinity, disorder = 0
    for (i = 0; i < clean.length; ++i) { if (clean[i].t < maxT) disorder++; else maxT = clean[i].t }
    out.disorder_ratio = disorder / clean.length
    if (out.disorder_ratio > P.DISORDER_MAX) why("disorder")
    // E1-3 排序與去重（同時戳留最後到達的一筆）
    clean.sort(function (a, b) { return a.t - b.t || a.arrival - b.arrival })
    var dedup = []
    for (i = 0; i < clean.length; ++i) {
        if (dedup.length && dedup[dedup.length - 1].t === clean[i].t) dedup[dedup.length - 1] = clean[i]
        else dedup.push(clean[i])
    }
    // E1-4 名目窗內找跳變：相鄰差的絕對值 > 5 個百分點（恰 5 不算），取最近一次
    var tEnd = dedup[dedup.length - 1].t, nominal = []
    for (i = 0; i < dedup.length; ++i) if (dedup[i].t >= tEnd - W) nominal.push(dedup[i])
    var start = 0
    for (i = 1; i < nominal.length; ++i) if (Math.abs(nominal[i].soc - nominal[i - 1].soc) > P.JUMP_PCT) start = i
    out.jump_at = start > 0 ? nominal[start].t : null
    // E1-5 有效窗
    var win = nominal.slice(start)
    out.n_valid = win.length
    var tFirst = win[0].t, cov = { requested: [tEnd - W, tEnd], covered: [tFirst, tEnd], gaps: [] }
    out.coverage_ratio = (tEnd - tFirst) / W                                                  // 分母固定 60 秒
    out.stale = !!(opts.checkStale && finite(opts.now) && opts.now - tEnd > STALE_AFTER_S)
    var maxGap = 0
    for (i = 1; i < win.length; ++i) maxGap = Math.max(maxGap, win[i].t - win[i - 1].t)
    if (win.length < P.N_MIN) why("n_valid")
    if (out.coverage_ratio < P.COVERAGE_MIN) why("coverage")
    if (maxGap > P.GAP_MAX_S) { why("gap"); cov.gaps.push({ max_gap_s: maxGap }) }
    var last = win[win.length - 1], n = win.length
    var points = []
    for (i = 0; i < n; ++i) points.push({ t: win[i].t, soc: win[i].soc })
    var windowLabel = { t0: tFirst, t1: tEnd }
    // E3 固定電量：回歸前先看是否全部相同
    var allSame = true
    for (i = 1; i < n; ++i) if (win[i].soc !== win[0].soc) allSame = false
    var slope = null, r2 = null, intercept = null
    if (n >= 2 && allSame && tEnd > tFirst) { slope = 0; r2 = null; intercept = win[0].soc; out.direction = "持平" }
    else if (n >= 2) {
        var xb = 0, sb = 0
        for (i = 0; i < n; ++i) { xb += win[i].t - tFirst; sb += win[i].soc }
        xb /= n; sb /= n
        var sxx = 0, sxy = 0, syy = 0
        for (i = 0; i < n; ++i) { var dx = win[i].t - tFirst - xb, dy = win[i].soc - sb; sxx += dx * dx; sxy += dx * dy; syy += dy * dy }
        if (sxx === 0) why("zero_time_variance")
        else {
            slope = sxy / sxx * 60; r2 = (sxy * sxy) / (sxx * syy); intercept = sb - (sxy / sxx) * xb
            if (r2 < P.R2_MIN) why("r2")
            else out.direction = slope < -(P.EPS + NUM_EPS) ? "下降" : (slope > P.EPS + NUM_EPS ? "上升" : "持平")
        }
    } else why("zero_time_variance")
    out.slope_pct_per_min = slope; out.r2 = r2
    var lastFact = fact("F2", "value", "soc", last.soc, "%", tEnd, more())
    var seriesFact = fact("F3", "series", "soc", null, "%", tEnd, { points: points })
    if (out.stale) { out.direction = null; return done("STALE", [fact("F1", "value", "soc", last.soc, "%", tEnd, more())], cov) }   // 過期不發布趨勢與 ETA
    if (out.insufficient_reasons.length) { out.direction = null; return done("INSUFFICIENT", [lastFact, seriesFact], cov) }
    // E4／§C' 第 3 點 ETA
    if (out.direction !== "下降") out.eta_reason = "not_falling"
    else if (!reserveValid) out.eta_reason = "reserve_invalid"
    else if (!(last.soc > reserve)) out.eta_reason = "at_or_below_reserve"
    else {
        var eta = (last.soc - reserve) / Math.abs(slope)
        if (eta <= P.ETA_MAX_MIN + NUM_EPS) { out.eta_min = eta; out.eta_reason = "" }
        else out.eta_reason = "over_limit"
    }
    var trend = fact("F1", "trend", "soc", slope, "%/min", tEnd, more({ slope: slope, direction: out.direction, window: windowLabel, r2: r2,
                     intercept: intercept, t_ref: tFirst, eta_min: out.eta_min, eta_reason: out.eta_reason }))
    return done("OK", [trend, lastFact, seriesFact], cov)
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
// 0.4（v3.1c L1～L4）：兩階段去重、內容詞規則 v1（詞表最長比對＋剩餘兩字詞）、先截前 50 再篩、低頻過濾保底。
// L5（兩路融合身分）要等向量路徑（B 包），M1 只有關鍵字一路。
var DOC_KEYWORD_TOP = 50
var QUERY_STOP = ["如何", "設定", "怎麼", "請問"]                // v3.1c L2 第 3 點
var CONTENT_LEXICON = ["返航", "保留", "電量", "電池", "電壓", "電流", "高度", "速度", "航向", "姿態", "衛星", "訊號", "遙測", "位置",
                       "距離", "溫度", "風速", "告警", "警告", "異常", "航線", "航點", "任務", "地圖", "報告", "紀錄", "日誌", "手冊", "參數",
                       "起飛", "降落", "懸停", "解鎖", "上鎖", "低電量", "失控", "保護", "校準", "馬達", "螺旋槳", "遙控器", "電子圍籬", "禁航區"]
var CONTENT_RULE_VERSION = "content-terms-v1"
function tokenize(text) {
    var s = String(text || "").toLowerCase(), out = [], m, re = /[a-z0-9_]+|[一-鿿]+/g
    while ((m = re.exec(s))) {
        var w = m[0]
        if (/^[a-z0-9_]+$/.test(w)) out.push(w)
        else if (w.length === 1) out.push(w)
        else for (var i = 0; i + 1 < w.length; ++i) out.push(w.substr(i, 2))   // 中文用相鄰兩字（排名用）
    }
    return out
}
// 內容詞規則 v1：領域詞表最長比對；沒被詞表蓋到的連續漢字才切兩字詞（單字保留）
function contentTerms(query) {
    var q = String(query || "").toLowerCase(), i
    for (i = 0; i < DOC_STOP.length; ++i) q = q.split(DOC_STOP[i]).join(" ")
    for (i = 0; i < QUERY_STOP.length; ++i) q = q.split(QUERY_STOP[i]).join(" ")
    var lex = CONTENT_LEXICON.slice().sort(function (a, b) { return b.length - a.length || CONTENT_LEXICON.indexOf(a) - CONTENT_LEXICON.indexOf(b) })
    var out = [], m, re = /[a-z0-9_]+|[一-鿿]+/g
    function push(t) { if (out.indexOf(t) < 0) out.push(t) }
    while ((m = re.exec(q))) {
        var w = m[0]
        if (/^[a-z0-9_]+$/.test(w)) { push(w); continue }
        var pos = 0, rest = ""
        function flush() { if (!rest) return; if (rest.length === 1) push(rest); else for (var k = 0; k + 1 < rest.length; ++k) push(rest.substr(k, 2)); rest = "" }
        while (pos < w.length) {
            var hit = ""
            for (var j = 0; j < lex.length && !hit; ++j) if (w.substr(pos, lex[j].length) === lex[j]) hit = lex[j]
            if (hit) { flush(); push(hit); pos += hit.length } else { rest += w.charAt(pos); pos++ }
        }
        flush()
    }
    return out
}
// glossary: {中文詞: [英文詞, ...]}；查詢含中文詞就補上英文詞（v3.1c L2：擴充詞只影響排名）
function expandQuery(query, glossary) {
    var extra = [], q = String(query || "")
    for (var zh in (glossary || {})) if (q.indexOf(zh) >= 0) extra = extra.concat(glossary[zh])
    return extra.length ? q + " " + extra.join(" ") : q
}
function chunkHas(chunkText, term) { return String(chunkText).toLowerCase().indexOf(term) >= 0 }
// chunks: [{chunk_id, doc, heading, version, text, text_sha256?}]
function manualSearch(chunks, query, glossary) {
    var inputs = { query: query, k: DOC_TOP_K, content_rule: CONTENT_RULE_VERSION }
    if (!chunks) return result("T_MANUAL_SEARCH", inputs, "UNAVAILABLE", [], null, { degraded: true })
    // L1 兩階段去重：先 chunk_id，再（doc, 文字雜湊或原文），都保留第一筆
    var byId = Object.create(null), stage1 = [], u
    for (u = 0; u < chunks.length; ++u) { var cid = String(chunks[u].chunk_id); if (byId[cid]) continue; byId[cid] = true; stage1.push(chunks[u]) }
    var byText = Object.create(null), uniq = []
    for (u = 0; u < stage1.length; ++u) {
        var ch = stage1[u], tk = String(ch.doc) + "\u0000" + (ch.text_sha256 ? "sha:" + ch.text_sha256 : "raw:" + String(ch.text))
        if (byText[tk]) continue
        byText[tk] = true; uniq.push(ch)
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
        docs.push({ chunk: chunks[i], tf: tf, len: toks.length, order: i }); avg += toks.length
    }
    avg = docs.length ? avg / docs.length : 0
    // 內容詞（規則 v1）與其 df（以片段原文是否含該詞計）
    var cterms = contentTerms(query), cdf = Object.create(null)
    for (j = 0; j < cterms.length; ++j) { cdf[cterms[j]] = 0; for (i = 0; i < docs.length; ++i) if (chunkHas(docs[i].chunk.text, cterms[j])) cdf[cterms[j]]++ }
    // 低頻過濾：去掉出現在超過 20% 片段的詞
    var content = []
    for (j = 0; j < cterms.length; ++j) if (!docs.length || cdf[cterms[j]] / docs.length <= DOC_QUALIFY.DF_MAX) content.push(cterms[j])
    var anyPresent = false
    for (j = 0; j < content.length; ++j) if (cdf[content[j]]) anyPresent = true
    if (!anyPresent) content = cterms.slice()                     // 退路（v3.1b §L'）
    // L4 保底：原本 ≥2 個內容詞時至少留 2 個（df 最低的兩個，同 df 依查詢順序）；任何情況至少 1 個
    var need = Math.min(cterms.length, cterms.length >= 2 ? 2 : 1)
    if (content.length < need) {
        var rank = cterms.slice().sort(function (a, b) { return cdf[a] - cdf[b] || cterms.indexOf(a) - cterms.indexOf(b) })
        content = []
        for (j = 0; j < cterms.length; ++j) if (rank.indexOf(cterms[j]) < need) content.push(cterms[j])
    }
    // 關鍵字排名
    var ranked = []
    for (i = 0; i < docs.length; ++i) {
        var score = 0
        for (j = 0; j < terms.length; ++j) {
            var f = docs[i].tf[terms[j]]
            if (!f) continue
            var idf = Math.log(1 + (docs.length - df[terms[j]] + 0.5) / (df[terms[j]] + 0.5))
            score += idf * f * (BM25.k1 + 1) / (f + BM25.k1 * (1 - BM25.b + BM25.b * (avg ? docs[i].len / avg : 0)))
        }
        if (score > 0) ranked.push({ d: docs[i], score: score })
    }
    ranked.sort(function (a, b) { return b.score - a.score || a.d.order - b.d.order })
    ranked = ranked.slice(0, DOC_KEYWORD_TOP)                     // L3 先截前 50
    var scored = []
    for (i = 0; i < ranked.length; ++i) {
        var hitN = 0
        for (j = 0; j < content.length; ++j) if (chunkHas(ranked[i].d.chunk.text, content[j])) hitN++
        var cover = content.length ? hitN / content.length : 0
        // 使用者 11/18 21:24「L4 加命中 2 個」：內容詞 ≥2 個時至少命中 2 個
        if (content.length && hitN >= Math.min(2, content.length) && cover >= DOC_QUALIFY.MIN_COVERAGE) scored.push({ chunk: ranked[i].d.chunk, score: ranked[i].score, cover: cover })
    }
    var facts = []
    for (i = 0; i < scored.length && i < DOC_TOP_K; ++i) {
        var c = scored[i].chunk
        facts.push(fact("F" + (i + 1), "doc_quote", "manual", c.text, "", null,
                        { chunk_id: c.chunk_id, doc: c.doc, heading: c.heading, doc_version: c.version, score: scored[i].score, content_coverage: scored[i].cover }))
    }
    if (!facts.length) return result("T_MANUAL_SEARCH", inputs, "EMPTY_COMPLETE", [fact("F1", "not_found", "manual", null, "", null)], null, { degraded: true, content_terms: content })
    return result("T_MANUAL_SEARCH", inputs, "OK", facts, null, { degraded: true, content_terms: content })
}

// ---------------------------------------------------------------- T_FLIGHTLOG DEVIATION（F2，說明 f2_deviation_v1 與使用者 11/21 03:08 裁決）
// waypoints: [{seq, lat, lon}]（任務原順序）；samples: [{t, lat, lon}]；只看水平距離。
// 原點＝第一個有效航點，平面近似（本案局部任務範圍）；無效航點照原順序斷段、前後不接；航段長度須嚴格 > 0.01 m；
// 跨 ±180 度經線 → INSUFFICIENT（reason antimeridian）；最大、平均用原始精度，顯示時才四捨五入（Claims.num）。
var DEV_R = 6371008.8, DEV_MIN_SEG = 0.01
function devValid(p) { return !!p && finite(p.lat) && finite(p.lon) && Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180 }
function devSegDist(px, py, a, b) {
    var dx = b.x - a.x, dy = b.y - a.y, L2 = dx * dx + dy * dy
    var u = ((px - a.x) * dx + (py - a.y) * dy) / L2
    if (u < 0) u = 0; else if (u > 1) u = 1
    var ex = a.x + u * dx - px, ey = a.y + u * dy - py
    return Math.sqrt(ex * ex + ey * ey)
}
function flightlogDeviation(waypoints, samples, t0, t1, gaps) {
    var inputs = { operation: "DEVIATION", t0: t0, t1: t1 }
    if (!samples || !waypoints) return result("T_FLIGHTLOG", inputs, "ERROR", [], null, { internal_status: "UNAVAILABLE" })
    var i, origin = null
    for (i = 0; i < waypoints.length; ++i) if (devValid(waypoints[i])) { origin = waypoints[i]; break }
    var coverage = { requested: [t0, t1], covered: null, gaps: gaps || [] }
    function insufficient(reason, extra) { var d = { reason: reason, insufficient_reasons: [reason] }; if (extra) for (var k in extra) d[k] = extra[k]
        return result("T_FLIGHTLOG", inputs, "INSUFFICIENT", [], coverage, { detail: d }) }
    if (!origin) return insufficient("no_segment", { valid_segments: 0, breaks: [] })
    var lat0 = origin.lat * Math.PI / 180, cos0 = Math.cos(lat0)
    function xy(p) { return { x: DEV_R * (p.lon - origin.lon) * Math.PI / 180 * cos0, y: DEV_R * (p.lat - origin.lat) * Math.PI / 180 } }
    var segs = [], breaks = [], lastValid = null, broken = false
    for (i = 0; i < waypoints.length; ++i) {
        var w = waypoints[i]
        if (!devValid(w)) { broken = true; continue }
        if (lastValid && Math.abs(w.lon - lastValid.lon) > 180) return insufficient("antimeridian", { at_seq: w.seq })
        if (lastValid && broken) breaks.push({ after_seq: lastValid.seq, before_seq: w.seq })
        if (lastValid && !broken) {
            var a = xy(lastValid), b = xy(w), len = Math.sqrt((b.x - a.x) * (b.x - a.x) + (b.y - a.y) * (b.y - a.y))
            if (len > DEV_MIN_SEG) segs.push({ a: a, b: b, idx: segs.length, from_seq: lastValid.seq, to_seq: w.seq })
        }
        lastValid = w; broken = false
    }
    if (!segs.length) return insufficient("no_segment", { valid_segments: 0, breaks: breaks })
    var pts = []
    for (i = 0; i < samples.length; ++i) {
        var s = samples[i]
        if (!s || !finite(s.t) || !devValid(s) || s.t < t0 || s.t > t1) continue
        if (Math.abs(s.lon - origin.lon) > 180) return insufficient("antimeridian", { at_t: s.t })
        pts.push({ t: s.t, lat: s.lat, lon: s.lon, arrival: i })
    }
    pts.sort(function (p, q) { return p.t - q.t || p.arrival - q.arrival })
    var detail = { valid_segments: segs.length, breaks: breaks, origin_seq: origin.seq }
    if (!pts.length) return result("T_FLIGHTLOG", inputs, coverage.gaps.length || breaks.length ? "PARTIAL" : "ERROR", [], coverage,
                                   coverage.gaps.length || breaks.length ? { detail: detail } : { internal_status: "EMPTY_COMPLETE", detail: detail })
    coverage.covered = [pts[0].t, pts[pts.length - 1].t]
    var dist = [], sum = 0, best = 0
    for (i = 0; i < pts.length; ++i) {
        var p = xy(pts[i]), dmin = Infinity, smin = -1
        for (var k = 0; k < segs.length; ++k) { var d = devSegDist(p.x, p.y, segs[k].a, segs[k].b); if (d < dmin) { dmin = d; smin = k } }   // 同距離取編號小的
        dist.push({ t: pts[i].t, value: dmin, arrival: pts[i].arrival, seg: smin }); sum += dmin
        if (dmin > dist[best].value) best = i
    }
    var series = []
    if (dist.length > SERIES_MAX_POINTS) {
        var tA = dist[0].t, width = (dist[dist.length - 1].t - tA) / SERIES_BUCKETS, bucket = []
        for (i = 0; i < SERIES_BUCKETS; ++i) bucket.push(null)
        for (i = 0; i < dist.length; ++i) {
            var bi = width > 0 ? Math.min(SERIES_BUCKETS - 1, Math.floor((dist[i].t - tA) / width)) : 0
            var bk = bucket[bi] || (bucket[bi] = { mn: i, mx: i })
            if (dist[i].value < dist[bk.mn].value) bk.mn = i
            if (dist[i].value > dist[bk.mx].value) bk.mx = i
        }
        for (i = 0; i < SERIES_BUCKETS; ++i) {
            if (!bucket[i]) continue
            var lo = Math.min(bucket[i].mn, bucket[i].mx), hi = Math.max(bucket[i].mn, bucket[i].mx)
            series.push({ t: dist[lo].t, value: dist[lo].value })
            if (hi !== lo) series.push({ t: dist[hi].t, value: dist[hi].value })
        }
    } else for (i = 0; i < dist.length; ++i) series.push({ t: dist[i].t, value: dist[i].value })
    var facts = [
        fact("F1", "series", "deviation", null, "公尺", dist[dist.length - 1].t, { points: series, downsampled: dist.length > SERIES_MAX_POINTS }),
        fact("F2", "value", "deviation.max", dist[best].value, "公尺", dist[best].t, { segment: segs[dist[best].seg].idx, show_time: true }),
        fact("F3", "value", "deviation.mean", sum / dist.length, "公尺", null)
    ]
    return result("T_FLIGHTLOG", inputs, coverage.gaps.length || breaks.length ? "PARTIAL" : "OK", facts, coverage, { detail: detail })
}
