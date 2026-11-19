.pragma library
// GenuiBind：預檢通過的節點 → 每個框的「畫面資料」（W1～W5 轉接元件說明 v1.2 §1、§2）。純函式，不讀即時狀態。
// 版本 bind-m1-0.1。QML 元件只顯示這裡給的資料；找不到就回 {ok:false}，該框畫「資料無法顯示」，不畫半份。
var BIND_VERSION = "bind-m1-0.1.1"   // 0.1.1：只改 GenuiWidget.qml 的路徑解析，本檔邏輯不變
var MAX_POINTS = 150
var ACCENT = { normal_soc: "telemetryMetricGreen", normal: "telemetryMetricBlue", warn: "telemetryMetricOrange" }
// 與 GenuiClaims 相同的數字格式與 ETA 原因句（說明 §1：答案和卡片顯示同一個數字）
function num(x) { var r = Math.round(x * 10) / 10; return String(r === 0 ? 0 : r) }
var ETA_NA_REASON = { reserve_invalid: "保留電量設定無效", at_or_below_reserve: "目前電量已不高於保留電量", over_limit: "照目前趨勢超過 600 分鐘",
                      no_trend: "沒有有效的趨勢", not_falling: "電量沒有在下降" }

function bad(code) { return { ok: false, error: code, data: null } }
function findFact(toolResults, ref) {
    if (typeof ref !== "string") return null
    var k = ref.indexOf(":"); if (k < 1) return null
    var ti = Number(ref.slice(0, k)), fid = ref.slice(k + 1)
    if (!(ti >= 0 && ti < toolResults.length && Math.floor(ti) === ti)) return null
    var fs = toolResults[ti].facts || []
    for (var i = 0; i < fs.length; ++i) if (fs[i].fact_id === fid) return { tool_index: ti, fact: fs[i] }
    return null
}
function finite(x) { return typeof x === "number" && isFinite(x) }

// 縱軸範圍：min～max 加 5% 邊距；全部同值時上下各留 1 個單位；有保留電量線時把它也包進來
function axisRange(values, extra) {
    var lo = Infinity, hi = -Infinity, i
    for (i = 0; i < values.length; ++i) { if (values[i] < lo) lo = values[i]; if (values[i] > hi) hi = values[i] }
    if (finite(extra)) { if (extra < lo) lo = extra; if (extra > hi) hi = extra }
    if (!(lo <= hi)) return null
    if (lo === hi) return { min: lo - 1, max: hi + 1 }
    var pad = (hi - lo) * 0.05
    return { min: lo - pad, max: hi + pad }
}

function bindAnswer(answer) {
    if (!answer || !Array.isArray(answer.lines)) return bad("NO_ANSWER")
    var m = [], o = [], i
    for (i = 0; i < answer.lines.length; ++i) {
        var l = answer.lines[i]; if (typeof l.text !== "string") return bad("LINE_TYPE")
        ;(l.mandatory ? m : o).push({ text: l.text, mandatory: !!l.mandatory })
    }
    return { ok: true, error: "", data: { lines: m.concat(o) } }
}

function bindSeries(toolResults, ref) {
    var hit = findFact(toolResults, ref)
    if (!hit || hit.fact.kind !== "series" || !Array.isArray(hit.fact.points)) return bad("BINDING_NOT_FOUND")
    var r = toolResults[hit.tool_index], isEnergy = r.tool === "T_ENERGY", pts = [], vals = [], i
    if (hit.fact.points.length > MAX_POINTS) return bad("SERIES_TOO_LONG")
    for (i = 0; i < hit.fact.points.length; ++i) {
        var p = hit.fact.points[i], v = isEnergy ? p.soc : p.value
        if (!finite(p.t) || !finite(v)) return bad("POINT_TYPE")
        pts.push({ t: p.t, v: v }); vals.push(v)
    }
    var reserve = null
    if (isEnergy) for (i = 0; i < r.facts.length; ++i) if (r.facts[i].kind === "trend" && r.facts[i].reserve_valid && finite(r.facts[i].reserve_pct)) reserve = r.facts[i].reserve_pct
    var req = r.coverage && r.coverage.requested
    var t0 = req ? req[0] : (pts.length ? pts[0].t : 0), t1 = req ? req[1] : (pts.length ? pts[pts.length - 1].t : 1)
    return { ok: true, error: "", data: { subject: hit.fact.subject, unit: hit.fact.unit || "", points: pts, t0: t0, t1: t1,
             gaps: (r.coverage && r.coverage.gaps) || [], reserve_pct: reserve, y: pts.length ? axisRange(vals, reserve) : null } }
}

function bindEvents(toolResults, ref) {
    var hit = findFact(toolResults, ref)
    if (!hit || !Array.isArray(hit.fact.rows) || toolResults[hit.tool_index].tool !== "T_ALERT_HISTORY") return bad("BINDING_NOT_FOUND")
    var rows = hit.fact.rows.map(function (e) {
        return { t: e.t, level: e.level, predictor: e.predictor, text: e.text,
                 tone: e.level === "critical" ? "statusCritical" : (e.level === "warning" ? "statusWarning" : "textPrimary") } })
    return { ok: true, error: "", data: { rows: rows, has_critical: !!hit.fact.has_critical } }
}

