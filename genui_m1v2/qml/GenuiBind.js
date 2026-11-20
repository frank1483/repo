.pragma library
// GenuiBind：預檢通過的節點 → 每個框的「畫面資料」（W1～W5 轉接元件說明 v1.2 §1、§2）。純函式，不讀即時狀態。
// 版本 bind-m1-0.1。QML 元件只顯示這裡給的資料；找不到就回 {ok:false}，該框畫「資料無法顯示」，不畫半份。
var BIND_VERSION = "bind-m1-0.4.1"   // 0.4.1：W4／W5 在 bound 還沒綁上時不讀 .cards／.citations（host01 run1 7 個 TypeError）。0.4： 0.4：使用者 11/20 16:40 D1（W4 改 GcpCard、長文換行、卡片增高）、D2（W1 安全提示→主要事實→常駐「未查」，矮畫面空間規則）；新增 contentMinH 給排版。0.3.1： 0.3.1：W2 右側標籤改用 labelTops 依實際高度避讓（real02 的 long 情境「目前」與「保留」重疊）。0.3： 0.3：只改 W 元件字級（通用級距）與 W2 標籤欄寬、W4 valueSize 固定 28（本檔邏輯不變）。0.2.2： 0.2.2：只改 W2 的「目前」標籤成兩行（本檔邏輯不變）。0.2.1： 0.2.1：橘色門檻改用顯示到小數一位後的值比較（0.2 run1 的 10 分鐘邊界顯示「10」卻是藍色）。0.2： 0.2：使用者 11/20 07:17 R1～R4 裁決（W4 橘色門檻與無法估計文字、W5 完整句、W1 引用出處優先、W2 數字標示）
var MAX_POINTS = 150
var ETA_WARN_MIN = 10                         // R1：ETA ≤ 10 分鐘用橘色〔顯示用候選值〕
var ETA_NA_LABEL = "電量下降，無法估計到保留電量的時間"
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

// T-DOC 行「「引文」（文件 › 章節，版本）」拆成引文與出處（R3）
function splitDocLine(t) {
    if (typeof t !== "string" || t.charAt(0) !== "「" || t.charAt(t.length - 1) !== "）") return null
    var k = t.lastIndexOf("」（")                      // 引文結尾＋出處開頭；章節名稱本身可以含括號
    return k > 0 ? { quote: t.slice(1, k), source: t.slice(k + 2, t.length - 1) } : null
}
// 依句子邊界切句（。！？；.!?），保留標點
function sentences(t) {
    var out = [], cur = "", cps = Array.from(t), i
    for (i = 0; i < cps.length; ++i) { cur += cps[i]; if ("。！？；.!?".indexOf(cps[i]) >= 0) { out.push(cur); cur = "" } }
    if (cur) out.push(cur)
    return out
}
// 在完整句邊界縮短：取最多能放進 maxChars 的前幾句；一句都放不下時回 {text:"", whole:false}（R2、R3）
function shortenAtSentence(t, maxChars) {
    var ss = sentences(t), acc = "", n = 0
    for (var i = 0; i < ss.length; ++i) { if (Array.from(acc + ss[i]).length > maxChars) break; acc += ss[i]; ++n }
    return { text: acc, whole: n === ss.length, sentences: n }
}

// D2：安全提示（資料過期、部分缺漏、樣本不足）；「本次未執行：…」在 W1 縮成「未查：…」（答案區與紀錄保留原句）
var SAFETY_TPL = ["T-STALE", "T-PARTIAL", "T-CANNOT"]
function shortOmitted(t) {
    var k = t.indexOf("："), e = t.indexOf("（")
    var names = k >= 0 ? t.slice(k + 1, e > k ? e : t.length) : t
    return "未查：" + names
}
// 估計文字寬度（像素）：中日韓與全形字算 1 個字級寬，其餘算 0.6；寧可估大，避免裁掉
function textWidth(t, px) {
    var w = 0, cps = Array.from(String(t))
    for (var i = 0; i < cps.length; ++i) { var c = cps[i].codePointAt(0); w += (c >= 0x2E80 || (c >= 0xFF00 && c <= 0xFFEF)) ? px : px * 0.6 }
    return w
}
function textLines(t, px, widthPx) { return Math.max(1, Math.ceil(textWidth(t, px) / Math.max(1, widthPx * 0.95))) }

