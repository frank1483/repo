.pragma library
// GenUI M1 規則版：Domain Gate 與 Task Router（純 JS，不依賴 Qt 物件，可用 node 測試）。
// 依據：契約附件 v3 第一部分 §A（Gate）、附件 v1 §B（Router）、v3 §B（沒有模型選參數階段）。
// M1 只有第 1 層規則，source 一律是 "rule"；不呼叫模型、不算 embedding。
// 所有門檻都是候選值〔待凍結〕，校準包跑完才凍結。

var POLICY_VERSION = "gate-m1-0.1"
var LEXICON_VERSION = "lex-m1-0.1"
var MAX_INPUT_CHARS = 200
var T_SCORE = 2      // 〔待凍結〕
var M_MARGIN = 1     // 〔待凍結〕
var MAX_TOOLS = 3
var MAX_CLARIFY = 5

var REPLY_TOO_LONG = "輸入過長，請拆成短句"
var REPLY_OUT_OF_DOMAIN = "這不在本系統的範圍，或請把問題說完整"
var REPLY_NO_CAUSE = "此版本不提供原因分析"
var REPLY_HOLD = "我不會送飛行或相機指令，請用畫面上的指令區"
var REPLY_INVALID = "請輸入問題"

// ---------------------------------------------------------------- 詞庫
// 飛控動詞（沿用 ui_agent/qml/GcpAgentCore.js preGate 的 CMD_WORDS）
var FLIGHT_VERBS = ["起飛", "降落", "返航", "解鎖", "上鎖", "懸停", "開始任務", "執行任務", "暫停任務", "拍照", "錄影", "takeoff", "land"]
// 名詞例外：只遮罩剛好這幾個字（v3 §A-2a）。後四個是既有 preGate 已排除的參數名稱。
var NOUN_EXCEPTIONS = ["返航點", "降落點", "起飛點", "返航高度", "返航電量", "返航速度", "返航距離"]
var CLAUSE_SEPARATORS = [",", "，", "。", ";", "；", "、", "然後", "之後", "再", "並", "後"]
// 一般疑問詞：只用來判問句，不算領域證據，意圖權重為 0（v3 §A-2c）
var QUESTION_WORDS = ["怎麼", "如何", "為什麼", "為何", "哪", "多少", "幾", "什麼", "是否", "能不能", "可不可以", "會不會"]
var QUESTION_ENDINGS = ["?", "？", "嗎", "呢"]
var CAUSE_WORDS = ["原因", "為什麼", "為何", "怎麼會"]

// 領域證據 ①：gcs_demo/domains/*.json 的 keywords_zh（複本；來源變動時要一起更新並升版）
var DOMAIN_KEYWORDS = ["農業", "農田", "作物", "稻", "果園", "茶園", "病害", "病蟲害", "雜草", "噴灑", "施肥", "植保",
                       "巡檢", "班檢", "電線", "電塔", "輸電", "絕緣子", "橋梁", "管線", "太陽能板", "設施檢查",
                       "多機", "多架", "機群", "編隊", "協同", "群飛", "多台無人機"]
// 領域證據 ②：遙測欄位名稱與別名（同時是 QA 的意圖詞，權重 1）
var TELEMETRY_TERMS = ["電量", "電池", "電壓", "電流", "高度", "速度", "航向", "姿態", "gps", "衛星", "訊號", "遙測", "位置", "距離", "溫度", "風速"]
// 領域證據 ③：元件、工具與系統的固定名稱
var SYSTEM_TERMS = ["告警", "警告", "異常", "航線", "航點", "任務", "地圖", "報告", "飛行紀錄", "紀錄", "日誌", "手冊", "參數",
                    "無人機", "飛機", "機體", "相機", "雲台", "馬達", "設定", "畫面", "版面", "字體", "px4", "qgc", "圖表", "趨勢"]