// W4：只用 binding 列出的電量 Fact；value → 目前電量卡；trend → 斜率卡＋ETA 卡。最多 3 張。
function bindDiag(toolResults, refs) {
    if (!Array.isArray(refs) || refs.length < 1 || refs.length > 2) return bad("BINDING_NOT_FOUND")
    var cards = [], i, val = null, tr = null
    for (i = 0; i < refs.length; ++i) {
        var hit = findFact(toolResults, refs[i])
        if (!hit || toolResults[hit.tool_index].tool !== "T_ENERGY") return bad("BINDING_NOT_FOUND")
        if (hit.fact.kind === "value") val = hit.fact; else if (hit.fact.kind === "trend") tr = hit.fact; else return bad("FACT_KIND")
    }
    var res = (tr || val)
    var belowReserve = !!(val && res.reserve_valid && finite(res.reserve_pct) && finite(val.value) && val.value <= res.reserve_pct)
    if (val) cards.push({ key: "soc", label: "目前電量", value: finite(val.value) ? num(val.value) : "—", unit: "%",
                          accent: belowReserve ? ACCENT.warn : ACCENT.normal_soc })
    if (tr) {
        cards.push({ key: "slope", label: "電量變化", value: finite(tr.slope) ? num(tr.slope) : "—", unit: "%/min", accent: ACCENT.normal })
        var eta = finite(tr.eta_min) && !tr.eta_reason, why = ETA_NA_REASON[tr.eta_reason] || ""
        var warn = tr.direction === "下降" && !eta
        cards.push({ key: "eta", label: "到保留電量", value: eta ? num(tr.eta_min) : "無法估計", unit: eta ? "分鐘" : (why ? "（" + why + "）" : ""),
                     accent: warn ? ACCENT.warn : ACCENT.normal })
    }
    return { ok: true, error: "", data: { cards: cards } }
}

function bindCitations(toolResults, refs) {
    if (!Array.isArray(refs) || refs.length < 1 || refs.length > 5) return bad("BINDING_NOT_FOUND")
    var out = [], i, t, q
    for (i = 0; i < refs.length; ++i) {
        var f = null
        for (t = 0; t < toolResults.length && !f; ++t) { var fs = toolResults[t].facts || []; for (q = 0; q < fs.length; ++q) if (fs[q].kind === "doc_quote" && fs[q].chunk_id === refs[i]) { f = fs[q]; break } }
        if (!f) return bad("BINDING_NOT_FOUND")
        out.push({ chunk_id: f.chunk_id, doc: f.doc, heading: f.heading, doc_version: f.doc_version, text: f.value })
    }
    return { ok: true, error: "", data: { citations: out } }
}

// node：plan 裡的節點（已過 validatePlan）；answer：trusted.answer
function resolve(node, toolResults, answer) {
    if (!node || !node.binding_ref || !Array.isArray(toolResults)) return bad("NO_NODE")
    var b = node.binding_ref, r
    switch (node.component_id) {
    case "W1_FACT": r = bindAnswer(answer); break
    case "W2_SERIES": r = bindSeries(toolResults, b.ref); break
    case "W3_TABLE": r = bindEvents(toolResults, b.ref); break
    case "W4_DIAG": r = bindDiag(toolResults, b.ref); break
    case "W5_DOC": r = bindCitations(toolResults, b.ref); break
    default: return bad("UNKNOWN_COMPONENT")
    }
    r.component_id = node.component_id; r.node_id = node.node_id
    return r
}

// ---- 放不下時怎麼收（說明 §2）：都只決定「顯示幾個」，不截斷句子中間
// W1：mandatory 行一定顯示；其餘從最後一行開始收；收掉的行數 > 0 時要多佔一行顯示「還有 N 行」
function fitLines(lines, availH, lineH) {
    var cap = Math.max(0, Math.floor(availH / lineH)), m = 0, i
    for (i = 0; i < lines.length; ++i) if (lines[i].mandatory) ++m
    if (lines.length <= cap) return { shown: lines.length, hidden: 0 }
    var room = Math.max(m, cap - 1)          // 留一行給「還有 N 行」
    var shown = Math.min(lines.length, room)
    return { shown: shown, hidden: lines.length - shown }
}
// W3／W5：依序顯示能放的個數，放不下的顯示「還有 N 筆／段」（Q1：不捲動）
function fitCount(n, availH, itemH) {
    var cap = Math.max(0, Math.floor(availH / itemH))
    if (n <= cap) return { shown: n, hidden: 0 }
    var shown = Math.max(0, cap - 1)
    return { shown: shown, hidden: n - shown }
}
// W2：資料點 → 框內像素座標（缺口處斷線：回傳多段折線）
function seriesPaths(d, w, h) {
    if (!d || !d.points.length || !d.y || !(w > 0) || !(h > 0)) return []
    var span = d.t1 - d.t0 || 1, ys = d.y.max - d.y.min || 1, segs = [], cur = [], i, j
    function inGap(a, b) { for (j = 0; j < d.gaps.length; ++j) { var g = d.gaps[j]; if (a < g[1] && b > g[0]) return true } return false }
    for (i = 0; i < d.points.length; ++i) {
        var p = d.points[i]
        if (i > 0 && inGap(d.points[i - 1].t, p.t)) { if (cur.length) segs.push(cur); cur = [] }
        cur.push({ x: (p.t - d.t0) / span * w, y: h - (p.v - d.y.min) / ys * h })
    }
    if (cur.length) segs.push(cur)
    return segs
}
