.pragma library
// GenUI M1 規則版：UiPlanner（選元件）、LayoutEngine（逐列貪婪排版）、預檢 Validator。
// 版本 m1v2：依 v3.1 草案 §K-2'、K-2''、K-4' 修改 binding 與驗證；舊版 genui_m1/ 不動。
// 依據：M1 演算法說明 v2 §5～7、候選 ADR §4（H-24 逐列貪婪）、G-02（新增元件要按「套用」）。
// 模型永遠不產生座標；LayoutSchema 只由 layout() 產生。尺寸數值都是候選值〔待凍結〕。

var LAYOUT_VERSION = "layout-m1-0.2"
var CATALOG_ID = "catalog-m1-0.2"
var GRID_COLS = 12, GAP = 16, UNIT = 8
var MAX_INSTANCES = 5
var SIZE_CLASS_COLS = { S: 3, M: 6, L: 12 }
// min_cols：最小欄數；min_h／pref_h：最小與建議高度（像素，UNIT 的倍數）
var CATALOG = {
    W1_FACT:   { min_cols: 6, min_h: 96,  pref_h: 160, size_class: "M", priority: 100 },
    W2_SERIES: { min_cols: 6, min_h: 160, pref_h: 240, size_class: "M", priority: 70 },
    W3_TABLE:  { min_cols: 6, min_h: 128, pref_h: 240, size_class: "L", priority: 60 },
    W4_DIAG:   { min_cols: 3, min_h: 80,  pref_h: 96,  size_class: "S", priority: 80 },
    W5_DOC:    { min_cols: 4, min_h: 96,  pref_h: 160, size_class: "M", priority: 50 }
}
var PRIORITY_CRITICAL_TABLE = 90
var PLAN_KEYS = ["schema", "request_id", "catalog_id", "nodes", "order"]
var NODE_KEYS = ["node_id", "component_id", "binding_ref", "priority", "size_class", "required"]

function finite(x) { return typeof x === "number" && isFinite(x) }
function own(o, k) { return o !== null && typeof o === "object" && Object.prototype.hasOwnProperty.call(o, k) }
var BINDING_KIND = { W1_FACT: "answer", W2_SERIES: "series", W3_TABLE: "events", W4_DIAG: "facts", W5_DOC: "citations" }
var BINDING_KEYS = ["request_id", "kind", "ref"]
function qid(ti, fid) { return ti + ":" + fid }
// 依 "工具序號:fact_id" 找 fact
function findFact(toolResults, ref) {
    if (typeof ref !== "string") return null
    var c = ref.indexOf(":"), ti = Number(ref.slice(0, c)), fid = ref.slice(c + 1)
    if (c <= 0 || !(ti >= 0) || Math.floor(ti) !== ti || !toolResults || ti >= toolResults.length) return null
    var fs = toolResults[ti].facts || []
    for (var i = 0; i < fs.length; ++i) if (fs[i].fact_id === fid) return { fact: fs[i], tool_index: ti }
    return null
}

