.pragma library
// GenUI M1 規則版：claim 候選、選擇結果的驗證與渲染。
// 版本 m1v2：依 v3 §D-7（已確認）與 v3.1 草案 §D-3'、§D-7' 修改；舊版 genui_m1/ 不動。
// 依據：契約附件 v1 §D-1、D-2，v3 第一部分 §D（必顯示組由程式固定顯示，不給模型選）。
// 模型（M2）只回傳 {"schema":"qa.claims/1","selected_claim_ids":[...]}；M1 用 selectRule()。
// 句子裡的數字、單位、方向全部取自程式產生的 Fact，不取自模型輸出。

var CLAIMS_VERSION = "claims-m1-0.2"
var SCHEMA_ID = "qa.claims/1"
var MAX_CLAIMS = 8                      // 〔待凍結〕整個答案的句數上限
var MANDATORY_ORDER = ["T-STALE", "T-PARTIAL", "T-CANNOT", "T-NOTFOUND", "T-DOC-NONE", "T-OMITTED"]
var RULE_ORDER = ["T-VALUE", "T-THRESH", "T-TREND", "T-ETA", "T-ETA-NA", "T-COUNT", "T-NONE", "T-DOC"]
var ETA_NA_TEXT = { reserve_invalid: "保留電量設定無效，無法估計剩餘時間", at_or_below_reserve: "目前電量已不高於保留電量，不估計剩餘時間",
                    over_limit: "照目前趨勢剩餘時間超過 600 分鐘，不估計" }
var PARTIAL_SUFFIX = "（資料不完整）"

var SUBJECT_ZH = { soc: "電量", alt: "高度", gs: "地速", rssi: "訊號強度", dist_home: "離家距離", alerts: "告警", manual: "手冊",
                   T_TELEMETRY: "即時遙測", T_FLIGHTLOG: "飛行紀錄", T_ENERGY: "電量趨勢", T_ALERT_HISTORY: "告警紀錄", T_MANUAL_SEARCH: "手冊" }
var SUFFIX_ZH = { min: "最小值", max: "最大值", mean: "平均值", first: "起始值", last: "結束值", duration: "時長" }
var LEVEL_ZH = { all: "", critical: "嚴重", warning: "警告", info: "提示" }

function finite(x) { return typeof x === "number" && isFinite(x) }
function subjectZh(subject) {
    var s = String(subject), dot = s.lastIndexOf(".")
    if (dot > 0 && SUFFIX_ZH[s.slice(dot + 1)]) return (SUBJECT_ZH[s.slice(0, dot)] || s.slice(0, dot)) + SUFFIX_ZH[s.slice(dot + 1)]
    return SUBJECT_ZH[s] || s
}
function num(x) { var r = Math.round(x * 10) / 10; return String(r === 0 ? 0 : r) }   // 固定取到小數一位
function defaultTime(t) { return "t=" + num(t) + " 秒" }
function span(a, b, fmt) { return fmt(a) + "～" + fmt(b) }