var INTENT_TERMS = {
    QA:      [["目前", 1], ["現在", 1], ["最近", 1], ["上一趟", 2], ["最近一次", 1], ["剩多久", 2], ["多快", 1], ["是什麼意思", 2], ["怎麼設定", 2], ["手冊", 2], ["查詢", 1]],
    UI_OP:   [["放大", 2], ["縮小", 2], ["打開", 2], ["開啟", 2], ["關閉", 2], ["隱藏", 2], ["切換", 2], ["前往", 2], ["字體", 2], ["版面", 2], ["顯示", 1], ["畫面", 1], ["進入", 1], ["頁", 1]],
    ALERT_Q: [["告警", 2], ["警告", 2], ["有沒有問題", 2], ["異常", 1]],
    MISSION: [["規劃", 2], ["重規劃", 1], ["航線", 1], ["巡檢", 1], ["任務", 1]],
    REPORT:  [["報告", 2], ["產生", 1], ["匯出", 1]]
}
var CLARIFY_ORDER = ["ALERT_Q", "MISSION", "UI_OP", "QA", "REPORT"]

// ---------------------------------------------------------------- 小工具
function normalize(text) {
    var s = String(text === undefined || text === null ? "" : text)
    if (s.normalize) s = s.normalize("NFKC")
    return s.toLowerCase().replace(/\s+/g, " ").replace(/^ | $/g, "")
}
function charLength(s) { return Array.from ? Array.from(s).length : s.length }
function isAsciiWord(t) { return /^[a-z0-9]+$/.test(t) }
// 英數詞要求前後不是英數（避免 "land" 命中 "island"）；中文詞用字串比對
function hasTerm(text, term) {
    if (!isAsciiWord(term)) return text.indexOf(term) >= 0
    var i = text.indexOf(term)
    while (i >= 0) {
        var before = i > 0 ? text.charAt(i - 1) : " ", after = i + term.length < text.length ? text.charAt(i + term.length) : " "
        if (!/[a-z0-9]/.test(before) && !/[a-z0-9]/.test(after)) return true
        i = text.indexOf(term, i + 1)
    }
    return false
}
function matched(text, terms) {
    var out = []
    for (var i = 0; i < terms.length; ++i) if (hasTerm(text, terms[i])) out.push(terms[i])
    return out
}
// 名詞例外遮罩：長的優先，把剛好那幾個字換成佔位符 \u0001（不會被任何詞庫命中）
function maskNouns(text) {
    var ex = NOUN_EXCEPTIONS.slice().sort(function (a, b) { return b.length - a.length })
    var out = text, hits = []
    for (var i = 0; i < ex.length; ++i) {
        if (out.indexOf(ex[i]) < 0) continue
        hits.push(ex[i])
        out = out.split(ex[i]).join(new Array(ex[i].length + 1).join("\u0001"))
    }
    return { text: out, hits: hits }
}
function splitClauses(text) {
    var parts = [text]
    for (var i = 0; i < CLAUSE_SEPARATORS.length; ++i) {
        var next = []
        for (var j = 0; j < parts.length; ++j) next = next.concat(parts[j].split(CLAUSE_SEPARATORS[i]))
        parts = next
    }
    var out = []
    for (i = 0; i < parts.length; ++i) { var p = parts[i].replace(/^ | $/g, ""); if (p) out.push(p) }
    return out
}
function isQuestion(clause) {
    for (var i = 0; i < QUESTION_ENDINGS.length; ++i)
        if (clause.length && clause.lastIndexOf(QUESTION_ENDINGS[i]) === clause.length - QUESTION_ENDINGS[i].length) return true
    return matched(clause, QUESTION_WORDS).length > 0
}