// ---------------------------------------------------------------- UiPlanner（規則版）
// answer: GenuiClaims.answer() 的結果；toolResults: 同一次請求的 ToolResult 陣列
function plan(requestId, answer, toolResults) {
    var nodes = [], byComp = {}
    function add(component, kind, ref, priority, required) {
        if (byComp[component]) return byComp[component]
        var n = { node_id: "", component_id: component, binding_ref: { request_id: requestId, kind: kind, ref: ref }, priority: priority,
                  size_class: CATALOG[component].size_class, required: !!required }
        byComp[component] = n; nodes.push(n); return n
    }
    add("W1_FACT", "answer", requestId + ":answer", CATALOG.W1_FACT.priority, true)   // 固定答案區，一定在、排第一
    var lines = (answer && answer.lines) || [], ev = {}, i, j
    for (i = 0; i < ((answer && answer.evidence) || []).length; ++i) ev[answer.evidence[i].id] = answer.evidence[i]
    function seriesOf(ti) { var fs = toolResults[ti].facts; for (var k = 0; k < fs.length; ++k) if (fs[k].kind === "series" && fs[k].points) return fs[k]; return null }
    for (i = 0; i < lines.length; ++i) {
        var tpl = lines[i].template_id, e = ev[lines[i].evidence_ids[0]]
        if (!e) continue
        var ti = e.tool_index, r = toolResults[ti]
        if (tpl === "T-TREND" || (tpl === "T-VALUE" && r.tool === "T_FLIGHTLOG")) {
            var sf = seriesOf(ti)                                    // W2 綁可畫的序列（C-09）
            if (sf) add("W2_SERIES", "series", qid(ti, sf.fact_id), CATALOG.W2_SERIES.priority, false)
        } else if (tpl === "T-THRESH" || tpl === "T-ETA") {
            var n4 = byComp.W4_DIAG
            if (!n4) add("W4_DIAG", "facts", [qid(ti, e.fact_id)], CATALOG.W4_DIAG.priority, false)
            else if (n4.binding_ref.ref.length < 2 && n4.binding_ref.ref[0].split(":")[0] === String(ti) && n4.binding_ref.ref.indexOf(qid(ti, e.fact_id)) < 0)
                n4.binding_ref.ref.push(qid(ti, e.fact_id))
        } else if (tpl === "T-COUNT") {
            var rows = null
            for (j = 0; j < r.facts.length; ++j) if (r.facts[j].rows) rows = r.facts[j]
            if (rows) add("W3_TABLE", "events", qid(ti, rows.fact_id), rows.has_critical ? PRIORITY_CRITICAL_TABLE : CATALOG.W3_TABLE.priority, !!rows.has_critical)
        } else if (tpl === "T-DOC") {
            var n5 = byComp.W5_DOC, cid = r.facts.filter(function (f) { return f.fact_id === e.fact_id })[0].chunk_id
            if (!n5) add("W5_DOC", "citations", [cid], CATALOG.W5_DOC.priority, false)
            else if (n5.binding_ref.ref.indexOf(cid) < 0 && n5.binding_ref.ref.length < 5) n5.binding_ref.ref.push(cid)
        }
    }
    // 上限 5 個：從可省略、分數最低的開始拿掉（同分拿掉後面的）
    while (nodes.length > MAX_INSTANCES) {
        var drop = -1
        for (i = 0; i < nodes.length; ++i) if (!nodes[i].required && (drop < 0 || nodes[i].priority <= nodes[drop].priority)) drop = i
        if (drop < 0) break
        nodes.splice(drop, 1)
    }
    var order = []
    for (i = 0; i < nodes.length; ++i) { nodes[i].node_id = "n" + (i + 1); order.push(nodes[i].node_id) }
    return { schema: "UiPlan/1", request_id: requestId, catalog_id: CATALOG_ID, nodes: nodes, order: order }
}
// 這份計畫要不要按「套用」：只有固定的 W1 就不用；有任何其他元件就要（G-02）
function needsConfirm(uiPlan) { return uiPlan.nodes.length > 1 }