// toolResults: ToolResult 陣列（最多 3 個）。ctx: {formatTime(t), thresholds: [{subject, value, unit, label}]}
// 回傳 {mandatory:[claim], optional:[claim]}；claim = {claim_id, template_id, text, facts:[{tool_index, fact_id}], tool}
function generate(toolResults, ctx) {
    ctx = ctx || {}
    var fmt = ctx.formatTime || defaultTime, mandatory = [], optional = [], seq = 0
    function add(list, tpl, text, ti, factIds) {
        var refs = []
        for (var i = 0; i < factIds.length; ++i) refs.push({ tool_index: ti, fact_id: factIds[i] })
        list.push({ claim_id: "C" + (++seq), template_id: tpl, text: text, facts: refs, tool: toolResults[ti].tool })
    }
    for (var ti = 0; ti < (toolResults || []).length; ++ti) {
        var r = toolResults[ti], st = r.status, toolZh = SUBJECT_ZH[r.tool] || r.tool, partial = st === "PARTIAL"
        var sfx = partial ? PARTIAL_SUFFIX : "", d = r.detail || {}
        // 每個工具最多 1 句必顯示句；多個狀態合成一句，依「過期 → 不完整 → 樣本不足 → 查不到」（v3.1 §D-3'）
        if (st === "STALE") {
            var sf = r.facts[0], txt = (sf ? subjectZh(sf.subject) : toolZh) + "的資料已過期" + (sf && finite(sf.time) ? "（最後更新 " + fmt(sf.time) + "）" : "")
            if (d.insufficient_reason) txt += "，且樣本不足，無法估計趨勢"
            add(mandatory, "T-STALE", txt, ti, sf ? [sf.fact_id] : [])
            continue
        }
        if (st === "UNAVAILABLE" || st === "ERROR") { add(mandatory, "T-NOTFOUND", "查不到" + toolZh + "的資料", ti, []); continue }
        if (st === "UNSUPPORTED") { add(mandatory, "T-NOTFOUND", "此機型不支援" + toolZh, ti, []); continue }
        if (st === "INSUFFICIENT") { add(mandatory, "T-CANNOT", toolZh + "樣本不足，無法估計", ti, []); continue }
        if (st === "EMPTY_COMPLETE") {
            if (r.tool === "T_ALERT_HISTORY") {
                var cf = r.facts[0]
                if (cf && cf.kind === "count" && cf.value === 0)
                    add(optional, "T-NONE", span(cf.interval[0], cf.interval[1], fmt) + " 內沒有" + (LEVEL_ZH[cf.level] || "") + "告警", ti, [cf.fact_id])
            } else if (r.tool === "T_MANUAL_SEARCH") add(mandatory, "T-DOC-NONE", "手冊裡查不到相關內容", ti, [])
            else add(mandatory, "T-NOTFOUND", "查不到" + toolZh + "的資料", ti, [])
            continue
        }
        if (partial) {
            var gaps = (r.coverage && r.coverage.gaps) || [], gapText = []
            for (var g = 0; g < gaps.length; ++g) if (finite(gaps[g].t0) && finite(gaps[g].t1)) gapText.push(span(gaps[g].t0, gaps[g].t1, fmt))
            add(mandatory, "T-PARTIAL", toolZh + "的資料不完整" + (gapText.length ? "（缺 " + gapText.join("、") + "）" : ""), ti, [])
        }
        // OK 或 PARTIAL 的可選句
        for (var i = 0; i < r.facts.length; ++i) {
            var f = r.facts[i]
            if (f.kind === "value" && finite(f.value)) {
                var isStat = /\.(min|max|mean|first|last|duration)$/.test(f.subject)
                add(optional, "T-VALUE", (r.tool === "T_FLIGHTLOG" ? "該趟紀錄中" : "") + subjectZh(f.subject) + (isStat ? "是 " : " 目前是 ") + num(f.value) + f.unit
                    + (finite(f.time) && !isStat ? "（" + fmt(f.time) + "）" : "") + sfx, ti, [f.fact_id])
                var th = ctx.thresholds || []
                for (var k = 0; k < th.length; ++k) {
                    if (th[k].subject !== f.subject || th[k].unit !== f.unit || !finite(th[k].value) || f.value === th[k].value) continue
                    add(optional, "T-THRESH", subjectZh(f.subject) + " " + (f.value > th[k].value ? "高於" : "低於") + (th[k].label || "門檻") + " " + num(th[k].value) + th[k].unit + sfx, ti, [f.fact_id])
                }
            } else if (f.kind === "trend" && !partial) {
                add(optional, "T-TREND", subjectZh(f.subject) + " 在 " + span(f.window.t0, f.window.t1, fmt) + " 內" + f.direction, ti, [f.fact_id])
                if (f.direction === "下降" && finite(f.eta_min))
                    add(optional, "T-ETA", "照目前趨勢，約 " + num(f.eta_min) + " 分鐘後到保留電量" + (f.reserve_assumed ? "（依假設保留值估計）" : ""), ti, [f.fact_id])
                else if (f.direction === "下降" && ETA_NA_TEXT[f.eta_reason])
                    add(optional, "T-ETA-NA", ETA_NA_TEXT[f.eta_reason], ti, [f.fact_id])
            } else if (f.kind === "count" && finite(f.value) && (f.value > 0 || partial)) {
                add(optional, "T-COUNT", span(f.interval[0], f.interval[1], fmt) + (partial ? " 內已取得的資料中有 " : " 內有 ") + f.value + " 筆" + (LEVEL_ZH[f.level] || "") + "告警" + sfx, ti, [f.fact_id])
            } else if (f.kind === "doc_quote") {
                add(optional, "T-DOC", "「" + f.value + "」（" + f.doc + " › " + f.heading + "，" + f.doc_version + "）", ti, [f.fact_id])
            }
        }
    }
    // 被截掉沒執行的工具：固定 1 句，放在必顯示組最後（v3 §D-7、v3.1 §D-3'）
    var omitted = ctx.omitted_tools || []
    if (omitted.length) {
        var names = []
        for (var o = 0; o < omitted.length; ++o) names.push(SUBJECT_ZH[omitted[o]] || omitted[o])
        mandatory.push({ claim_id: "C" + (++seq), template_id: "T-OMITTED", text: "本次未執行：" + names.join("、") + "（一次最多查三項）", facts: [], tool: null })
    }
    var mpos = {}
    for (var mi = 0; mi < mandatory.length; ++mi) mpos[mandatory[mi].claim_id] = mi
    mandatory.sort(function (a, b) { return MANDATORY_ORDER.indexOf(a.template_id) - MANDATORY_ORDER.indexOf(b.template_id) || mpos[a.claim_id] - mpos[b.claim_id] })
    return { mandatory: mandatory, optional: optional }
}
function quota(claims) { return Math.max(0, MAX_CLAIMS - claims.mandatory.length) }