// ---------------------------------------------------------------- Gate
// 回傳 {class, source:"rule", rule_no, scores, matched_terms, reply, clarify, lexicon_version, policy_version}
// class 是七類之一，或 CLARIFY / INVALID_INPUT / INPUT_TOO_LONG / NO_CAUSE_ANALYSIS。
function gate(input) {
    var text = normalize(input)
    var res = { "class": "", source: "rule", rule_no: 0, scores: {}, matched_terms: {}, reply: "", clarify: [],
                lexicon_version: LEXICON_VERSION, policy_version: POLICY_VERSION }
    function done(cls, ruleNo, reply) { res["class"] = cls; res.rule_no = ruleNo; res.reply = reply || ""; return res }

    // 1 空字串或沒有中文、英文、數字
    if (!text.length || !/[a-z0-9一-鿿]/.test(text)) return done("INVALID_INPUT", 1, REPLY_INVALID)
    // 2 過長：不截斷、不路由
    if (charLength(text) > MAX_INPUT_CHARS) return done("INPUT_TOO_LONG", 2, REPLY_TOO_LONG)
    // 3 名詞例外遮罩，再切子句
    var masked = maskNouns(text)
    var clauses = splitClauses(masked.text)
    // 4 任一子句遮罩後仍命中飛控動詞，且該子句不是問句
    for (var i = 0; i < clauses.length; ++i) {
        var verbs = matched(clauses[i], FLIGHT_VERBS)
        if (verbs.length && !isQuestion(clauses[i])) {
            res.matched_terms.flight = verbs
            return done("FLIGHT_CMD", 4, REPLY_HOLD)
        }
    }
    // 5 領域證據（和意圖分數分開）
    var domain = matched(text, DOMAIN_KEYWORDS).concat(matched(text, TELEMETRY_TERMS), matched(text, SYSTEM_TERMS),
                                                       matched(text, FLIGHT_VERBS), masked.hits)
    res.matched_terms.domain = domain
    // 6 沒有領域證據
    if (!domain.length) return done("OUT_OF_DOMAIN", 6, REPLY_OUT_OF_DOMAIN)
    // 7 問原因
    var cause = matched(text, CAUSE_WORDS)
    if (cause.length) { res.matched_terms.cause = cause; return done("NO_CAUSE_ANALYSIS", 7, REPLY_NO_CAUSE) }
    // 8 意圖打分
    var ranked = []
    for (var c = 0; c < CLARIFY_ORDER.length; ++c) {
        var cls = CLARIFY_ORDER[c], terms = INTENT_TERMS[cls], score = 0, hit = []
        for (var k = 0; k < terms.length; ++k) if (hasTerm(text, terms[k][0])) { score += terms[k][1]; hit.push(terms[k][0]) }
        if (cls === "QA") { var tel = matched(text, TELEMETRY_TERMS); score += tel.length; hit = hit.concat(tel) }
        res.scores[cls] = score
        if (hit.length) res.matched_terms[cls] = hit
        ranked.push({ cls: cls, score: score, order: c })
    }
    ranked.sort(function (a, b) { return b.score - a.score || a.order - b.order })
    // 9 所有意圖 0 分：QA（走手冊檢索）
    if (ranked[0].score === 0) return done("QA", 9)
    // 10 最高分夠高且領先夠多
    if (ranked[0].score >= T_SCORE && ranked[0].score - ranked[1].score >= M_MARGIN) return done(ranked[0].cls, 10)
    // 11 其他：請使用者選
    res.clarify = [ranked[0].cls, ranked[1].cls]
    return done("CLARIFY", 11)
}