// ---------------------------------------------------------------- 預檢（排版前）
// toolResults 必填：binding 要能在本請求的資料裡找到，priority／required 依資料重算後比對（v3.1 §K-2''）
function validatePlan(p, toolResults) {
    function bad(code, id) { return { ok: false, error: code, node_id: id || "" } }
    if (!p || typeof p !== "object" || Array.isArray(p)) return bad("PLAN_TYPE")
    if (!Array.isArray(toolResults)) return bad("NO_DATA")
    var k
    for (k in p) if (own(p, k) && PLAN_KEYS.indexOf(k) < 0) return bad("PLAN_UNKNOWN_FIELD")
    if (p.schema !== "UiPlan/1") return bad("PLAN_SCHEMA")
    if (p.catalog_id !== CATALOG_ID) return bad("CATALOG_VERSION")
    if (typeof p.request_id !== "string" || !p.request_id) return bad("REQUEST_ID")
    if (!Array.isArray(p.nodes) || !Array.isArray(p.order)) return bad("NODES_TYPE")
    if (!p.nodes.length || p.nodes.length > MAX_INSTANCES) return bad("NODE_COUNT")
    var ids = Object.create(null), comps = Object.create(null)
    for (var i = 0; i < p.nodes.length; ++i) {
        var n = p.nodes[i]
        if (!n || typeof n !== "object" || Array.isArray(n)) return bad("NODE_TYPE")
        for (k in n) if (own(n, k) && NODE_KEYS.indexOf(k) < 0) return bad("NODE_UNKNOWN_FIELD", n.node_id)   // x、y、w、h 在這裡被擋掉
        if (n.node_id !== "n" + (i + 1)) return bad("NODE_ID", n.node_id)                                      // 由程式依序給
        ids[n.node_id] = true
        if (typeof n.component_id !== "string" || !own(CATALOG, n.component_id)) return bad("NOT_IN_CATALOG", n.node_id)
        if (comps[n.component_id]) return bad("DUPLICATE_COMPONENT", n.node_id)
        comps[n.component_id] = true
        if (typeof n.size_class !== "string" || !own(SIZE_CLASS_COLS, n.size_class)) return bad("SIZE_CLASS", n.node_id)
        if (!finite(n.priority)) return bad("PRIORITY", n.node_id)
        if (typeof n.required !== "boolean") return bad("REQUIRED_TYPE", n.node_id)
        var b = n.binding_ref
        if (!b || typeof b !== "object" || Array.isArray(b)) return bad("BINDING_INVALID", n.node_id)
        for (k in b) if (own(b, k) && BINDING_KEYS.indexOf(k) < 0) return bad("BINDING_INVALID", n.node_id)
        if (b.request_id !== p.request_id) return bad("BINDING_FOREIGN", n.node_id)
        if (b.kind !== BINDING_KIND[n.component_id]) return bad("BINDING_INVALID", n.node_id)
        // 依資料重算 priority 與 required
        var wantP = CATALOG[n.component_id].priority, wantR = n.component_id === "W1_FACT", hit, m
        if (n.component_id === "W1_FACT") { if (b.ref !== p.request_id + ":answer") return bad("BINDING_INVALID", n.node_id) }
        else if (n.component_id === "W2_SERIES") {
            hit = findFact(toolResults, b.ref)
            if (!hit || hit.fact.kind !== "series" || !Array.isArray(hit.fact.points)) return bad("BINDING_INVALID", n.node_id)
        } else if (n.component_id === "W3_TABLE") {
            hit = findFact(toolResults, b.ref)
            if (!hit || !Array.isArray(hit.fact.rows)) return bad("BINDING_INVALID", n.node_id)
            if (hit.fact.has_critical) { wantP = PRIORITY_CRITICAL_TABLE; wantR = true }
        } else if (n.component_id === "W4_DIAG") {
            if (!Array.isArray(b.ref) || b.ref.length < 1 || b.ref.length > 2) return bad("BINDING_INVALID", n.node_id)
            var tool0 = -1
            for (m = 0; m < b.ref.length; ++m) {
                hit = findFact(toolResults, b.ref[m])
                if (!hit || (hit.fact.kind !== "value" && hit.fact.kind !== "trend")) return bad("BINDING_INVALID", n.node_id)
                if (tool0 >= 0 && hit.tool_index !== tool0) return bad("BINDING_INVALID", n.node_id)
                tool0 = hit.tool_index
            }
        } else if (n.component_id === "W5_DOC") {
            if (!Array.isArray(b.ref) || b.ref.length < 1 || b.ref.length > 5) return bad("BINDING_INVALID", n.node_id)
            for (m = 0; m < b.ref.length; ++m) {
                var found = false
                for (var t = 0; t < toolResults.length && !found; ++t) {
                    var fs = toolResults[t].facts || []
                    for (var q = 0; q < fs.length; ++q) if (fs[q].kind === "doc_quote" && fs[q].chunk_id === b.ref[m]) found = true
                }
                if (!found) return bad("BINDING_INVALID", n.node_id)
            }
        }
        if (n.priority !== wantP || n.required !== wantR) return bad("PLAN_TAMPERED", n.node_id)
    }
    if (p.nodes[0].component_id !== "W1_FACT") return bad("W1_MISSING")
    if (p.order.length !== p.nodes.length) return bad("ORDER_LENGTH")
    var seen = Object.create(null)
    for (i = 0; i < p.order.length; ++i) {
        if (typeof p.order[i] !== "string" || !ids[p.order[i]] || seen[p.order[i]]) return bad("ORDER_MISMATCH")
        seen[p.order[i]] = true
    }
    return { ok: true, error: "", node_id: "" }
}