// 規則版：可選組照固定順序取到名額用完
function selectRule(claims) {
    var sorted = claims.optional.slice(), pos = {}
    for (var i = 0; i < sorted.length; ++i) pos[sorted[i].claim_id] = i
    sorted.sort(function (a, b) { return RULE_ORDER.indexOf(a.template_id) - RULE_ORDER.indexOf(b.template_id) || pos[a.claim_id] - pos[b.claim_id] })
    var q = quota(claims), ids = []
    for (i = 0; i < sorted.length && i < q; ++i) ids.push(sorted[i].claim_id)
    return { ids: ids, claims_truncated: Math.max(0, sorted.length - q) }
}

// 驗證模型的選擇（v3 §D-3）。raw 可以是字串或物件。回傳 {ok, ids, dedup, fallback_reason}
function validateSelection(raw, claims) {
    function bad(reason) { return { ok: false, ids: [], dedup: false, fallback_reason: reason } }
    var obj = raw
    if (typeof raw === "string") { try { obj = JSON.parse(raw) } catch (e) { return bad("json_parse") } }
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return bad("not_object")
    for (var key in obj) if (Object.prototype.hasOwnProperty.call(obj, key) && key !== "schema" && key !== "selected_claim_ids") return bad("extra_field")
    if (obj.schema !== SCHEMA_ID) return bad("schema")
    var sel = obj.selected_claim_ids
    if (!Array.isArray(sel)) return bad("ids_not_array")
    var optIds = Object.create(null), manIds = Object.create(null), i
    for (i = 0; i < claims.optional.length; ++i) optIds[claims.optional[i].claim_id] = true
    for (i = 0; i < claims.mandatory.length; ++i) manIds[claims.mandatory[i].claim_id] = true
    var out = [], seen = Object.create(null), dedup = false
    for (i = 0; i < sel.length; ++i) {
        if (typeof sel[i] !== "string") return bad("id_type")
        if (manIds[sel[i]]) return bad("selected_mandatory")
        if (!optIds[sel[i]]) return bad("unknown_id")
        if (seen[sel[i]]) { dedup = true; continue }
        seen[sel[i]] = true; out.push(sel[i])
    }
    if (!out.length) return bad("empty")
    if (out.length > quota(claims)) return bad("over_quota")
    return { ok: true, ids: out, dedup: dedup, fallback_reason: "" }
}

// 渲染：必顯示組在前，再照 ids 的順序。E# 依第一次出現的順序編號，只在這個答案內有效。
function render(claims, ids, source, truncated) {
    var byId = {}, i
    for (i = 0; i < claims.optional.length; ++i) byId[claims.optional[i].claim_id] = claims.optional[i]
    var list = claims.mandatory.slice()
    for (i = 0; i < ids.length; ++i) if (byId[ids[i]]) list.push(byId[ids[i]])
    var lines = [], evidence = [], eIndex = {}
    for (i = 0; i < list.length; ++i) {
        var c = list[i], eids = []
        for (var j = 0; j < c.facts.length; ++j) {
            var key = c.facts[j].tool_index + ":" + c.facts[j].fact_id
            if (!eIndex[key]) { eIndex[key] = "E" + (evidence.length + 1); evidence.push({ id: eIndex[key], tool_index: c.facts[j].tool_index, fact_id: c.facts[j].fact_id, tool: c.tool }) }
            eids.push(eIndex[key])
        }
        lines.push({ claim_id: c.claim_id, template_id: c.template_id, text: c.text, evidence_ids: eids, mandatory: i < claims.mandatory.length })
    }
    var res = { schema: "qa.answer/1", source: source, lines: lines, evidence: evidence, claims_truncated: truncated || 0 }
    if (truncated > 0) res.truncation_notice = "還有 " + truncated + " 項，見資料表"
    return res
}

// 一次做完：有模型輸出就先驗證，不合格整份退回規則模板。modelRaw 為 undefined 時就是規則版（M1）。
function answer(toolResults, ctx, modelRaw) {
    var claims = generate(toolResults, ctx), rule = selectRule(claims)
    if (!claims.mandatory.length && !claims.optional.length)
        return { schema: "qa.answer/1", source: "rule", lines: [{ claim_id: "", template_id: "T-NOTFOUND", text: "查不到", evidence_ids: [], mandatory: true }], evidence: [], claims_truncated: 0, fallback_reason: "no_claims" }
    if (modelRaw === undefined || !claims.optional.length) return render(claims, rule.ids, "rule", rule.claims_truncated)
    var v = validateSelection(modelRaw, claims)
    if (!v.ok) { var r = render(claims, rule.ids, "rule", rule.claims_truncated); r.fallback_reason = v.fallback_reason; return r }
    var m = render(claims, v.ids, "model", 0); m.dedup = v.dedup; return m
}