// ---------------------------------------------------------------- Router
var ROUTE_TABLE = {
    QA:        { handler: "qa_pipeline",     confirm: "answer_direct_new_nodes_apply", fallback: "not_found" },
    UI_OP:     { handler: "ui_agent_param",  confirm: "existing",                      fallback: "existing_rule" },
    ALERT_Q:   { handler: "qa_pipeline",     confirm: "answer_direct_new_nodes_apply", fallback: "not_found", first_tool: "T_ALERT_HISTORY" },
    MISSION:   { handler: "mission_planner", confirm: "existing_always_confirm",       fallback: "existing_rule" },
    REPORT:    { handler: "report",          confirm: "existing",                      fallback: "rule_report" },
    FLIGHT_CMD:        { handler: "safety_hold",  confirm: "none", fallback: "hold" },
    OUT_OF_DOMAIN:     { handler: "fixed_reject", confirm: "none", fallback: "reject" },
    INVALID_INPUT:     { handler: "fixed_reply",  confirm: "none", fallback: "reply" },
    INPUT_TOO_LONG:    { handler: "fixed_reply",  confirm: "none", fallback: "reply" },
    NO_CAUSE_ANALYSIS: { handler: "fixed_reply",  confirm: "none", fallback: "reply" },
    CLARIFY:           { handler: "clarify",      confirm: "user_pick", fallback: "clarify" }
}
// QA 內部選工具（附件 v1 §B-2）。順序就是執行順序。
var TOOL_TRIGGERS = [
    { tool: "T_TELEMETRY",     any: ["現在", "目前", "即時"], needTelemetry: true },
    { tool: "T_FLIGHTLOG",     any: ["上一趟", "最近一次", "紀錄", "航線", "飛了多久"] },
    { tool: "T_ENERGY",        any: ["電量", "電池", "剩多久", "掉多快"] },
    { tool: "T_ALERT_HISTORY", any: ["告警", "警告", "異常", "有沒有問題"] },
    { tool: "T_MANUAL_SEARCH", any: ["怎麼設定", "是什麼意思", "手冊", "參數"] }
]
function selectTools(input, cls) {
    var text = normalize(input), tools = [], reasons = {}
    if (cls === "ALERT_Q") { tools.push("T_ALERT_HISTORY"); reasons.T_ALERT_HISTORY = ["(ALERT_Q 固定先跑)"] }
    for (var i = 0; i < TOOL_TRIGGERS.length; ++i) {
        var t = TOOL_TRIGGERS[i], hit = matched(text, t.any)
        if (!hit.length) continue
        if (t.needTelemetry) { var tel = matched(text, TELEMETRY_TERMS); if (!tel.length) continue; hit = hit.concat(tel) }
        if (tools.indexOf(t.tool) < 0) tools.push(t.tool)
        reasons[t.tool] = (reasons[t.tool] || []).concat(hit)
    }
    if (!tools.length) { tools.push("T_MANUAL_SEARCH"); reasons.T_MANUAL_SEARCH = ["(沒有命中任何工具)"] }
    var truncated = tools.length > MAX_TOOLS
    return { tools: tools.slice(0, MAX_TOOLS), tools_truncated: truncated, reasons: reasons }
}
// 參數候選：candidates 是程式列出的 [{candidate_id, label, ...}]；keep 是過濾函式。
// 剩 1 個自動用；0 個查不到；2 個以上請使用者選（最多列 5 個，不挑第一名）。沒有模型選參數的階段。
function resolveParam(candidates, keep) {
    var left = []
    for (var i = 0; i < (candidates || []).length; ++i) if (!keep || keep(candidates[i])) left.push(candidates[i])
    if (left.length === 1) return { status: "AUTO", selected: left[0], options: [] }
    if (!left.length) return { status: "NOT_FOUND", selected: null, options: [] }
    return { status: "CLARIFY", selected: null, options: left.slice(0, MAX_CLARIFY), options_total: left.length }
}
// 時間區間候選：由資料實際範圍產生（秒）。
function timeWindowCandidates(tFirst, tLast) {
    var out = []
    if (!(isFinite(tFirst) && isFinite(tLast)) || tLast < tFirst) return out
    out.push({ candidate_id: "W_ALL", label: "整趟", t0: tFirst, t1: tLast })
    if (tLast - tFirst >= 60) out.push({ candidate_id: "W_60S", label: "最近 60 秒", t0: tLast - 60, t1: tLast })
    if (tLast - tFirst >= 300) out.push({ candidate_id: "W_5MIN", label: "最近 5 分鐘", t0: tLast - 300, t1: tLast })
    return out
}

// 只追加、不改寫的 RouteRecord。sha256Hex 由呼叫端傳入（GenuiHash.js），timestamp 也由呼叫端給（台灣時間字串）。
function route(input, opts) {
    opts = opts || {}
    var g = gate(input), row = ROUTE_TABLE[g["class"]]
    var tools = (row.handler === "qa_pipeline") ? selectTools(input, g["class"]) : { tools: [], tools_truncated: false, reasons: {} }
    var record = {
        request_id: opts.request_id || "", input_hash: opts.sha256Hex ? opts.sha256Hex(normalize(input)) : "",
        context_ref: opts.context_ref || "", gate_stage: "rule", category_id: g["class"], candidates: g.clarify,
        selected_handler: row.handler, parameter_source: "program_candidates", reason_code: "rule_" + g.rule_no,
        policy_version: POLICY_VERSION, timestamp_utc8: opts.timestamp_utc8 || ""
    }
    return { gate: g, handler: row.handler, confirm: row.confirm, fallback: row.fallback, tools: tools.tools,
             tools_truncated: tools.tools_truncated, tool_reasons: tools.reasons, reply: g.reply, record: record }
}