// ---------------------------------------------------------------- LayoutEngine（逐列貪婪）
// viewport: {width, height, revision}（Qt 實際回報的工作區內容區，像素）
// 回傳 {ok, error, layout:{schema, request_id, viewport_revision, col_width, rects[], rows, dropped[], compact}}
function layout(p, viewport, toolResults) {
    var v = validatePlan(p, toolResults)
    if (!v.ok) return { ok: false, error: v.error, layout: null }
    if (!viewport || !finite(viewport.width) || !finite(viewport.height) || viewport.width <= 0 || viewport.height <= 0)
        return { ok: false, error: "VIEWPORT", layout: null }
    var colW = Math.floor((viewport.width - (GRID_COLS - 1) * GAP) / GRID_COLS)
    if (colW < 1) return { ok: false, error: "VIEWPORT_TOO_NARROW", layout: null }
    var orderIdx = {}, i
    for (i = 0; i < p.order.length; ++i) orderIdx[p.order[i]] = i
    // 排序：W1 第一；必要的在前；再依分數高到低、order 索引、node_id
    var nodes = p.nodes.slice()
    nodes.sort(function (a, b) {
        var aw = a.component_id === "W1_FACT" ? 0 : 1, bw = b.component_id === "W1_FACT" ? 0 : 1
        return aw - bw || (a.required === b.required ? 0 : (a.required ? -1 : 1)) || b.priority - a.priority
            || orderIdx[a.node_id] - orderIdx[b.node_id] || (a.node_id < b.node_id ? -1 : a.node_id > b.node_id ? 1 : 0)
    })
    var dropped = []
    while (true) {
        // 分列：先試建議寬度，放不下試最小寬度，再放不下換列
        var rows = [], row = null
        for (i = 0; i < nodes.length; ++i) {
            var c = CATALOG[nodes[i].component_id], pref = Math.min(GRID_COLS, Math.max(SIZE_CLASS_COLS[nodes[i].size_class], c.min_cols))
            if (row && row.used + pref <= GRID_COLS) { row.items.push({ node: nodes[i], cols: pref }); row.used += pref }
            else if (row && row.used + c.min_cols <= GRID_COLS) { row.items.push({ node: nodes[i], cols: c.min_cols }); row.used += c.min_cols }
            else { row = { items: [{ node: nodes[i], cols: pref }], used: pref }; rows.push(row) }
        }
        // 每列剩下的欄數全給該列第一個（最重要的）元件
        for (i = 0; i < rows.length; ++i) { rows[i].items[0].cols += GRID_COLS - rows[i].used; rows[i].used = GRID_COLS }
        // 高度：先用建議高度，超出就改用最小高度
        var modes = ["pref_h", "min_h"], fit = null
        for (var m = 0; m < modes.length && !fit; ++m) {
            var total = 0, heights = []
            for (i = 0; i < rows.length; ++i) {
                var h = 0
                for (var j = 0; j < rows[i].items.length; ++j) h = Math.max(h, CATALOG[rows[i].items[j].node.component_id][modes[m]])
                heights.push(h); total += h
            }
            total += GAP * (rows.length - 1)
            if (total <= viewport.height) fit = { heights: heights, compact: modes[m] === "min_h", total: total }
        }
        if (fit) {
            var rects = [], y = 0
            for (i = 0; i < rows.length; ++i) {
                var col = 0
                for (j = 0; j < rows[i].items.length; ++j) {
                    var it = rows[i].items[j]
                    rects.push({ node_id: it.node.node_id, x: col * (colW + GAP), y: y, width: it.cols * colW + (it.cols - 1) * GAP, height: fit.heights[i],
                                 row: i, col: col, cols: it.cols })
                    col += it.cols
                }
                y += fit.heights[i] + GAP
            }
            return { ok: true, error: "", layout: { schema: "LayoutSchema/1", request_id: p.request_id, viewport_revision: viewport.revision === undefined ? null : viewport.revision,
                                                    col_width: colW, rects: rects, rows: rows.length, dropped: dropped, compact: fit.compact, total_height: fit.total } }
        }
        // 放不下：拿掉可省略、分數最低的（同分拿 order 最後的、再比 node_id 最大的），重排
        var drop = -1
        for (i = 0; i < nodes.length; ++i) {
            if (nodes[i].required) continue
            if (drop < 0) { drop = i; continue }
            var a = nodes[i], b = nodes[drop]
            if (a.priority < b.priority || (a.priority === b.priority && (orderIdx[a.node_id] > orderIdx[b.node_id]
                || (orderIdx[a.node_id] === orderIdx[b.node_id] && a.node_id > b.node_id)))) drop = i
        }
        if (drop < 0) return { ok: false, error: "REQUIRED_OVERFLOW", layout: null }
        dropped.push(nodes[drop].node_id)
        nodes.splice(drop, 1)
    }
}