function bindAnswer(answer) {
    if (!answer || !Array.isArray(answer.lines)) return bad("NO_ANSWER")
    var m = [], o = [], i
    for (i = 0; i < answer.lines.length; ++i) {
        var l = answer.lines[i]; if (typeof l.text !== "string") return bad("LINE_TYPE")
        var row = { text: l.text, mandatory: !!l.mandatory, kind: "text", tpl: l.template_id || "",
                    role: SAFETY_TPL.indexOf(l.template_id) >= 0 ? "safety" : (l.template_id === "T-OMITTED" ? "omitted" : (l.mandatory ? "mandatory_fact" : "fact")) }
        if (row.role === "omitted") row.short = shortOmitted(l.text)
        if (l.template_id === "T-DOC") { var d = splitDocLine(l.text); if (d) { row.kind = "doc"; row.quote = d.quote; row.source = d.source } }
        ;(l.mandatory ? m : o).push(row)
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
        if (eta) cards.push({ key: "eta", label: "到保留電量", value: num(tr.eta_min), unit: "分鐘", note: "",
                              accent: Number(num(tr.eta_min)) <= ETA_WARN_MIN ? ACCENT.warn : ACCENT.normal })
        else if (tr.direction === "下降") cards.push({ key: "eta", label: ETA_NA_LABEL, value: "—", unit: "", note: why, accent: ACCENT.warn })
        else cards.push({ key: "eta", label: "到保留電量", value: "—", unit: "", note: why, accent: ACCENT.normal })
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
// W1（R3）：每行高度不同（引用行最多 3 行）。mandatory 一定顯示；其餘依序放，放不下留一行給「還有 N 行」
function fitLinesH(heights, mandatory, availH, moreH) {
    var used = 0, shown = 0, i, n = heights.length
    for (i = 0; i < n; ++i) if (mandatory[i]) used += heights[i]
    var total = 0; for (i = 0; i < n; ++i) total += heights[i]
    if (total <= availH) return { shown: n, hidden: 0 }
    var budget = availH - moreH, acc = 0
    for (i = 0; i < n; ++i) {
        var need = mandatory[i] ? 0 : heights[i]
        if (!mandatory[i] && used + acc + need > budget) break
        acc += need; ++shown
    }
    for (var k = shown; k < n; ++k) if (mandatory[k]) ++shown  // mandatory 已排在最前，實務上不會走到
    return { shown: shown, hidden: n - shown }
}
// W2（R4）：縱軸最小、最大標籤；右側「目前／保留」標籤，兩者太近就改兩行並排在同一位置
function seriesLabels(d, h, labelH) {
    if (!d || !d.y || !d.points.length) return null
    var unit = d.unit === "%" ? "%" : (d.unit ? " " + d.unit : ""), last = d.points[d.points.length - 1].v
    var yOf = function (v) { return h - (v - d.y.min) / ((d.y.max - d.y.min) || 1) * h }
    var out = { min: num(d.y.min) + unit, max: num(d.y.max) + unit, current: { text: "目前 " + num(last) + unit, y: yOf(last) }, reserve: null, diff: "", stacked: false }
    if (d.reserve_pct !== null && d.reserve_pct !== undefined) {
        out.reserve = { text: "保留 " + num(d.reserve_pct) + unit, y: yOf(d.reserve_pct) }
        var gap = Math.round((last - d.reserve_pct) * 10) / 10
        out.diff = gap >= 0 ? "高於保留值 " + num(gap) + " 個百分點" : "低於保留值 " + num(-gap) + " 個百分點"
        if (Math.abs(out.current.y - out.reserve.y) < labelH) { out.stacked = true; out.reserve.y = out.current.y + labelH }
    }
    return out
}
// W2（0.3.1）：右側兩個標籤的實際上緣位置。先以數值位置置中、夾在畫布內；若重疊，數值高的在上、低的緊接在下；
// 下面那個超出畫布底時兩個一起往上推。hCur／hRes 是兩個標籤的實際高度（「目前」是兩行）。
function labelTops(lab, h, hCur, hRes) {
    if (!lab) return null
    function clamp(t, hh) { return Math.max(0, Math.min(h - hh, t)) }
    var cur = { top: clamp(lab.current.y - hCur / 2, hCur), h: hCur, v: -lab.current.y }
    if (!lab.reserve) return { current: cur.top, reserve: null }
    var res = { top: clamp(lab.reserve.y - hRes / 2, hRes), h: hRes, v: -lab.reserve.y }
    var up = cur.v >= res.v ? cur : res, dn = up === cur ? res : cur   // 數值高（y 小）的在上
    if (dn.top < up.top + up.h) {
        dn.top = up.top + up.h
        if (dn.top + dn.h > h) { var shift = dn.top + dn.h - h; dn.top -= shift; up.top = Math.max(0, up.top - shift) }
    }
    return { current: cur.top, reserve: res.top }
}
// ---- D2：W1 排列（W1 元件與排版共用同一套量法）
// 版面量法（與 GenuiW1Fact.qml 一致）：外框 GcpPanel 內縮 8、GcpCard 內縮 8＋上下各 8 → 可用高 = H − 32；可用寬 = W − 56
var W1M = { px: 22, smallPx: 18, lineH: 33, padH: 32, padW: 56, maxTextLines: 3, maxQuoteLines: 2 }
function w1RowHeight(r, availW) {
    if (r.kind === "doc") {
        var q = shortenAtSentence(r.quote, Math.max(1, Math.floor(availW / W1M.px)) * W1M.maxQuoteLines)
        var qt = q.sentences > 0 ? "「" + q.text + (q.whole ? "」" : "…」") : ""
        var ql = qt ? Math.min(W1M.maxQuoteLines, textLines(qt, W1M.px, availW)) : 0
        return { h: W1M.lineH * (1 + ql), quote: qt, qLines: ql, lines: 1 }
    }
    var txt = r.role === "omitted" ? r.short : r.text
    var n = Math.min(W1M.maxTextLines, textLines(txt, W1M.px, availW))
    return { h: W1M.lineH * n, lines: n, text: txt }
}
// 必顯示：安全提示（依原順序）→ 主要事實（第一條事實；沒有就第一條必顯示事實）→ 其他必顯示事實 → … → 「未查」（最後）
// 其餘事實是補充，放不下就收起並顯示「還有 N 行」
function w1Arrange(lines, availH, availW) {
    var safety = [], mfacts = [], facts = [], omitted = [], i
    for (i = 0; i < lines.length; ++i) {
        var r = lines[i]; var m = w1RowHeight(r, availW)
        var row = { src: r, h: m.h, lines: m.lines, text: m.text, quote: m.quote, qLines: m.qLines, kind: r.kind, role: r.role, source: r.source }
        if (r.role === "safety") safety.push(row); else if (r.role === "omitted") omitted.push(row)
        else if (r.role === "mandatory_fact") mfacts.push(row); else facts.push(row)
    }
    var main = facts.length ? [facts.shift()] : []
    var always = safety.concat(main, mfacts), tail = omitted, opt = facts
    var used = 0
    for (i = 0; i < always.length; ++i) used += always[i].h
    for (i = 0; i < tail.length; ++i) used += tail[i].h
    var shownOpt = [], left = availH - used
    for (i = 0; i < opt.length; ++i) {
        var restAfter = opt.length - i - 1, need = opt[i].h + (restAfter > 0 ? W1M.lineH : 0)
        if (need <= left) { shownOpt.push(opt[i]); left -= opt[i].h } else break
    }
    var hidden = opt.length - shownOpt.length
    return { rows: always.concat(shownOpt), tail: tail, hidden: hidden, required_h: used + (opt.length ? W1M.lineH : 0) }
}
function w1MinH(lines, widthPx) {
    var a = w1Arrange(lines, 0, widthPx - W1M.padW)
    return W1M.padH + a.required_h
}
// ---- D1：W4 卡片量法（與 GenuiW4Diag.qml 一致）：外框內縮 8、卡片間距 8；卡片內距 12；圓點 14＋間距 6
var W4M = { labelPx: 18, labelLineH: 27, valuePx: 28, valueLineH: 40, unitPx: 18, padOuter: 8, gap: 8, padCard: 12, dot: 20 }
function w4CardLayout(cards, widthPx) {
    var n = Math.max(1, cards.length), cardW = (widthPx - 2 * W4M.padOuter - W4M.gap * (n - 1)) / n
    var labelW = cardW - 2 * W4M.padCard - W4M.dot, out = [], maxH = 0
    for (var i = 0; i < cards.length; ++i) {
        var ll = textLines(cards[i].label, W4M.labelPx, labelW)
        var vw = textWidth(cards[i].value, W4M.valuePx) + 6 + textWidth(cards[i].unit, W4M.unitPx)
        var vl = vw > cardW - 2 * W4M.padCard ? 2 : 1                                   // 數值＋單位放不下一行時單位換到下一行
        var h = W4M.padCard + ll * W4M.labelLineH + W4M.valueLineH + (vl - 1) * W4M.labelLineH + W4M.padCard
        out.push({ labelLines: ll, valueLines: vl, h: h }); if (h > maxH) maxH = h
    }
    return { cardW: cardW, cards: out, minH: 2 * W4M.padOuter + maxH }
}
// 給排版用：依內容算這個框在指定寬度下至少要多高（0 表示用目錄的最小高度）
function contentMinH(node, toolResults, answer, widthPx) {
    if (!node) return 0
    if (node.component_id === "W1_FACT") { var a = bindAnswer(answer); return a.ok ? w1MinH(a.data.lines, widthPx) : 0 }
    if (node.component_id === "W4_DIAG") { var d = bindDiag(toolResults, node.binding_ref.ref); return d.ok ? w4CardLayout(d.data.cards, widthPx).minH : 0 }
    return 0
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