// ---------------------------------------------------------------- 預檢（排版後、上畫面前的幾何檢查）
// alertRect: 告警區在同一座標系的矩形（可省略）。標示、截字、遮蔽要等實際畫面，不在這裡檢查。
function validateLayout(p, lay, viewport, alertRect) {
    function bad(code, id) { return { ok: false, error: code, node_id: id || "" } }
    if (!lay || lay.schema !== "LayoutSchema/1" || !Array.isArray(lay.rects)) return bad("LAYOUT_TYPE")
    if (lay.request_id !== p.request_id) return bad("LAYOUT_FOREIGN")
    if (lay.viewport_revision !== (viewport.revision === undefined ? null : viewport.revision)) return bad("VIEWPORT_REVISION")
    var byId = {}, i
    for (i = 0; i < p.nodes.length; ++i) byId[p.nodes[i].node_id] = p.nodes[i]
    var colW = Math.floor((viewport.width - (GRID_COLS - 1) * GAP) / GRID_COLS), seen = {}
    for (i = 0; i < lay.rects.length; ++i) {
        var r = lay.rects[i], n = byId[r.node_id]
        if (!n || seen[r.node_id]) return bad("RECT_NODE", r.node_id)
        seen[r.node_id] = true
        if (!finite(r.x) || !finite(r.y) || !finite(r.width) || !finite(r.height)) return bad("RECT_NOT_FINITE", r.node_id)
        if (r.x < 0 || r.y < 0 || r.x + r.width > viewport.width || r.y + r.height > viewport.height) return bad("OUT_OF_BOUNDS", r.node_id)
        var c = CATALOG[n.component_id]
        if (r.width < c.min_cols * colW + (c.min_cols - 1) * GAP || r.height < c.min_h) return bad("BELOW_MIN_SIZE", r.node_id)
        if (alertRect && r.x < alertRect.x + alertRect.width && alertRect.x < r.x + r.width && r.y < alertRect.y + alertRect.height && alertRect.y < r.y + r.height)
            return bad("ALERT_OCCLUDED", r.node_id)
        for (var j = 0; j < i; ++j) {
            var o = lay.rects[j]
            if (r.x < o.x + o.width && o.x < r.x + r.width && r.y < o.y + o.height && o.y < r.y + r.height) return bad("OVERLAP", r.node_id)
        }
    }
    for (i = 0; i < p.nodes.length; ++i) if (p.nodes[i].required && !seen[p.nodes[i].node_id]) return bad("REQUIRED_MISSING", p.nodes[i].node_id)
    return { ok: true, error: "", node_id: "" }
}
