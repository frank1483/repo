# Codex 補核 r3b：程式 genui_m1v2 0.3 是否照契約 v3／v3.1b 寫

日期：2026-11-16。

## 規則（務必遵守）
- 只讀。全部材料都已貼在這則訊息裡，不要讀檔、不要執行任何指令、工具、程式、測試、模型、下載、ADB；不改任何設定。
- 你不能跑程式。需要執行才能確認的地方，寫成「需要 Claude 執行的檢查」，附確切輸入與預期輸出（預期要由條文推導，不要猜程式輸出）。
- 繁體中文、台灣時間，結論先講。兩方意見一致不代表已驗證；不要放寬，也不要硬找問題。
- 使用者本人的決定不要重新裁決（V3-1～V3-9、V3.1-1、V3.1-2、v3.1b 全文已於 11/16 13:04 確認）。若有安全或正確性問題，照實指出並標「需使用者重新裁決」。
- 輸出格式：# 判定（可進入／需修正後再進入）→ 逐項表 → 新問題（編號、嚴重度、位置、證據、反例、建議修法）→ 需要 Claude 執行的檢查 → 你沒看到的材料。

## 請你做的事
1. 對 run2b 的 C-01～C-14 逐項判定：已修正／部分／未修正，指出程式位置（檔名與函式）。
2. 逐檔對照 v3.1b，找程式與契約不一致或契約沒寫但程式自己決定的地方。特別看：GenuiGate 的 commandVerbs 與 splitClausesQ；codePoints 與能力檢查（Qt 6.8.3 的 Array.from 按 UTF-16 切、sort 不穩定，已在雲端 PySide6 6.8.3 實測）；energyTrend 的跳變、過期與樣本不足同時記錄、eta_reason；manualSearch 的去重、內容詞與退路；Claims 的 T-OMITTED、合併狀態句、T-ETA-NA；Layout 的 binding 驗證與 PLAN_TAMPERED；Python 對照版 reference.py 是否和 JS 共用相同錯誤。
3. 測試是否有弱斷言或預期值抄自輸出。run4 有一個預期值是我寫錯的（J03），請確認判斷是否正確。


===== 檔案：genui_m1v2/qml/GenuiGate.js（sha256 8509f0df505e34d8913d99954b0e862a2ce10734bdebf6925243617b1915c7f4）=====
.pragma library
// GenUI M1 規則版：Domain Gate 與 Task Router（純 JS，不依賴 Qt 物件，可用 node 測試）。
// 版本 m1v2：依契約附件 v3.1 草案 §A-0'、A-2'、A-2a'～c'、A-3'（尚未經使用者確認）修改 Gate；舊版 genui_m1/ 不動。
// 依據：契約附件 v3 第一部分 §A（Gate）、附件 v1 §B（Router）、v3 §B（沒有模型選參數階段）。
// M1 只有第 1 層規則，source 一律是 "rule"；不呼叫模型、不算 embedding。
// 所有門檻都是候選值〔待凍結〕，校準包跑完才凍結。

var POLICY_VERSION = "gate-m1-0.3"
var LEXICON_VERSION = "lex-m1-0.2"
var MAX_INPUT_CHARS = 200
var T_SCORE = 1      // calibration_v1 A1 凍結值（hash8 b1da1e48）
var M_MARGIN = 1     // 〔待凍結〕
var MAX_TOOLS = 3
var MAX_CLARIFY = 5

var REPLY_TOO_LONG = "輸入過長，請拆成短句"
var REPLY_OUT_OF_DOMAIN = "這不在本系統的範圍，或請把問題說完整"
var REPLY_NO_CAUSE = "此版本不提供原因分析"
var REPLY_HOLD = "我不會送飛行或相機指令，請用畫面上的指令區"
var REPLY_INVALID = "請輸入問題"
var REPLY_CAPABILITY = "問答功能無法啟動（引擎能力不足）"

// ---------------------------------------------------------------- 詞庫
// 飛控動詞（沿用 ui_agent/qml/GcpAgentCore.js preGate 的 CMD_WORDS）
var FLIGHT_VERBS = ["起飛", "降落", "返航", "解鎖", "上鎖", "懸停", "開始任務", "執行任務", "暫停任務", "拍照", "錄影", "takeoff", "land"]
// 名詞例外表 v1.1（v3.1 §A-2a'）
var NOUN_EXCEPTIONS = ["返航點", "降落點", "起飛點", "返航高度", "返航電量", "返航速度", "返航距離"]
// 子句分界（v3.1 §A-2b'）：標點、換行、多字連接詞。單字「再」「並」「後」不再當分界。
var CLAUSE_SEPARATOR_RE = /(然後|之後|接著|並且|再來|[,，。.．;；、?？!！\n])/
var QUESTION_MARKS = ["?", "？"]
// 能力詞：出現在飛控動詞前面（中間最多隔 2 個字）時，該動詞算「被問」（v3.1 §A-3'）
var CAPABILITY_WORDS = ["能不能", "可不可以", "會不會", "是否", "能否", "可以"]
var CAPABILITY_GAP_MAX = 2
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
// 依碼位切字串。Qt 6.8.3 的 Array.from(字串) 會按 UTF-16 切（qt_poc_run1 發現），所以用 for…of。
function codePoints(s) { var out = []; for (var ch of s) out.push(ch); return out }
// 能力檢查（v3.1 §A-0'）：沒有 NFKC 或碼位走訪就不啟用 Gate，不做降級替代。
function capabilityOk() {
    try { return typeof "".normalize === "function" && "Ａ".normalize("NFKC") === "A" && codePoints("𠀀a").length === 2 && "𠀀".codePointAt(0) === 0x20000 }
    catch (e) { return false }
}
// 換行保留（當子句分界），其他連續空白縮成一個
function normalize(text) {
    var s = String(text === undefined || text === null ? "" : text).normalize("NFKC").toLowerCase()
    s = s.replace(/\r\n?/g, "\n").replace(/[^\S\n]+/g, " ").replace(/ *\n[\s]*/g, "\n")
    return s.replace(/^[ \n]+|[ \n]+$/g, "")
}
function charLength(s) { return codePoints(s).length }
// 有沒有中文（含擴充 A、相容、擴充 B 以後）、英文或數字
function hasContentChar(s) {
    var cps = codePoints(s)
    for (var i = 0; i < cps.length; ++i) {
        var c = cps[i].codePointAt(0)
        if ((c >= 0x30 && c <= 0x39) || (c >= 0x61 && c <= 0x7a) || (c >= 0x3400 && c <= 0x4dbf) || (c >= 0x4e00 && c <= 0x9fff)
            || (c >= 0xf900 && c <= 0xfaff) || (c >= 0x20000 && c <= 0x2fa1f)) return true
    }
    return false
}
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
// 回傳 [{text, q}]；q = 這個子句後面緊接著問號
function splitClausesQ(text) {
    var parts = text.split(CLAUSE_SEPARATOR_RE), out = []
    for (var i = 0; i < parts.length; i += 2) {
        var p = parts[i].replace(/^ | $/g, ""), sep = i + 1 < parts.length ? parts[i + 1] : ""
        if (p) out.push({ text: p, q: QUESTION_MARKS.indexOf(sep) >= 0 })
    }
    return out
}
function splitClauses(text) { var c = splitClausesQ(text), out = []; for (var i = 0; i < c.length; ++i) out.push(c[i].text); return out }
// 子句裡每個飛控動詞的位置是不是「被問」（v3.1 §A-3'）。回傳命令用的動詞清單（空 = 沒有命令）。
function commandVerbs(clause) {
    var text = clause.text, cmds = []
    for (var v = 0; v < FLIGHT_VERBS.length; ++v) {
        var verb = FLIGHT_VERBS[v], at = text.indexOf(verb)
        while (at >= 0) {
            if (hasTerm(text.substr(at, verb.length), verb) && (isAsciiWord(verb) ? isWordAt(text, at, verb) : true)) {
                var before = text.slice(0, at), after = text.slice(at + verb.length), asked = false
                for (var k = 0; k < CAPABILITY_WORDS.length && !asked; ++k) {
                    var e = before.lastIndexOf(CAPABILITY_WORDS[k])
                    if (e >= 0 && at - (e + CAPABILITY_WORDS[k].length) <= CAPABILITY_GAP_MAX) asked = true
                }
                if (!asked && (matched(after, QUESTION_WORDS).length || after.indexOf("嗎") >= 0 || after.indexOf("呢") >= 0 || clause.q)) asked = true
                if (!asked && matched(before, CAUSE_WORDS).length) asked = true
                if (!asked && cmds.indexOf(verb) < 0) cmds.push(verb)
            }
            at = text.indexOf(verb, at + 1)
        }
    }
    return cmds
}
function isWordAt(text, at, term) {
    var b = at > 0 ? text.charAt(at - 1) : " ", a = at + term.length < text.length ? text.charAt(at + term.length) : " "
    return !/[a-z0-9]/.test(b) && !/[a-z0-9]/.test(a)
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
    var res = { "class": "", source: "rule", rule_no: 0, scores: {}, matched_terms: {}, reply: "", clarify: [],
                lexicon_version: LEXICON_VERSION, policy_version: POLICY_VERSION }
    function done(cls, ruleNo, reply) { res["class"] = cls; res.rule_no = ruleNo; res.reply = reply || ""; return res }

    if (!capabilityOk()) return done("GATE_CAPABILITY_FAIL", 0, REPLY_CAPABILITY)
    var text = normalize(input)
    // 1 空字串或沒有中文、英文、數字
    if (!text.length || !hasContentChar(text)) return done("INVALID_INPUT", 1, REPLY_INVALID)
    // 2 過長：不截斷、不路由
    if (charLength(text) > MAX_INPUT_CHARS) return done("INPUT_TOO_LONG", 2, REPLY_TOO_LONG)
    // 3 名詞例外遮罩，再切子句
    var masked = maskNouns(text)
    var clauses = splitClausesQ(masked.text)
    // 4 任一子句遮罩後仍有「命令用」的飛控動詞（v3.1 §A-3'：逐一看動詞位置是不是被問）
    for (var i = 0; i < clauses.length; ++i) {
        var verbs = commandVerbs(clauses[i])
        if (verbs.length) {
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
    var pos = []
    for (c = 0; c < ranked.length; ++c) if (ranked[c].score > 0) pos.push(ranked[c])
    // 9 沒有任何類別得正分：QA（走手冊檢索）
    if (!pos.length) return done("QA", 9)
    // 10 最高分夠高且領先夠多（第二名沒有就當 0）
    var second = pos.length > 1 ? pos[1].score : 0
    if (pos[0].score >= T_SCORE && pos[0].score - second >= M_MARGIN) return done(pos[0].cls, 10)
    // 11a 只有一個正分類別但未達 T：只問「是不是要 X」（v3.1 §A-2'）
    if (pos.length === 1) { res.clarify = [pos[0].cls]; return done("CLARIFY_ONE", 11) }
    // 11b 兩個以上正分：列正分的前 2 類（不湊零分類別）
    res.clarify = [pos[0].cls, pos[1].cls]
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
    CLARIFY:           { handler: "clarify",      confirm: "user_pick", fallback: "clarify" },
    CLARIFY_ONE:       { handler: "clarify_one",  confirm: "user_pick", fallback: "clarify" },
    GATE_CAPABILITY_FAIL: { handler: "fixed_reply", confirm: "none", fallback: "reply" }
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
    return { tools: tools.slice(0, MAX_TOOLS), tools_truncated: truncated, omitted_tools: tools.slice(MAX_TOOLS), reasons: reasons }
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
    var tools = (row.handler === "qa_pipeline") ? selectTools(input, g["class"]) : { tools: [], tools_truncated: false, omitted_tools: [], reasons: {} }
    var record = {
        request_id: opts.request_id || "", input_hash: opts.sha256Hex && g.rule_no !== 0 ? opts.sha256Hex(normalize(input)) : "",
        context_ref: opts.context_ref || "", gate_stage: "rule", category_id: g["class"], candidates: g.clarify,
        selected_handler: row.handler, parameter_source: "program_candidates", reason_code: "rule_" + g.rule_no,
        policy_version: POLICY_VERSION, timestamp_utc8: opts.timestamp_utc8 || ""
    }
    return { gate: g, handler: row.handler, confirm: row.confirm, fallback: row.fallback, tools: tools.tools,
             tools_truncated: tools.tools_truncated, omitted_tools: tools.omitted_tools, tool_reasons: tools.reasons, reply: g.reply, record: record }
}

===== 檔案結束：genui_m1v2/qml/GenuiGate.js =====


===== 檔案：genui_m1v2/qml/GenuiTools.js（sha256 ab91bed4432fa5c1940df802fe099c4f40c35b4ee8f7dd243c9196a344ff068e）=====
.pragma library
// GenUI M1 規則版：5 個唯讀工具的純計算部分（不讀檔、不連線、不對飛機下指令）。
// 依據：M1 演算法說明 v2 §3、契約附件 v1 §C 與 v3 第一部分 §C（電量斜率：先清理、再取視窗）。
// 版本 m1v2：依 v3 §C（已確認）與 v3.1 草案 §C'、§D-6'、§L' 修改；舊版 genui_m1/ 不動。
// 資料由呼叫端（重放器或紀錄讀取器）以陣列傳入；缺值一律不補。數值門檻都是候選值〔待凍結〕。

var TOOLS_VERSION = "tools-m1-0.3"
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
                reserve_pct: finite(reserve) ? reserve : null, reserve_assumed: !!opts.reserveAssumed, stale: false, insufficient_reason: "", reason: "", jump_at: null }
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
    // 3b 跳變（V3.1-2，使用者 11/16 13:19）：相鄰兩筆變化超過 5%，視窗從最後一次跳變後那一筆重新起算
    var start = 0
    for (i = 1; i < dedup.length; ++i) if (Math.abs(dedup[i].soc - dedup[i - 1].soc) > P.JUMP_PCT) start = i
    out.jump_at = start > 0 ? dedup[start].t : null
    // 4 取視窗
    var tEnd = dedup[dedup.length - 1].t, win = []
    for (i = start; i < dedup.length; ++i) if (dedup[i].t >= tEnd - W) win.push(dedup[i])
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

===== 檔案結束：genui_m1v2/qml/GenuiTools.js =====


===== 檔案：genui_m1v2/qml/GenuiClaims.js（sha256 b65048a11c6c336d2330fe5ba32a79248f012f77270a4a5b8aaf032e7668f98f）=====
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

===== 檔案結束：genui_m1v2/qml/GenuiClaims.js =====


===== 檔案：genui_m1v2/qml/GenuiLayout.js（sha256 1de7930be088b34551288968a0df628f6e9a3bc2822e2a6ad1265dee1d6a89cc）=====
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

===== 檔案結束：genui_m1v2/qml/GenuiLayout.js =====


===== 檔案：genui_m1v2/golden/reference.py（sha256 2d53ded70b81eae224fc1e9b76ac45607d07ef5ba01d9c50be59aadbb09311c0）=====
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


def energy(samples, o):
    """v3 §C 與 v3.1 草案 §C'：W 固定 60；保留值 0～100（含 100）有效且一律判定；過期與樣本不足都檢查，status 取過期優先。"""
    res = o.get("reservePct")
    rv = fin(res) and 0 <= res <= 100
    d = dict(slope_pct_per_min=None, r2=None, n_valid=0, n_dropped=0, coverage_ratio=None, direction=None, eta_min=None, eta_reason="",
             disorder_ratio=None, reserve_valid=rv, reserve_invalid=not rv, reserve_pct=res if fin(res) else None,
             reserve_assumed=bool(o.get("reserveAssumed")), stale=False, insufficient_reason="", reason="", jump_at=None)
    out = dict(status=None, detail=d, requested=None, covered=None, points=None, intercept=None)

    def ret(status):
        out["status"] = status; return out

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
        d["reason"] = d["insufficient_reason"] = "no_valid_samples"; return ret("INSUFFICIENT")
    seen_max, dis = -math.inf, 0
    for t, _, _ in kept:
        if t < seen_max: dis += 1
        else: seen_max = t
    d["disorder_ratio"] = dis / len(kept)
    if d["disorder_ratio"] > DIS_MAX: d["insufficient_reason"] = "disorder"
    latest = {}
    for t, i, soc in sorted(kept):
        latest[t] = soc
    ts = sorted(latest)
    t_end = ts[-1]
    start = 0
    for k in range(1, len(ts)):
        if abs(latest[ts[k]] - latest[ts[k - 1]]) > JUMP: start = k
    d["jump_at"] = ts[start] if start > 0 else None
    win = [(t, latest[t]) for t in ts[start:] if t >= t_end - W]
    d["n_valid"] = len(win)
    t0 = win[0][0]
    d["coverage_ratio"] = (t_end - t0) / W
    out["requested"], out["covered"] = [t_end - W, t_end], [t0, t_end]
    d["stale"] = bool(o.get("checkStale") and fin(now) and now - t_end > STALE_S)
    gap = max([b[0] - a[0] for a, b in zip(win, win[1:])] or [0])
    if not d["insufficient_reason"]:
        if len(win) < N_MIN: d["insufficient_reason"] = "n_valid"
        elif d["coverage_ratio"] < COV_MIN: d["insufficient_reason"] = "coverage"
        elif gap > GAP_MAX: d["insufficient_reason"] = "gap"
    if d["stale"]:
        d["reason"] = "stale"; return ret("STALE")
    if d["insufficient_reason"]:
        d["reason"] = d["insufficient_reason"]; return ret("INSUFFICIENT")
    n = len(win)
    xs, ys = [t - t0 for t, _ in win], [s for _, s in win]
    xb, yb = sum(xs) / n, sum(ys) / n
    sxx = sum((x - xb) ** 2 for x in xs); syy = sum((y - yb) ** 2 for y in ys)
    sxy = sum((x - xb) * (y - yb) for x, y in zip(xs, ys))
    if sxx == 0:
        d["reason"] = d["insufficient_reason"] = "zero_time_variance"; return ret("INSUFFICIENT")
    out["points"] = [[t, s] for t, s in win]
    if syy == 0:
        d["slope_pct_per_min"], d["direction"], d["eta_reason"] = 0, "持平", "not_falling"
        out["intercept"] = yb
        return ret("OK")
    slope, r2 = sxy / sxx * 60, sxy * sxy / (sxx * syy)
    d["slope_pct_per_min"], d["r2"] = slope, r2
    if r2 < R2_MIN:
        d["reason"] = d["insufficient_reason"] = "r2"; out["points"] = None; return ret("INSUFFICIENT")
    d["direction"] = "下降" if slope < -(EPS + NUM_EPS) else ("上升" if slope > EPS + NUM_EPS else "持平")
    if d["direction"] != "下降": d["eta_reason"] = "not_falling"
    elif not rv: d["eta_reason"] = "reserve_invalid"
    elif not ys[-1] > res: d["eta_reason"] = "at_or_below_reserve"
    else:
        eta = (ys[-1] - res) / abs(slope)
        if eta <= ETA_MAX + NUM_EPS: d["eta_min"] = eta
        else: d["eta_reason"] = "over_limit"
    out["intercept"] = yb - (sxy / sxx) * xb
    return ret("OK")


def telemetry(c):
    if c["samples"] is None: return dict(status="UNAVAILABLE", facts=[])
    ok = [(s["t"], k, s["value"]) for k, s in enumerate(c["samples"]) if s and fin(s.get("t")) and fin(s.get("value")) and not (fin(c["now"]) and s["t"] > c["now"] + FUTURE_S)]
    if not ok: return dict(status="UNAVAILABLE", facts=[])
    t, _, v = max(ok)                        # 時間最大；同時間取後到的
    return dict(status="STALE" if c["now"] - t > STALE_S else "OK", facts=[["F1", "value", c["field"], v, t]])


def flightlog(c):
    """v3.1 §D-6'：同時戳保留到達順序、不去重；統計用全部原始值；超過 300 點等分 150 桶（依時間），每桶留最小與最大。"""
    if c["samples"] is None: return dict(status="UNAVAILABLE", facts=[], points=[])
    pts = sorted([(s["t"], k, s["value"]) for k, s in enumerate(c["samples"]) if fin(s.get("t")) and fin(s.get("value")) and c["t0"] <= s["t"] <= c["t1"]],
                 key=lambda p: (p[0], p[1]))
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
        ta, width = pts[0][0], (pts[-1][0] - pts[0][0]) / BUCKETS
        groups = {}
        for i, (t, v) in enumerate(pts):
            bi = min(BUCKETS - 1, math.floor((t - ta) / width)) if width > 0 else 0
            groups.setdefault(bi, []).append(i)
        series = []
        for bi in sorted(groups):
            idx = groups[bi]
            lo = min(idx, key=lambda i: (pts[i][1], i)); hi = max(idx, key=lambda i: (pts[i][1], -i))
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


def manual(chunks, c, glossary):
    """v3 §L-3 去重（chunk_id，再同文件同文字）後排名；v3.1 §L' 合格：命中內容詞 ≥ 一半。"""
    uniq, ids, texts = [], set(), set()
    for ch in chunks:
        if ch["chunk_id"] in ids or (ch["doc"], ch["text"]) in texts: continue
        ids.add(ch["chunk_id"]); texts.add((ch["doc"], ch["text"])); uniq.append(ch)
    q = c["query"] or ""
    for w in DOC_STOP: q = q.replace(w, " ")
    extra = [w for zh, ws in (glossary if c["use_glossary"] else {}).items() if zh in q for w in ws]
    terms = list(dict.fromkeys(tokens(q + " " + " ".join(extra) if extra else q)))
    docs = [tokens(ch["text"]) for ch in uniq]
    n = len(docs); avg = sum(len(d) for d in docs) / n if n else 0
    df = {}
    for d in docs:
        for t in set(d): df[t] = df.get(t, 0) + 1
    content = [t for t in terms if not n or df.get(t, 0) / n <= DOC_DF_MAX]
    if not any(df.get(t, 0) for t in content): content = list(terms)   # 剩下的詞都不在手冊裡就不做這一步（run1 發現）
    scored = []
    for ch, d in zip(uniq, docs):
        hit = sum(1 for t in content if t in d)
        cover = hit / len(content) if content else 0
        s = 0.0
        for t in terms:
            tf = d.count(t)
            if tf: s += math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf * (K1 + 1) / (tf + K1 * (1 - B + B * (len(d) / avg if avg else 0)))
        if s > 0 and hit >= 1 and cover >= DOC_MIN_COV: scored.append((-s, ch["chunk_id"]))
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

===== 檔案結束：genui_m1v2/golden/reference.py =====


===== 檔案：genui_m1v2/golden/check_expect.py（sha256 8f88ac232d776ff067f650863371554eaf07d0cb82fec11d8f1ecde57c43fd41）=====
"""把一份結果（JS 或 Python）和 vectors_v3.json 的 expect 比對。expect 是部分欄位；數字容差 1e-6。
用法：python3 -I check_expect.py vectors.json result.json [overrides.json]  （結束碼 1 表示有不符）
overrides：因已裁決的條文改變而更新的預期，依案例 id 取代 expect（原向量檔不動）。"""
import json, math, sys

V, R = json.load(open(sys.argv[1], encoding="utf-8")), json.load(open(sys.argv[2], encoding="utf-8"))
OV = json.load(open(sys.argv[3], encoding="utf-8")) if len(sys.argv) > 3 else {}
bad = n = 0


def eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(eq(x, y) for x, y in zip(a, b))
    return a == b


def sub(exp, got, path, out):
    for k, v in exp.items():
        if isinstance(v, dict):
            sub(v, (got or {}).get(k) or {}, path + "." + k, out)
        elif k not in (got or {}) or not eq(v, got[k]):
            out.append(f"{path}.{k}: want={v!r} got={(got or {}).get(k, '<missing>')!r}")


for group, cases in V["cases"].items():
    for c in cases:
        if "expect" not in c: continue
        n += 1
        got, exp, diffs = R.get(c["id"]), dict(OV.get(c["id"], c["expect"])), []
        if c["id"] in OV: print("OVERRIDE " + c["id"])
        if got is None: diffs.append("missing case")
        else:
            if "points_head" in exp:
                ph = exp.pop("points_head")
                if not eq(ph, got["points"][:len(ph)]): diffs.append(f"points_head want={ph} got={got['points'][:len(ph)]}")
            if "facts" in exp and group == "flightlog":
                fx = exp.pop("facts"); fm = {f[2]: f[3] for f in got["facts"]}
                for k, v in fx.items():
                    if not eq(v, fm.get(k)): diffs.append(f"facts.{k}: want={v} got={fm.get(k)}")
            if "hit_ids" in exp:
                hid = exp.pop("hit_ids")
                if [h[0] for h in got["hits"]] != hid: diffs.append(f"hit_ids want={hid} got={[h[0] for h in got['hits']]}")
            sub(exp, got, c["id"], diffs)
        if diffs:
            bad += 1; print("MISMATCH " + c["id"]); [print("  " + d) for d in diffs]
print(f"expect cases {n} / mismatch {bad}")
sys.exit(1 if bad else 0)

===== 檔案結束：genui_m1v2/golden/check_expect.py =====


===== 檔案：genui_m1v2/golden/compare.py（sha256 41c41b1dfbf00933559b27847132220d8bcd727cd7fef5b8b3f66f8d2cff3e18）=====
"""逐案比對 JS 與 Python 的結果。數字容差：相對 1e-9 或絕對 1e-9。用法：compare.py js.json py.json"""
import json, math, sys

TOL = 1e-9


def same(a, b, path, diffs):
    if isinstance(a, bool) != isinstance(b, bool):          # true 與 1 算不同（C-14）
        diffs.append(f"{path}: type js={type(a).__name__} py={type(b).__name__}"); return
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        if a != b: diffs.append(f"{path}: js={a!r} py={b!r}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not math.isclose(a, b, rel_tol=TOL, abs_tol=TOL): diffs.append(f"{path}: js={a!r} py={b!r}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): diffs.append(f"{path}: length js={len(a)} py={len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)): same(x, y, f"{path}[{i}]", diffs)
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b: diffs.append(f"{path}.{k}: missing in {'js' if k not in a else 'py'}")
            else: same(a[k], b[k], f"{path}.{k}", diffs)
    else:
        diffs.append(f"{path}: type js={type(a).__name__} py={type(b).__name__}")


js, py = json.load(open(sys.argv[1], encoding="utf-8")), json.load(open(sys.argv[2], encoding="utf-8"))
bad, status = 0, {}
for cid in sorted(set(js) | set(py)):
    diffs = []
    if cid not in js or cid not in py: diffs.append("missing case")
    else: same(js[cid], py[cid], cid, diffs)
    if diffs:
        bad += 1; print("DIFF " + cid); [print("  " + d) for d in diffs[:6]]
    elif "status" in js[cid]:
        key = cid.rstrip("0123456789_nulempty")[:1] + ":" + js[cid]["status"]; status[key] = status.get(key, 0) + 1
print("status coverage: " + json.dumps(status, ensure_ascii=False, sort_keys=True))
print(f"cases {len(set(js) | set(py))} / differ {bad}")
sys.exit(1 if bad else 0)

===== 檔案結束：genui_m1v2/golden/compare.py =====


===== 檔案：genui_m1v2/golden/make_vectors_v3.js（sha256 30b7e4b270fa03d7dba32dfb68a6d4d5d4d1b11d5d037cddb5583a28d2f6ff10）=====
// G4 第 3 版向量：Codex run2b §4-1、4-2、4-3、4-6 的確切輸入，加上由條文手算的預期值（expect）。
// 預期值寫在這裡、先於任何實作輸出提交；check_expect.py 讓 JS 與 Python 各自和它比，不互相當標準答案。
// 執行：node genui_m1v2/golden/make_vectors_v3.js > genui_m1v2/golden/vectors_v3.json
const R = (a, b) => Array.from({ length: 61 }, (_, t) => ({ t, soc: a + b * t / 60 }))
const O = (x) => Object.assign({ now: 60, reservePct: 20, vehicleType: 'multirotor' }, x || {})
const without = (s, lo, hi) => s.filter(p => p.t < lo || p.t > hi)
const energy = [], E = (id, samples, opts, expect) => energy.push({ id, samples, opts, expect })

const e01 = { status: 'OK', detail: { slope_pct_per_min: -1, r2: 1, direction: '下降', eta_min: 59, eta_reason: '', reserve_valid: true, reserve_invalid: false, n_valid: 61, disorder_ratio: 0 }, requested: [0, 60], covered: [0, 60] }
E('E01', R(80, -1), O(), e01)
E('E02', R(80, -1), O({ reserveAssumed: true }), { status: 'OK', detail: { eta_min: 59, reserve_assumed: true } })
E('E03', R(80, -1), O({ reservePct: 100 }), { status: 'OK', detail: { slope_pct_per_min: -1, direction: '下降', reserve_valid: true, reserve_invalid: false, eta_min: null, eta_reason: 'at_or_below_reserve' } })
E('E04', R(80, -1), O({ reservePct: 0 }), { status: 'OK', detail: { reserve_valid: true, eta_min: 79 } })
for (const [k, v] of [['a', -1], ['b', 100.1], ['c', null]]) {
  E('E05' + k, R(80, -1), O({ reservePct: v }), { status: 'OK', detail: { slope_pct_per_min: -1, direction: '下降', reserve_invalid: true, eta_min: null, eta_reason: 'reserve_invalid' } })
  E('E06' + k, R(80, 0), O({ reservePct: v }), { status: 'OK', detail: { slope_pct_per_min: 0, direction: '持平', r2: null, reserve_invalid: true, eta_min: null, eta_reason: 'not_falling' } })
}
E('E08', without(R(80, -1), 21, 30), O(), { status: 'INSUFFICIENT', detail: { reason: 'gap', insufficient_reason: 'gap', n_valid: 51, eta_min: null } })
E('E09', without(R(80, -1), 21, 29), O(), { status: 'OK', detail: { slope_pct_per_min: -1, direction: '下降', eta_min: 59, n_valid: 52 } })
E('E10', R(50, 0.5), O(), { status: 'OK', detail: { slope_pct_per_min: 0.5, r2: 1, direction: '上升', eta_min: null, eta_reason: 'not_falling' } })
const e11 = R(80, -1); e11[60] = { t: 60, soc: 78 }; e11.push({ t: 60, soc: 79 })
E('E11', e11, O(), { status: 'OK', detail: { n_valid: 61, slope_pct_per_min: -1, r2: 1, eta_min: 59, disorder_ratio: 0 } })
E('E12_W30_ignored', R(80, -1), O({ W: 30 }), e01)
E('E12_Wneg_ignored', R(80, -1), O({ W: -1 }), e01)
const eta600 = Array.from({ length: 17 }, (_, i) => ({ t: 3.75 * i, soc: 57.5625 - i / 256 }))
E('E13_eta600', eta600, O(), { status: 'OK', detail: { slope_pct_per_min: -0.0625, direction: '下降', eta_min: 600, n_valid: 17 } })
E('E13_eta601', eta600.map(p => ({ t: p.t, soc: p.soc + 0.0625 })), O(), { status: 'OK', detail: { slope_pct_per_min: -0.0625, eta_min: null, eta_reason: 'over_limit' } })
E('E14_stale_and_few', [{ t: 0, soc: 80 }], { now: 10, checkStale: true, reservePct: 20 }, { status: 'STALE', detail: { stale: true, insufficient_reason: 'n_valid', reason: 'stale' } })
E('E15_same_t', Array.from({ length: 20 }, () => ({ t: 0, soc: 80 })), O({ now: 0 }), { status: 'INSUFFICIENT', detail: { reason: 'n_valid', n_valid: 1 } })
E('E16_flat_boundary', R(80, -0.05), O(), { status: 'OK', detail: { direction: '持平', eta_min: null, eta_reason: 'not_falling' } })
E('E17_just_falling', R(80, -0.0501), O(), { status: 'OK', detail: { direction: '下降', eta_min: null, eta_reason: 'over_limit' } })
E('E18_noise', R(80, -1).map(p => ({ t: p.t, soc: p.soc + 0.3 * Math.sin(p.t * 1.7) })), O(), { status: 'OK', detail: { direction: '下降' } })

// 亂序（§4-2）
const B = Array.from({ length: 100 }, (_, t) => ({ t, soc: 80 - t / 60 }))
const S = k => { const a = B.map(p => ({ ...p })); for (let j = 0; j < k; ++j) { const x = a[4 * j + 1]; a[4 * j + 1] = a[4 * j + 2]; a[4 * j + 2] = x } return a }
const oo = O({ now: 99 })
E('O01', S(20), oo, { status: 'OK', detail: { disorder_ratio: 0.2, n_valid: 61 } })
E('O02', S(21), oo, { status: 'INSUFFICIENT', detail: { disorder_ratio: 0.21, reason: 'disorder' } })
E('O03', S(20).concat([{ t: 101, soc: 50 }]), oo, { status: 'OK', detail: { disorder_ratio: 0.2, n_dropped: 1 } })
E('O04', S(20).concat([{ t: 50, soc: 80 - 50 / 60 }]), oo, { status: 'INSUFFICIENT', detail: { disorder_ratio: 21 / 101, reason: 'disorder' } })
E('O05', S(20).concat([{ t: 99, soc: 80 - 99 / 60 }]), oo, { status: 'OK', detail: { disorder_ratio: 20 / 101, n_valid: 61 } })
E('O06', Array.from({ length: 20 }, (_, i) => ({ t: -981 - i, soc: 80 })).concat(R(80, -1)), O(), { status: 'INSUFFICIENT', detail: { disorder_ratio: 19 / 81, reason: 'disorder' } })

// 飛行紀錄同時戳（§4-6）
const fl = [{ t: 0, value: 0 }, { t: 0, value: 10 }].concat(Array.from({ length: 299 }, (_, i) => ({ t: i + 1, value: 5 })))
const flightlog = [{ id: 'FL01_same_t', field: 'alt', unit: 'm', samples: fl, t0: 0, t1: 299, gaps: [],
  expect: { status: 'OK', points_head: [[0, 0], [0, 10]], facts: { 'alt.min': 0, 'alt.max': 10, 'alt.mean': (10 + 5 * 299) / 301 } } }]

// 手冊去重（§4-6）：c01 重複、c02 與 c01 同文件同文字
const chunks = [{ chunk_id: 'c01', doc: 'D1', heading: 'h', version: 'v1', text: 'battery' }, { chunk_id: 'c01', doc: 'D1', heading: 'h', version: 'v1', text: 'battery' },
                { chunk_id: 'c02', doc: 'D1', heading: 'h', version: 'v1', text: 'battery' }, { chunk_id: 'c03', doc: 'D2', heading: 'h', version: 'v1', text: 'battery' }]
const manual = [{ id: 'M01_dedup', query: 'battery', use_glossary: false, expect: { status: 'OK', hit_ids: ['c01', 'c03'] } }]

process.stdout.write(JSON.stringify({ version: 'g4-v3', note: 'Codex run2b §4 的確切輸入；expect 由條文手算', chunks, glossary: {},
  cases: { energy, telemetry: [], flightlog, alerts: [], manual } }, null, 1))

===== 檔案結束：genui_m1v2/golden/make_vectors_v3.js =====


===== 檔案：genui_m1v2/golden/make_vectors_v4.js（sha256 765fa6b9f60b537a2c48d8a4b0c15987fbff4abb7ab1cd925a41570a98aa1d2d）=====
// G4 第 4 版：V3.1-2（跳變規則、R² 0.8）的新案例，預期值由條文手算，先於執行提交。
const R = (a, b, n = 61, t0 = 0) => Array.from({ length: n }, (_, i) => ({ t: t0 + i, soc: a + b * i / 60 }))
const O = x => Object.assign({ now: 60, reservePct: 20, vehicleType: 'multirotor' }, x || {})
const energy = [], E = (id, samples, opts, expect) => energy.push({ id, samples, opts, expect })
// J01 下降 0..60 後在 61 跳到 100，之後 61..120 持平：跳變在 61，視窗 61..120 共 60 筆、覆蓋 59/60 → 持平
E('J01_jump_then_flat', R(80, -1).concat(R(100, 0, 60, 61)), O({ now: 120 }), { status: 'OK', detail: { jump_at: 61, n_valid: 60, direction: '持平' } })
// J02 跳變後只有 10 秒：覆蓋不足
E('J02_jump_recent', R(80, -1).concat(R(100, 0, 11, 61)), O({ now: 71 }), { status: 'INSUFFICIENT', detail: { jump_at: 61, reason: 'coverage' } })
// J03 剛好 5%：不算跳變（> 5 才算）
E('J03_step5', R(80, -1).concat([{ t: 61, soc: 79 - 1 / 60 - 5 }]), O({ now: 61 }), { status: 'OK', detail: { jump_at: null } })
// J04 E01 不受影響
E('J04_E01', R(80, -1), O(), { status: 'OK', detail: { jump_at: null, eta_min: 59, r2: 1 } })
// J05 R² 介於 0.5 與 0.8：交錯 ±0.2 的雜訊（R² 約 0.68，見下行計算）→ 舊門檻 0.5 會過、新門檻 0.8 不過
E('J05_r2_mid', R(80, -1).map((p, i) => ({ t: p.t, soc: p.soc + (i % 2 ? 0.2 : -0.2) })), O(), { status: 'INSUFFICIENT', detail: { reason: 'r2' } })
process.stdout.write(JSON.stringify({ version: 'g4-v4', chunks: [], glossary: {}, cases: { energy, telemetry: [], flightlog: [], alerts: [], manual: [] } }, null, 1))

===== 檔案結束：genui_m1v2/golden/make_vectors_v4.js =====


===== 檔案：genui_m1v2/golden/expect_overrides_v3_for_0.3.json（sha256 4a420be987ff125438be947d236f28a03630fb6f5c27c218bc964f0255d3e825）=====
{"note": "tools-m1-0.3 起（V3.1-2：R² 門檻 0.5→0.8，使用者 11/16 13:19 裁決）預期改變的 vectors_v3 案例。原 vectors_v3.json 不動。E18 的 R² 手算約 0.657，低於 0.8。",
 "E18_noise": {"status": "INSUFFICIENT", "detail": {"reason": "r2"}}}

===== 檔案結束：genui_m1v2/golden/expect_overrides_v3_for_0.3.json =====


===== 檔案：genui_m1v2/test/test_v3.js（sha256 4b52fdcb3c08b5833ecf99660694e06b10e176a805f551971e8503a3a6ff65a9）=====
// GenUI m1v2 固定案例第 3 版（gate-m1-0.3：T=1；tools-m1-0.3：跳變規則、R² 0.8）。執行：node genui_m1v2/test/test_v3.js
// 和 test_v2.js 的差別只有 T=1 那一案；其餘預期不變。
// 案例來源：契約附件 v3 §A-5、v3.1 草案 §A-3' 固定案例、Codex run2b §4-4、§4-5、§4-6、§4-1 E07、K-6。
// 預期值都由條文推導，在第一次執行前提交；執行一次，輸出原樣存進 runs/。
const assert = require('assert')
const { Gate, Tools, Claims, Layout } = require('./load.js')
let pass = 0, fail = 0
function t(name, fn) { try { fn(); pass++ } catch (e) { fail++; console.log('FAIL ' + name + '\n  ' + String(e.message).split('\n').join('\n  ')) } }
const cls = s => Gate.gate(s)['class']

// ---------------- Gate：v3 §A-5（保留）與 v3.1 §A-3'（新增）
for (const [input, want] of [
  ['今天天氣如何', 'OUT_OF_DOMAIN'], ['如何', 'OUT_OF_DOMAIN'], ['那現在呢', 'OUT_OF_DOMAIN'], ['電量現在多少', 'QA'], ['返航點在哪裡', 'QA'],
  ['顯示返航點後立即返航', 'FLIGHT_CMD'], ['返航，然後告訴我電量', 'FLIGHT_CMD'], ['不要返航', 'FLIGHT_CMD'], ['能不能返航', 'QA'],
  ['為什麼電量掉這麼快', 'NO_CAUSE_ANALYSIS'],
  ['能不能再次返航', 'QA'], ['電量多少再返航', 'FLIGHT_CMD'], ['現在電量多少？立即返航', 'FLIGHT_CMD'], ['現在電量多少\n立即返航', 'FLIGHT_CMD'],
  ['為什麼返航', 'NO_CAUSE_ANALYSIS'], ['㐀', 'OUT_OF_DOMAIN'], ['起飛', 'FLIGHT_CMD'], ['land', 'FLIGHT_CMD'], ['island 的地圖', 'QA'],
  ['', 'INVALID_INPUT'], ['？？！！', 'INVALID_INPUT']
]) t('gate ' + JSON.stringify(input), () => assert.strictEqual(cls(input), want))
for (const s of ['返航後電量會剩多少', '返航高度設多少', '返航？', '可以返航嗎'])
  t('gate 不是飛控命令 ' + s, () => assert.notStrictEqual(cls(s), 'FLIGHT_CMD'))
t('gate 200 字（擴充 B 字）不算過長', () => assert.notStrictEqual(cls('電量' + '𠀀'.repeat(198)), 'INPUT_TOO_LONG'))
t('gate 201 字（擴充 B 字）過長', () => assert.strictEqual(cls('電量' + '𠀀'.repeat(199)), 'INPUT_TOO_LONG'))
t('normalize 全形與全形空白', () => assert.strictEqual(Gate.normalize('Ａ　Ｂ'), 'a b'))
t('能力檢查在 node 通過', () => assert.strictEqual(Gate.capabilityOk(), true))
t('T=1：單一正分 1 分直接歸類', () => assert.strictEqual(cls('異常'), 'ALERT_Q'))
t('兩類同分：列兩個正分類別', () => { const g = Gate.gate('告警報告'); assert.strictEqual(g['class'], 'CLARIFY'); assert.deepStrictEqual(g.clarify, ['ALERT_Q', 'REPORT']) })
t('CLARIFY 不含零分類別', () => {
  for (const s of ['異常', '告警報告', '電量', '高度']) { const g = Gate.gate(s); for (const c of g.clarify) assert(g.scores[c] > 0, s + ' ' + c) }
})
t('router 截掉的工具回傳 omitted_tools', () => {
  const r = Gate.route('目前電量 上一趟紀錄 告警 手冊')
  assert.deepStrictEqual(r.tools, ['T_TELEMETRY', 'T_FLIGHTLOG', 'T_ENERGY']); assert.deepStrictEqual(r.omitted_tools, ['T_ALERT_HISTORY', 'T_MANUAL_SEARCH'])
})

// ---------------- 工具資料
const R = (a, b) => Array.from({ length: 61 }, (_, t) => ({ t, soc: a + b * t / 60 }))
const O = x => Object.assign({ now: 60, reservePct: 20, vehicleType: 'multirotor' }, x || {})
const e01 = () => Tools.energyTrend(R(80, -1), O())
t('E07 非有限保留值（下降）', () => { for (const v of [NaN, Infinity, -Infinity]) { const d = Tools.energyTrend(R(80, -1), O({ reservePct: v })).detail
  assert.strictEqual(d.reserve_invalid, true); assert.strictEqual(d.eta_min, null); assert.strictEqual(d.eta_reason, 'reserve_invalid'); assert(Math.abs(d.slope_pct_per_min + 1) < 1e-9) } })
t('E07 非有限保留值（持平）', () => { for (const v of [NaN, Infinity]) { const r = Tools.energyTrend(R(80, 0), O({ reservePct: v }))
  assert.strictEqual(r.status, 'OK'); assert.strictEqual(r.detail.direction, '持平'); assert.strictEqual(r.detail.reserve_invalid, true) } })
const tel = (v, t, now) => Tools.telemetryLatest('soc', '%', [{ t, value: v }], now)
const fl = Tools.flightlogSeries('alt', 'm', Array.from({ length: 61 }, (_, i) => ({ t: i, value: 10 + i })), 0, 60, [])
const alerts3 = Tools.alertHistory([{ t: 10, level: 'critical', predictor: 'p', text: 'a' }, { t: 20, level: 'warning', predictor: 'p', text: 'b' }, { t: 30, level: 'info', predictor: 'p', text: 'c' }], { t0: 0, t1: 60 }, [])
const man = Tools.manualSearch([{ chunk_id: 'k1', doc: 'D', heading: 'RTL', version: 'v1', text: '返航保留電量的設定方式：在參數頁設定 RTL 保留電量' },
                                { chunk_id: 'k2', doc: 'D', heading: '電池', version: 'v1', text: '電池廢棄處理：電量耗盡的電池請回收' }], '如何設定返航保留電量', {})
t('手冊：只中一個內容詞的片段不合格', () => { assert.strictEqual(man.status, 'OK'); assert.deepStrictEqual(man.facts.map(f => f.chunk_id), ['k1']) })
t('手冊：無關問題查不到', () => assert.strictEqual(Tools.manualSearch([{ chunk_id: 'k1', doc: 'D', heading: 'h', version: 'v1', text: '返航保留電量' }], '今天午餐吃什麼', {}).status, 'EMPTY_COMPLETE'))
t('手冊：chunk_id 是 constructor 之類的字也不出錯', () => assert.strictEqual(Tools.manualSearch([{ chunk_id: 'constructor', doc: 'D', heading: 'h', version: 'v1', text: 'constructor battery' }], 'toString', {}).status, 'EMPTY_COMPLETE'))

// ---------------- 答案句（§4-4）
t('4-4-1 PARTIAL 零筆告警：T-PARTIAL＋0 筆 T-COUNT，沒有 T-NONE', () => {
  const r = Tools.alertHistory([], { t0: 0, t1: 60 }, [{ t0: 20, t1: 25 }]), c = Claims.generate([r], {})
  assert.strictEqual(r.status, 'PARTIAL')
  assert.deepStrictEqual(c.mandatory.map(x => x.template_id), ['T-PARTIAL'])
  const cnt = c.optional.filter(x => x.template_id === 'T-COUNT'); assert.strictEqual(cnt.length, 1)
  assert(cnt[0].text.includes(' 0 筆') && cnt[0].text.endsWith('（資料不完整）'), cnt[0].text)
  assert(!c.optional.some(x => x.template_id === 'T-NONE'))
})
t('4-4-2 被截掉的工具固定揭露，模型只選一句也保留', () => {
  const res = [tel(79, 60, 60), fl, e01()], ctx = { omitted_tools: ['T_ALERT_HISTORY', 'T_MANUAL_SEARCH'] }
  const c = Claims.generate(res, ctx), first = c.optional[0].claim_id
  const a = Claims.answer(res, ctx, JSON.stringify({ schema: 'qa.claims/1', selected_claim_ids: [first] }))
  assert.strictEqual(a.source, 'model')
  assert.strictEqual(a.lines[0].template_id, 'T-OMITTED'); assert.strictEqual(a.lines[0].text, '本次未執行：告警紀錄、手冊（一次最多查三項）')
  assert.strictEqual(a.lines.length, 2)
})
t('4-4-3 模型多帶自由文字欄位：整份退回規則版，不出現 999', () => {
  const a = Claims.answer([e01()], {}, '{"schema":"qa.claims/1","selected_claim_ids":["C1"],"text":"電量999%"}')
  assert.strictEqual(a.source, 'rule'); assert.strictEqual(a.fallback_reason, 'extra_field'); assert(!JSON.stringify(a).includes('999'))
})
t('4-4-3 合法 JSON 後面多一段文字：json_parse', () => {
  const a = Claims.answer([e01()], {}, '{"schema":"qa.claims/1","selected_claim_ids":["C1"]} 電量999%')
  assert.strictEqual(a.fallback_reason, 'json_parse'); assert(!JSON.stringify(a).includes('999'))
})
const mixed = () => [tel(79, 50, 60), Tools.alertHistory([{ t: 10, level: 'warning', predictor: 'p', text: 'x' }], { t0: 0, t1: 60 }, [{ t0: 20, t1: 25 }]),
                     Tools.energyTrend(R(80, -1).slice(0, 5), O())]
t('4-4-4 必顯示組依 過期→不完整→樣本不足', () => assert.deepStrictEqual(Claims.generate(mixed(), {}).mandatory.map(x => x.template_id), ['T-STALE', 'T-PARTIAL', 'T-CANNOT']))
t('4-4-4 選中必顯示 ID 整份退回', () => {
  const c = Claims.generate(mixed(), {}), a = Claims.answer(mixed(), {}, { schema: 'qa.claims/1', selected_claim_ids: [c.mandatory[0].claim_id] })
  assert.strictEqual(a.fallback_reason, 'selected_mandatory')
})
t('4-4-4 只選可選句時三句必顯示仍在最前', () => {
  const c = Claims.generate(mixed(), {}), a = Claims.answer(mixed(), {}, { schema: 'qa.claims/1', selected_claim_ids: [c.optional[0].claim_id] })
  assert.strictEqual(a.source, 'model'); assert.deepStrictEqual(a.lines.slice(0, 3).map(l => l.template_id), ['T-STALE', 'T-PARTIAL', 'T-CANNOT'])
})
t('4-4-5 九個可選、一個必顯示：規則版 8 句、截掉 2、顯示告知', () => {
  const res = [tel(79, 50, 60), fl, alerts3], ctx = { thresholds: [{ subject: 'alt.max', value: 50, unit: 'm' }, { subject: 'alt.min', value: 50, unit: 'm' }] }
  const c = Claims.generate(res, ctx); assert.strictEqual(c.mandatory.length, 1); assert.strictEqual(c.optional.length, 9)
  const a = Claims.answer(res, ctx); assert.strictEqual(a.lines.length, 8); assert.strictEqual(a.claims_truncated, 2); assert.strictEqual(a.truncation_notice, '還有 2 項，見資料表')
})
t('過期又樣本不足：一句合併句', () => {
  const r = Tools.energyTrend([{ t: 0, soc: 80 }], { now: 10, checkStale: true, reservePct: 20 }), c = Claims.generate([r], {})
  assert.strictEqual(c.mandatory.length, 1); assert(c.mandatory[0].text.includes('已過期') && c.mandatory[0].text.includes('且樣本不足'), c.mandatory[0].text)
})
t('保留值 100：有「不估計剩餘時間」句，沒有 T-ETA', () => {
  const c = Claims.generate([Tools.energyTrend(R(80, -1), O({ reservePct: 100 }))], {})
  assert(c.optional.some(x => x.template_id === 'T-ETA-NA' && x.text === '目前電量已不高於保留電量，不估計剩餘時間')); assert(!c.optional.some(x => x.template_id === 'T-ETA'))
})
t('飛行紀錄數值用「該趟紀錄中」', () => assert(Claims.generate([fl], {}).optional.every(x => x.text.startsWith('該趟紀錄中'))))

// ---------------- 排版與 UiPlan 驗證（§4-5、K-6）
const k6res = () => [e01(), alerts3, Tools.manualSearch([{ chunk_id: 'k1', doc: 'D', heading: 'RTL', version: 'v1', text: '返航保留電量的設定方式' }], '返航保留電量', {})]
const k6 = () => { const res = k6res(), a = Claims.answer(res, {}); return { res, a, p: Layout.plan('r1', a, res) } }
t('K-6 計畫：W1、W2、W4、W3（必要 90）、W5', () => {
  const { p } = k6(); assert.deepStrictEqual(p.nodes.map(n => n.component_id), ['W1_FACT', 'W2_SERIES', 'W4_DIAG', 'W3_TABLE', 'W5_DOC'])
  assert.strictEqual(p.nodes[3].required, true); assert.strictEqual(p.nodes[3].priority, 90)
})
t('L05 趨勢圖綁到可畫的序列', () => {
  const { res, p } = k6(), w2 = p.nodes.find(n => n.component_id === 'W2_SERIES')
  assert.deepStrictEqual(w2.binding_ref, { request_id: 'r1', kind: 'series', ref: '0:F3' })
  const f = res[0].facts.find(x => x.fact_id === 'F3'); assert.strictEqual(f.points.length, 61); assert.deepStrictEqual(f.points[0], { t: 0, soc: 80 })
})
const L = (h, w = 1920) => { const { res, p } = k6(); return Layout.layout(p, { width: w, height: h, revision: 1 }, res) }
t('K-6 1920×1080 矩形', () => {
  const r = L(1080); assert(r.ok, r.error)
  const m = Object.fromEntries(r.layout.rects.map(x => [x.node_id, [x.x, x.y, x.width, x.height]]))
  assert.deepStrictEqual(m, { n1: [0, 0, 950, 240], n4: [966, 0, 950, 240], n3: [0, 256, 950, 240], n2: [966, 256, 950, 240], n5: [0, 512, 1916, 160] })
  assert.strictEqual(r.layout.total_height, 672)
})
t('K-6 1920×600 全部最小高度', () => { const r = L(600); assert.deepStrictEqual(r.layout.dropped, []); assert.strictEqual(r.layout.compact, true); assert.strictEqual(r.layout.total_height, 416) })
t('K-6 1920×500（Codex L06 更正）不刪、最小高度', () => { const r = L(500); assert.deepStrictEqual(r.layout.dropped, []); assert.strictEqual(r.layout.compact, true); assert.strictEqual(r.layout.total_height, 416) })
t('K-6 1920×400 拿掉 n5', () => { const r = L(400); assert.deepStrictEqual(r.layout.dropped, ['n5']); assert.strictEqual(r.layout.total_height, 304) })
t('K-6 1920×200 拿掉 n5、n2、n3', () => assert.deepStrictEqual(L(200).layout.dropped, ['n5', 'n2', 'n3']))
t('K-6 1920×120 拒絕', () => assert.strictEqual(L(120).error, 'REQUIRED_OVERFLOW'))
t('K-6 找不到「刪減後回建議高度」的高度（記為現有目錄觸發不到）', () => {
  for (let h = 1; h <= 1100; ++h) { const r = L(h); if (r.ok && r.layout.dropped.length) assert.strictEqual(r.layout.compact, true, 'h=' + h) }
})
const bad = (mut, code) => () => { const { res, p } = k6(); mut(p); const v = Layout.validatePlan(p, res); assert.strictEqual(v.ok, false); assert.strictEqual(v.error, code) }
t('L01 兩個 W2', bad(p => { p.nodes[4].component_id = 'W2_SERIES'; p.nodes[4].binding_ref = Object.assign({}, p.nodes[1].binding_ref) }, 'DUPLICATE_COMPONENT'))
t('L02 自創編號', bad(p => { p.nodes[1].node_id = 'custom'; p.order[1] = 'custom' }, 'NODE_ID'))
t('L03 component_id = toString', bad(p => { p.nodes[1].component_id = 'toString' }, 'NOT_IN_CATALOG'))
t('L03 size_class = toString', bad(p => { p.nodes[1].size_class = 'toString' }, 'SIZE_CLASS'))
t('L04 嚴重告警表改成非必要、0 分', bad(p => { p.nodes[3].required = false; p.nodes[3].priority = 0 }, 'PLAN_TAMPERED'))
t('節點帶 x', bad(p => { p.nodes[1].x = 0 }, 'NODE_UNKNOWN_FIELD'))
t('binding 多一個鍵', bad(p => { p.nodes[1].binding_ref.extra = 1 }, 'BINDING_INVALID'))
t('趨勢圖綁到計數事實', bad(p => { p.nodes[1].binding_ref.ref = '1:F1' }, 'BINDING_INVALID'))
t('只有 request_id 的 binding', bad(p => { p.nodes[1].binding_ref = { request_id: 'r1' } }, 'BINDING_INVALID'))
t('別的請求的資料', bad(p => { p.nodes[1].binding_ref.request_id = 'r2' }, 'BINDING_FOREIGN'))
t('沒給資料就不驗', () => assert.strictEqual(Layout.validatePlan(k6().p).error, 'NO_DATA'))
t('同一輸入兩次結果相同', () => assert.deepStrictEqual(L(1080), L(1080)))

console.log(`pass ${pass} / fail ${fail}`)
process.exit(fail ? 1 : 0)

===== 檔案結束：genui_m1v2/test/test_v3.js =====


===== 檔案：genui_m1v2/README.md（sha256 45d7f6f04928473edf10c1ca5cff333f12bf4f798797182973de385a4a766bf9）=====
# GenUI m1v2（探索，genui_m1 的下一版）

狀態：**探索**。舊版 `genui_m1/` 與它的 run 紀錄都不動。ADR-0001 仍是 Proposed；不接真模型。

依據：契約附件 v3（使用者已確認 V3-1～V3-9）、附件 v3.1 草案（未確認，只有 §K-3' 手冊引用的確認範圍由使用者 2026-11-16 12:48 裁決）、Codex 補核 run2a／run2b。

## 和 genui_m1 的差異

| 檔案 | 改了什麼 | 對應 |
|---|---|---|
| `qml/GenuiGate.js` | 能力檢查（無 NFKC 或碼位走訪就不啟用）；中文範圍含擴充字；子句只用標點、換行、多字連接詞切；逐一看飛控動詞是不是被問；規則 11 只取正分類別（`CLARIFY_ONE`）；Router 回傳 `omitted_tools` | v3.1 §A'；C-01、C-02；V3-F01、F02 |
| `qml/GenuiTools.js` | 電量：W 固定、保留值 0～100 含 100 且一律判定、過期與樣本不足都記、ETA 原因、邊界容差、輸出可畫序列 F3 與截距；飛行紀錄：同時戳保留到達順序、依時間等分 150 桶；手冊：排名前去重、內容詞過半才合格 | v3 §C、§L-3；v3.1 §C'、§D-6'、§L'；C-03～C-06、C-09、C-11 |
| `qml/GenuiClaims.js` | 每工具一句合併狀態句；「本次未執行」固定句；PARTIAL 0 筆計數句；`T-ETA-NA`；飛行紀錄措辭「該趟紀錄中」；截斷告知文字 | v3 §D-7；v3.1 §D-3'、§D-7'；C-07、C-08 |
| `qml/GenuiLayout.js` | binding_ref `{request_id, kind, ref}`；驗證器只看自有屬性、每種元件一個、編號依序、依資料重算 priority／required、需要資料才驗 | v3.1 §K-2'、§K-2''；C-10 |
| `golden/` | Python 對照版同步修改；比對器分清布林與數字；`vectors_v3.json` 用 Codex 列的確切輸入，預期值先寫好，`check_expect.py` 讓兩版各自比 | C-12～C-14 |
| `test/test_v2.js` | Gate、答案句、排版與驗證的固定案例 | Codex run2b §4-4～4-6、K-6 |

## 執行

```
node genui_m1v2/test/test_v2.js
node genui_m1v2/golden/run_js.js vectors_v3.json > js.json
python3 -I genui_m1v2/golden/reference.py vectors_v3.json > py.json
python3 -I genui_m1v2/golden/compare.py js.json py.json
python3 -I genui_m1v2/golden/check_expect.py genui_m1v2/golden/vectors_v3.json js.json   # py.json 也一樣
```

## 還沒做

- 沒在 QJSEngine 載入過；能力檢查與擴充字長度要在 Qt 上再驗。
- 畫面超支（§I）、交易提交點（§E'）、更新租約（§M）、Ollama 停止證據（§J）、告警計分（§F）都還沒有程式。
- 飛行紀錄的分頁、ROUTE、PROFILE、DEVIATION operation 未做。
- 手冊合格門檻 0.5、20% 是候選值〔待凍結〕。

## 0.3（2026-11-16 13:19 之後）

- Gate：T=1（calibration_v1 A1 凍結值）。
- 電量：使用者裁決 V3.1-2，R² 門檻 0.8、相鄰兩筆變化超過 5% 視窗重新起算（`detail.jump_at`）。
- 新增 `golden/vectors_v4.json`（跳變與 R² 案例）、`golden/expect_overrides_v3_for_0.3.json`（E18 因 R² 門檻改變而更新預期）、`test/test_v3.js`。

===== 檔案結束：genui_m1v2/README.md =====


===== 檔案：genui_m1v2/runs/m1v2_run1_20261116/RECORD.md（sha256 4cdf54be88e28d6487ab8438f1e2dffe87fc6e2e8ae5833f899de8a8fc74d28a）=====
# m1v2 run1（2026-11-16，台灣時間約 13:00）

- 程式：commit be4c05e（版本 gate-m1-0.2、tools-m1-0.2、claims-m1-0.2、layout-m1-0.2）。每項只跑一次，輸出原樣在本目錄。
- 固定案例 `test_v2.js`：**69 過、1 不過**。
- G4 第 3 版（Codex 列的確切輸入，31 案）：JS 與 Python 0 不同；JS、Python 各自和先寫好的預期值比，都 0 不符。
- G4 第 2 版輸入（82 案）用新程式重跑對照：0 不同。

## 不過的那一案

「手冊：只中一個內容詞的片段不合格」：預期只回 k1，實際兩個都不合格（查不到）。

事後診斷（另開指令看中間值，沒有重跑測試）：只有 2 個片段時，每個出現過的詞都超過「20% 片段」而被去掉；唯一留下的是兩個片段都沒有的「定返」，所以沒有觸發「一個都不剩就不做這一步」的退路，內容詞只剩一個誰都不會中的詞。這是 v3.1 §L' 的寫法本身的漏洞（只看「剩幾個」，沒看「剩下的詞有沒有出現在手冊裡」），不是測試寫錯。

## 處置

- 本次結果保留，不重跑。
- 修正放在下一版（tools-m1-0.2.1，新 run 目錄 m1v2_run2_20261116）：退路條件改成「去掉之後，沒有任何一個出現在手冊裡的詞」。v3.1 草案的這一句同步更正。

===== 檔案結束：genui_m1v2/runs/m1v2_run1_20261116/RECORD.md =====


===== 檔案：genui_m1v2/runs/m1v2_run4_20261116/RECORD.md（sha256 3623347f227185eaeacbf521b138a10c92ea9a617232f056dd7e88d6cd5951f6）=====
# m1v2 run4（2026-11-16，版本 0.3：T=1、跳變規則、R² 0.8）

- 程式 commit 見 ENV.txt。每項只跑一次。
- test_v3：70/0。
- G4：v2 82 案、v3 31 案、v4 5 案，JS 與 Python 都 0 不同。
- 對預期：v3 31 案 0 不符（E18 依已裁決條文改用新預期，見 expect_overrides_v3_for_0.3.json）。
- **v4 5 案 1 不符**：J03「剛好 5% 不算跳變」。兩版都回 jump_at=61。原因是**我寫的測資錯了**：跳後的值是 79 − 1/60 − 5，和前一筆 79 相差 5 + 1/60，本來就超過 5%。程式照條文做是對的，預期值是我手算時漏了那 1/60。
- 處置：本次保留不重跑；下一版測資另開 J03b（相差剛好 5.000）。

===== 檔案結束：genui_m1v2/runs/m1v2_run4_20261116/RECORD.md =====


===== 檔案：genui_m1v2/runs/qt_poc_run1_20261116/RECORD.md（sha256 114954e11604bb5f7faf8eb18df2159718dbb6100100ef224af5e4166f74e493）=====
# QJSEngine 載入 PoC 第 1 次（2026-11-16，雲端，PySide6 6.8.3＝筆電同版 Qt 6.8.3）

- 程式 commit 見 ENV.txt。只跑一次，輸出原樣保留（qt.json、node.json、compare.out）。
- **四個 `.pragma library` 檔都在 QML 裡載入成功**，沒有載入錯誤。
- 電量 29 案、K-6 排版 6 種高度、答案句、竄改檢查：Qt 與 node **完全相同**。
- **Gate 全部回 `GATE_CAPABILITY_FAIL`**：能力檢查不過，所以 169 句都沒判。

## 事後診斷（另跑小指令看引擎行為，沒有重跑 PoC）

| 寫法 | Qt 6.8.3 | node |
|---|---|---|
| `"Ａ".normalize("NFKC")` | A（正常） | A |
| `Array.from("𠀀").length` | **2**（按 UTF-16 切） | 1 |
| `[..."𠀀"].length`、`for…of` | 1（正常） | 1 |
| `Array.prototype.sort` 同值順序 | **不穩定** | 穩定 |

- 能力檢查發揮了作用：引擎的 `Array.from` 不照碼位切，Gate 拒絕啟用，而不是默默算錯長度。
- 修法：改用 `for…of` 走碼位；能力檢查改驗這個寫法。
- sort 不穩定：本版大部分排序已有明確的同值規則；`alertHistory` 只依時間排序，同一時間的告警順序在 Qt 上可能和 Python 不同，下一版補「同時間依到達順序」。
- 修正放下一版（gate-m1-0.2.1、tools-m1-0.2.2），新目錄 qt_poc_run2、m1v2_run3。

===== 檔案結束：genui_m1v2/runs/qt_poc_run1_20261116/RECORD.md =====


===== 檔案：genui_m1v2/runs/qt_poc_run2_20261116/RECORD.md（sha256 d1557273677a03aeb6e744f2a9b130e822eac2f074aa46b17bd72b2280c56f57）=====
# QJSEngine 載入 PoC 第 2 次（2026-11-16，PySide6 6.8.3）

- 程式 commit 見 ENV.txt（gate-m1-0.2.1、tools-m1-0.2.2）。只跑一次。
- 能力檢查通過；全形轉半形正常；擴充 B 字 200 字不算過長、201 字過長；㐀 判領域外。
- Gate 169 句、電量 29 案、K-6 六種高度、答案句、竄改檢查、同時間告警順序：Qt 與 node **逐位相同**。
- 唯一差異是探測項 `sort_stable`（Qt 的 sort 不穩定），這是引擎本身的性質，程式已不依賴它。
- 限制：這是雲端 PySide6，不是筆電上實際的 Qt 安裝；也還沒有畫面（QML 元件、GPU）部分。

===== 檔案結束：genui_m1v2/runs/qt_poc_run2_20261116/RECORD.md =====


===== 檔案：契約附件_v3.1b.md（sha256 85e7de35e4894c01275b9860bc9e47a08b02af4757243ec0fc0ba23289e9defc）=====
# ADR-0001 契約附件 v3.1b（草案）

> v3.1b：v3.1（sha256 d998e39a…ae5b）的更正版，v3.1 原檔不動。改了三處：§A-3' 兩列預期、§L' 退路條件、§K-3' 記上你的裁決。
> 撰寫：Claude，2026-11-16 台灣時間。依據：Codex 補核 run2a（附件 v3，V3-F01～F20）與 run2b（M1 程式，C-01～C14）。
> 性質：「AI 共同決定（使用者委任）」的草案。v3 兩部分原檔不動（第一部分 sha256 a2240994…95fc，第二部分 6164901f…42d3）；本檔只寫**取代或補充**的條文，沒寫到的照 v3。
> 你已確認的 V3-1～V3-9 全部保留，本檔沒有推翻任何一項。§K-3' 已由你在 12:48 裁決（見 decisions_v3_1.md）。
> 標〔待凍結〕的數值仍是候選值。ADR 維持 Proposed。

## 先看這裡：會影響使用感受的四件事

1. **問句裡的「再」「並」「後」不再切開句子**。「能不能再次返航」「返航後電量會剩多少」都當成問題回答；「電量多少再返航」仍當成飛控命令擋下來。問號、驚嘆號、換行改成分界。
2. **只有一種意圖但分數不夠時，只問你「是不是要 X」**，不再湊一個毫無根據的第二選項。
3. **一個工具最多一句狀態句**。例如資料又舊又不夠，會合成一句「資料已過期，且樣本不足」。沒執行的工具固定多一句「本次未執行：…」。
4. **畫面超支時，工作區換成一張靜態截圖**，原元件藏起來但不銷毀，這樣真的不再花繪製成本。

---

## A'（取代 v3 §A-2 第 9～11 條、§A-2b、§A-3 的切分與問句範圍；補 §A-0、§A-2a、§A-2c）

**A-0' 能力檢查（C-02）**
- 啟動時檢查 JS 引擎有 `String.prototype.normalize("NFKC")` 與依碼位走訪字串（`Array.from` 或 `for…of`）。任一項沒有：Gate 不啟用，所有輸入回固定句「問答功能無法啟動（引擎能力不足）」，記 `GATE_CAPABILITY_FAIL`。**不提供降級替代**。
- 「中文」的範圍：U+3400–4DBF、U+4E00–9FFF、U+F900–FAFF、U+20000–2FA1F。長度以碼位計算。

**A-2' 規則 9～11**

| 順序 | 規則 | 結果 |
|---|---|---|
| 9 | 沒有任何類別得正分 | `QA` |
| 10 | 最高分 ≥ T，且領先第二名 ≥ M（第二名沒有就當 0） | 該類別 |
| 11a | 剛好一個類別得正分，但未達 T | `CLARIFY_ONE`：問「是不是要 X？」，選項為「是」「取消」「改寫」 |
| 11b | 兩個以上類別得正分 | `CLARIFY`：列正分的前 2 類，同分依 v1 顯示順序 |

候選**只取正分類別**，不得為了湊數加入零分類別（V3-F01）。

**A-2a' 名詞例外表 v1.1**：「返航點、降落點、起飛點、返航高度、返航電量、返航速度、返航距離」（C-01，把程式已用的四個正式列入）。

**A-2b' 子句切分（V3-F02）**
- 分界只用標點與換行：`，,。．.；;、？?！!` 與換行。
- 多字連接詞照舊切：「然後」「之後」「接著」「並且」「再來」。
- **單字「再」「並」「後」不再當分界。**

**A-2c' 領域證據的第四個來源（C-01）**：飛控動詞詞庫本身也算領域證據，和其他三個來源一樣隨程式版本化凍結。這樣「能不能返航 → QA」維持原結果。

**A-3' 飛控動詞的問句範圍（V3-F02）**

一個子句在遮罩後命中飛控動詞時，逐一檢查每個命中位置：

- **算「被問」**，只要符合其一：
  - 動詞前面（中間最多隔 2 個字）有能力詞：能不能、可不可以、會不會、是否、能否、可以。
  - 動詞**後面**同一子句內出現疑問詞或句尾「嗎」「呢」「？」。
  - 動詞前面同一子句有原因詞（為什麼、為何、怎麼會）。這種句子之後在第 7 條回「此版本不提供原因分析」。
- 其他情況算「命令」。
- 任何一個命中位置是命令，該子句就是命令句，第 4 條判 `FLIGHT_CMD`。

固定案例（新增，每案一個預期）：

| 輸入 | 預期 |
|---|---|
| 能不能再次返航 | `QA` |
| 返航後電量會剩多少 | 不是 `FLIGHT_CMD`（意圖分數只有 1 分，照 A-2' 是 `CLARIFY_ONE`） |
| 電量多少再返航 | `FLIGHT_CMD` |
| 現在電量多少？立即返航 | `FLIGHT_CMD` |
| 顯示返航點後立即返航 | `FLIGHT_CMD`（照舊） |
| 為什麼返航 | 固定回「此版本不提供原因分析」 |
| 返航高度設多少 | 不是 `FLIGHT_CMD`（同上） |
| 㐀 | `OUT_OF_DOMAIN` |
| 「電量」＋198 個「𠀀」（200 字） | 不是 `INPUT_TOO_LONG` |
| 「電量」＋199 個「𠀀」（201 字） | `INPUT_TOO_LONG` |

---

## C'（補充 v3 §C 與 v1 C-2 第 3～7 步）電量

1. **W 固定 60 秒**〔待凍結〕，不接受呼叫端覆寫（C-06）。程式移除 `opts.W`。
2. **保留值判定一律執行**（C-03、C-04）：`reserve_pct` 是有限數字且 0 ≤ r ≤ 100 才有效，**100 有效**。不論之後是 OK、持平或任何提前結束，事實裡都要記 `reserve_valid` 與 `reserve_pct`。
3. **ETA 條件**：方向為下降、保留值有效、目前電量 > 保留值、ETA ≤ 600 分鐘〔待凍結〕。不成立時 `eta_min = null`，並記 `eta_reason`：`not_falling`／`reserve_invalid`／`at_or_below_reserve`／`over_limit`。
4. **數值邊界**：方向判定 |斜率| ≤ 0.05 + 1e-9 為持平；ETA 判定 ≤ 600 + 1e-9。
5. **多重失敗的優先序（C-05）**：所有檢查都做完，事實裡保留每一項結果（`stale`、`insufficient_reason`）。`status` 依「過期 → 樣本不足」取第一個；答案用一句合併句（§D-3'）。
6. **亂序比例的分母**：清理後、去重前、取視窗前的全部筆數。視窗外的樣本也算（照 v3，寫明以免誤讀）。
7. **事實要帶可畫的序列（C-09）**：輸出 `SeriesFact {fact_id, unit:"%", points:[{t, soc}]}`，內容是去重後視窗內的樣本。趨勢事實另帶 `{slope, intercept}`，畫回歸線用。

---

## D'（取代 v3 §D-3 的必顯示組計數；補 §D-6、§D-7）

**D-3' 必顯示組**
- 每個**已執行**的工具最多 1 句狀態句。同一工具有多個狀態時合成一句，依「過期 → 不完整 → 樣本不足 → 查不到」排列，例如「電量資料已過期，且樣本不足，無法估計趨勢」。
- 有工具被截掉時，固定 1 句「本次未執行：告警歷史、手冊（一次最多查三項）」，放在必顯示組最後。工具名照 Router 原排序。
- 所以必顯示組最多 4 句，可選組名額 = 8 − 實際句數（至少 4）。名額一律用**實際句數**算（V3-F05、C-08）。
- Router 回傳 `omitted_tools`，直接傳給答案組裝器，不經模型。

**D-6' T_FLIGHTLOG（V3-F06）**
- **讀取**：先把所有頁讀完再算，最多 64 頁（16,384 列）〔待凍結〕。超過上限就用已讀的資料計算，狀態 `PARTIAL`，句子帶「（資料不完整）」。
- **排序**：依 t 穩定排序，同一時戳**保留到達順序**，不去重（紀錄檔的原始列）。
- **統計**：最小、最大、平均、起始值、結束值都用區間 `[t0, t1]`（兩端都含）內的**全部原始有效值**計算，不用減量後的序列。
- **減量（只為顯示）**：超過 300 點時，把 `[第一筆 t, 最後一筆 t]` 等分成 150 桶；`桶號 = floor((t − t_first) ÷ 桶寬)`，最後一筆歸最後一桶。每桶輸出最小值與最大值兩點，依時間先後（同時戳依到達順序）；最小與最大是同一筆時只輸出一次；空桶不輸出。
- **PROFILE**：找到機型參數紀錄就 OK，欄位標「實測」或「假設」；找不到回 `UNSUPPORTED`。
- **DEVIATION**：航段 = 相鄰兩個有效航點（座標都有限、距離 > 0）。每個樣本輸出到最近有效航段的水平距離（公尺）。無效航點造成的斷裂記入缺口，狀態 `PARTIAL`；沒有任何有效航段 `INSUFFICIENT`。減量同 SAMPLES。
- 每個 operation 合法的狀態：METADATA {OK, ERROR}；SAMPLES、ROUTE、DEVIATION {OK, PARTIAL, INSUFFICIENT, ERROR}；PROFILE {OK, UNSUPPORTED, ERROR}。不在名單內的狀態視為 `ERROR`。

**D-7' 對照表補充（V3-F07、C-07）**

| 工具 | 狀態 | 事實 | 句型 | 組別 |
|---|---|---|---|---|
| 飛行紀錄 | OK／PARTIAL | 平均、起始值 | `T-VALUE`（措辭用「該趟紀錄中…」，不用「目前」） | 可選 |
| 飛行紀錄 | OK | PROFILE 參數 | `T-VALUE`，假設值句尾加「（假設值）」 | 可選 |
| 飛行紀錄 | OK／PARTIAL | DEVIATION 最大與平均距離 | `T-VALUE` | 可選 |
| 飛行紀錄 | OK／PARTIAL | ROUTE 航點數 | `T-VALUE` | 可選 |
| 飛行紀錄 | INSUFFICIENT | — | `T-CANNOT` | 必顯示 |
| 電量 | OK | 下降但 `eta_min = null` | `T-ETA-NA`「無法估計剩餘時間（原因）」，原因由 `eta_reason` 固定對應 | 可選，固定順序排在 `T-ETA` 後 |
| 告警歷史 | PARTIAL | 計數 = 0 | `T-COUNT`「已取得的資料中 0 筆（資料不完整）」 | 可選 |

---

## K'（補充 v3 §K）

**K-2' binding_ref 的 schema（V3-F08）**：`{request_id, kind, ref}`，多一個鍵就拒絕。

| 元件 | kind | ref | 必須符合 |
|---|---|---|---|
| W1_FACT | `answer` | 答案編號 | 本請求的答案 |
| W2_SERIES | `series` | SeriesFact 的 fact_id | 型別是 SeriesFact |
| W3_TABLE | `events` | 事件列的 fact_id | 型別是 EventList |
| W4_DIAG | `facts` | 1～2 個 fact_id 的陣列 | 都是門檻或 ETA 事實，且來自同一工具 |
| W5_DOC | `citations` | 1～5 個 chunk_id 的陣列 | 都在本次手冊結果裡 |

參照不存在、型別不符、或屬於別的請求：`BINDING_INVALID`。

**K-2'' 驗證器（C-10）**：只用自有屬性查表；每種元件最多一個；`node_id` 必須依節點順序是 n1、n2…；`priority` 與 `required` 由可信的建構器依 K-1 與資料**重算後比對**，不符就 `PLAN_TAMPERED`。

**K-3' 手冊引用的確認範圍（V3-F10，使用者本人 2026-11-16 12:48 裁決）**：答案區裡的引用與出處是答案的一部分，直接顯示；另外放進工作區的 W5_DOC 卡要按「套用」。

**K-3'' 按鈕綁定提案（V3-F10）**：「套用」按鈕的事件帶著畫面上顯示的 `transaction_id`。處理時只有和目前待確認提案的編號相同才提交；不同就忽略，記 `stale_click`。替換提案與更換按鈕編號在 GUI 執行緒上同一步完成。多把鎖同時存在時，優先序是 待確認鎖 → 互動鎖 → 情境穩定 → 同用途間隔。

**K-4' 列高（V3-F09）**：同一列的所有矩形高度都拉伸到該列列高；最小高度模式也一樣。K-6 的範例照此成立。

---

## I'（補充 v3 §I）

**I-1' 槽數**：值槽數 = 目前計畫的 binding 數，上限 32〔待凍結〕；計畫超過就在驗證時拒絕。喚醒交接採「先清旗標、再取值」，避免取完之後才到的值沒有人叫醒。

**I-3' OVERRUN_FROZEN 的做法（V3-F11）**：進入時把工作區**擷取成一張靜態圖**放在原位，原元件設為不可見（不銷毀），停止送畫格訊號給工作區。擷取失敗就直接隱藏工作區、顯示固定文字。凍結中如果仍連續 3 格超支，改成規則安全畫面（這時才銷毀工作區，且排在告警顯示之後）。

**I-3'' 恢復與停用（V3-F12）**
- 「當時正在工作的元件種類」可以是好幾種，全部記下（停用集合）。
- `RECOVERY_CHECK`：依排版順序每格恢復一個元件；**最後一個恢復後**開始算 30 秒；超支門檻與進入條件相同。
- 再超支：停用集合內的種類停用到重新啟動，規劃器之後不再選它們。停用集合含 W1_FACT，或必要元件被停用：整個工作區停用，答案改在骨架的固定文字區顯示（規則安全畫面）。
- `ALERT_PAUSED` 記下進入前的狀態，告警上了畫格就回到那個狀態；凍結的 5 秒照常計時。

---

## E'（補充 v3 §E）交易的提交點（V3-F13）

- 交易狀態只在一把共用的鎖裡改：`PREPARED → COMMITTING`（I/O 執行緒）與 `PREPARED → INVALIDATED`（GUI 執行緒）二選一，先到的贏。
- 進了 `COMMITTING` 才開始寫指標；之後才到的失效事件照 v3「指標已寫完、畫面還沒切換」那一列處理。
- `commit_intent` 紀錄改為 `{transaction_id, 舊指標, 新指標, 快照 sha256, 狀態}`。
- 安全事件打斷時，除了視窗大小，也要重查提案的安全條件（是否和告警區相交、必要元件是否還在）。

## N'（取代 v3 §N-4 的最後一句，V3-F14）

改為：每一案都不得自動啟用「沒有確認過、而且不符合 N-1 免確認條件」的版面；比對對象是實際排版結果。V3-3 不變。

---

## F'（取代 v3 §F-3 第 3 點；補 §F-1、§F-4，V3-F15、V3-F16）

- **合併**：同一 `(session, 機體, 預測器)` 的兩段，間隔 **≤ 5 秒**〔待凍結〕就合併。合併後相鄰兩段的配對窗不會重疊。
- **每段的結果三選一**：`HIT`（窗內有合格升起，第一個算）、`LOW_LEVEL`（窗內只有等級不足的升起）、`MISS`（沒有升起）。另列三個計數欄：重複升起數、等級不足升起數（含 HIT 段裡的）、誤報數。
- **對時公式**：四個時間戳，重放器送出 t1、Qt 收到 t2、Qt 回覆 t3、重放器收到 t4，單位奈秒整數。`偏移 = ((t2 − t1) + (t3 − t4)) ÷ 2`（Qt 減重放器），`來回 = (t4 − t1) − (t3 − t2)`。5 次取來回最小的一次，誤差界 = 來回 ÷ 2。來回 > 1 毫秒〔待凍結〕：整包 `ENV_INVALID`，首次結果保留。

## J'（補充 v3 §J-2、§J-3，V3-F03、V3-F04）

- **Windows（PC，必做）**：啟動器以「先暫停建立 → 放進 Job Object（設定關閉時結束全部）→ 再恢復執行」啟動專用 Ollama，這樣子程序無法在放進去之前跑掉。結束證據：Job 內作用中程序數為 0，且專用埠已釋放。
- **Linux（若筆電要跑）**：用新的 session 啟動，啟動器設為子程序收養者；結束證據：沒有任何程序屬於該 session，且埠已釋放。偵測到後代脫離 session 就停用桌面模型路徑。
- 兩個平台做不到上述查核：照 v3 J-3 第 4 點停用，不擴大到群組外程序。
- **正常完成**：收到 `done: true` 的最後一筆，且 HTTP 回應本體已結束（分塊傳輸的結尾）。**不要求底層連線關閉。** 收到 `done: true` 後 2 秒〔待凍結〕內沒有回應結尾，轉取消流程。
- 這仍是待 G5x 驗證的草案，U-06 不因本條關閉。

## L'（補充 v3 §L-3、§L-4，V3-F17、V3-F18、C-11）

- **順序**：兩條排名各自先去重（`chunk_id` → 同文件同 `text_sha256`），再各取前 50、排名從 1 起算；某片段不在某條排名裡，那一項貢獻 0；融合 → **合格篩選** → 取前 5。
- UI 語意融合的 k = 60〔待凍結〕。
- **合格的新定義**（取代 v3 §L-4 第一點）：
  - 先算查詢的「內容詞」：去掉一般疑問詞與停用詞表，再去掉出現在超過 20%〔待凍結〕片段裡的詞。去掉之後，剩下的詞沒有任何一個出現在手冊裡，就不做「去掉 20%」這一步（m1v2 run1 發現：片段很少時原寫法會只剩一個誰都不中的詞）。
  - 有向量時：語意相似度 ≥ `θ_sem`，**或**命中的內容詞 ≥ 內容詞數的一半（至少 1 個）。
  - 只有關鍵字（降級）時：命中的內容詞 ≥ 一半。
  - 例：「如何設定返航保留電量」的內容詞是返航、保留、電量；只講電池廢棄處理的片段只中「電量」（1/3），不合格。
- V3-9（沒有合格片段就回查不到）不變。

## M'（補充 v3 §M-1，V3-F19）

- **世代引用清單**：模型工作、向量工作、索引控制代碼、已掛載的元件、binding、排在 GUI 佇列裡的畫面提交、快照指標。
- 畫面提交在 GUI 執行緒**當下**重查世代；SWITCH 的發布也在 GUI 執行緒做，所以兩者不會交錯。舊世代的提交一律丟掉，記 `late_discard`。
- SWITCH 後，舊世代掛載的元件：若重排結果符合 N-1，直接換成新世代資料；不符合就換成規則安全畫面並產生恢復提案（要按套用）。
- 指標寫入結果不確定時，下次啟動讀回指標再驗；現行與前一組都驗不過：只開規則版，模型路徑停用。

## F-8～10'（V3-F20）

- 步數：第 30 步成功算通過，第 31 步起失敗。時間：從腳本收到第一個觀測到成功觀測，單調時鐘，≤ 120.000 秒算通過；同時發生算成功。
- 找不到目標：向下捲一頁，最多 5 次；再依固定順序切分頁；仍找不到算失敗。
- 讀取順序：先 y、再 x、再 `semantic_id`。同一畫面出現重複 `semantic_id`：該版 UI 標 `ENV_INVALID`。
- 報告第 8 欄接受「列表」或「查不到＋原因」。數值正確率以可追溯到事實欄位的數字計數；分母 0 記 `N/A`，不記 0 或 1；單位必須相同；容差：% 為 0.5、m 為 0.5、s 為 1〔待凍結〕。

---

## 只影響測試、不改條文的（給程式下一版）

- C-12：G4 對照改成「先由條文手算預期值，JS 與 Python 各自比對」，並比完整的電量事實與 coverage。
- C-13：重複時戳案例用不同數值；加入非零雜訊；版面預期附手算推導表。
- C-14：比對器先比 JSON 型別再比值（true 與 1 算不同）。
- Codex run2b 的 L06 前後矛盾（自己也標不可執行），不採用；改成先手算找出能觸發「刪減後回建議高度」的合法組合，找不到就記「現有目錄觸發不到」。

## 對照：每個問題落在哪一條

| 問題 | 條文 |
|---|---|
| V3-F01 | A-2' |
| V3-F02 | A-2b'、A-3' |
| V3-F03、F04 | J' |
| V3-F05 | D-3' |
| V3-F06 | D-6' |
| V3-F07 | C' 第 3 點、D-7' |
| V3-F08 | K-2' |
| V3-F09 | K-4' |
| V3-F10 | K-3'（已裁）、K-3'' |
| V3-F11、F12 | I-1'、I-3'、I-3'' |
| V3-F13 | E' |
| V3-F14 | N' |
| V3-F15、F16 | F' |
| V3-F17、F18 | L' |
| V3-F19 | M' |
| V3-F20 | F-8～10' |
| C-01、C-02 | A-0'、A-2a'、A-2c' |
| C-03～C-06、C-09 | C' |
| C-07、C-08 | D-3'、D-7' |
| C-10 | K-2'' |
| C-11 | L' |
| C-12～C-14 | 測試段 |

===== 檔案結束：契約附件_v3.1b.md =====


===== 檔案：run2b_codex-review（你上一輪的審查，閱讀副本）（sha256 f7d406baed926975f42987091fd7ce607491fd593cac8c9d1e35c5b4469a9650）=====
> 閱讀副本（經傳輸轉抄，縮排可能與原檔不同；原檔在 PC arch_review\design_gate\codex_review_v3_m1_20261116_b\run2b\codex-review.md，以原檔 sha256 為準）

# 判定：需修正後再進入

本次僅審查第三、四部分。**已有可由原文直接確認的契約差異；現有固定案例與 G4 對照不足以證明一致。** 這不表示探索程式不能保留，而是不能據此宣告 M1 契約驗證或 G4 已通過。

全程只讀取這則訊息，未使用工具、執行指令或寫入檔案。程式引用採檔名與函式名稱，避免替未附行號的內容編造行號。

另有一項材料限制：**貼文未包含 `M1_演算法說明_v2.txt` 全文。** 以下對電量後半段及 claim 模板，只就可見的 v3 條文明確判定；其餘保留為待核。

# 三、程式與契約不一致之處

## C-01｜Medium｜Gate 額外增加領域證據來源與名詞例外

**位置：** `GenuiGate.js` 的 `gate()`、`NOUN_EXCEPTIONS`。

**證據：**

- v3 第一部分 §A-2c 限定領域證據來自三個來源。
- `gate()` 另將 `matched(text, FLIGHT_VERBS)` 直接併入領域證據。
- 名詞例外比 §A-2a 多了「返航高度、返航電量、返航速度、返航距離」。

**反例：**「能不能拍照」會因問句判定避開第 4 條，再單憑 `FLIGHT_VERBS` 提供領域證據，最後進入 QA。這條領域證據的來源沒有在可見契約中正式列明。

四個參數名稱作為名詞有合理性，但「既有 preGate 已排除」不能直接代替新契約的詞庫定義。

**建議修法：** 將需要接受的能力名稱正式納入三個允許來源的版本化詞庫，並補列四個名詞例外。保留 §A-5「能不能返航 → QA」的既定案例，不應直接刪除動詞證據而使它失敗。

**其餘規則順序：** `gate()` 的第 1～11 條控制流程與可見 §A-2 基本一致。「只有一類低分，第二候選為 0 分」也是照現行第 11 條實作，**不是程式擅改契約**。問句、否定句的完整判定仍引用未附的 v1，無法全面核對。

## C-02｜Medium｜「中文」有效字元範圍較窄；正規化存在靜默降級

**位置：** `GenuiGate.js` 的 `gate()`、`normalize()`、`charLength()`。

**證據：**

- 有效內容檢查使用 `/[a-z0-9一-鿿]/`，未涵蓋 CJK 擴充字。
- 沒有 `String.normalize` 時，直接略過 NFKC。
- 沒有 `Array.from` 時，以 UTF-16 長度代替 Unicode 字元數。

**反例：** 單獨輸入中文漢字「㐀」會被判 `INVALID_INPUT`；按 §A-2，它有中文內容，應繼續檢查，因無領域證據而得到 `OUT_OF_DOMAIN`。

**建議修法：** 明訂並實作中文範圍；在固定 Qt 引擎驗證 NFKC 與字元計數能力。必要能力不存在時，應明確報能力檢查失敗，或提供符合契約的替代實作。

尚未看到證據顯示目標 QJSEngine 缺少這些 API；目前可確認的是程式存在上述降級分支。

## C-03｜High｜`reserve_pct = 100` 被錯判為無效

**位置：** `GenuiTools.js` 的 `energyTrend()` ETA 段；`reference.py` 的 `energy()`。

**證據：** v3 第一部分 §C 接受有限的 **0～100**；兩份程式都使用：

```text
reserve < 0 或 reserve >= 100
```

**反例：** 有充分下降樣本、`reservePct: 100` 時，程式記 `reserve_invalid = true`。契約要求它是有效保留值；是否輸出 ETA 是另一項判定。

**建議修法：** 上界改為 `> 100`，另按 ETA 規則決定是否產生時間。Python 對照版也有相同錯誤，因此原有一致結果無法排除此問題。

## C-04｜Medium｜固定電量分支漏記無效保留值

**位置：** `GenuiTools.js` 的 `energyTrend()` 零變異分支；`reference.py` 的 `energy()`。

**證據：** `syy === 0` 時直接回傳 `OK`；保留值驗證在後面，沒有執行。

**反例：** 61 筆充分、固定 80% 的樣本，搭配 `reservePct: -1`，會得到：

```text
status = OK
direction = 持平
reserve_invalid = false
```

最後一項違反 v3 §C。

**建議修法：** 將保留值合法性判定移到不會被「成功計算持平」提前返回略過的位置。ETA 仍可維持空值。

## C-05｜Medium｜過期優先於充分性，是目前可見材料未明定的選擇

**位置：** `GenuiTools.js` 的 `energyTrend()`；`reference.py` 的 `energy()`。

**證據：** 程式取完視窗後，先回傳 `STALE`，才檢查筆數、覆蓋率與缺口。

**反例：**

```text
samples = [{t: 0, soc: 80}]
opts = {now: 10, checkStale: true, reservePct: 20}
```

目前結果是 `STALE`，不會呈現「只有一筆、無法估計趨勢」。

**判定界線：** v3 §C 沒有明訂過期與充分性同時失敗時的優先序；未附的 M1 v2 或 v1 可能另有規定。**因此這是尚待對齊的行為，不能直接判違約。**

**建議修法：** 補明狀態優先序與診斷保留方式，再建立固定預期。不要只把現況輸出登記成標準答案。

另，`sxx === 0 → INSUFFICIENT` 目前不能判違約。在預設正視窗、去重、至少 10 筆及覆蓋率檢查成立後，所有時間相同的資料已不會走到這一分支。

## C-06｜Medium｜`W` 的輸入政策未完整處理，JS 與 Python 也不同

**位置：** `GenuiTools.js` 的 `energyTrend()`；`reference.py` 的 `energy()`。

**證據：**

- JS 接受有限數字 `opts.W`，沒有要求大於 0。
- `W = -1` 會產生空視窗，接著存取 `win[0].t`。
- Python 完全忽略 `opts.W`，固定使用 60 秒。

**反例：**

- 相同 61 筆資料、`W: 30`：JS 留 31 筆；Python 留 61 筆。
- `W: -1`：JS 存在未捕捉例外路徑。

**建議修法：** 若 W 是固定政策，移除呼叫端覆寫；若允許覆寫，兩版都驗證 `W > 0` 並使用相同值。這是程式 API 的實際差異，不能用目前沒有產生此輸入來排除。

## C-07｜Medium｜PARTIAL、觀測計數為 0 時漏掉 `T-COUNT`

**位置：** `GenuiClaims.js` 的 `generate()`。

**證據：** v3 第二部分 §D-7 規定告警歷史 `PARTIAL` 產生：

- 必顯示 `T-PARTIAL`。
- 帶「（資料不完整）」的可選 `T-COUNT`。
- 不產生 `T-NONE`。

程式的計數句要求 `f.value > 0`。

**反例：** 空告警列、有資料缺口時，只產生 `T-PARTIAL`，沒有「已取得資料中為 0 筆」的計數句。

**建議修法：** PARTIAL 的非負有效計數也產生帶不完整標記的 `T-COUNT`；仍禁止產生「沒有告警」。

## C-08｜High｜被截掉的工具沒有進入必顯示答案

**位置：** `GenuiGate.js` 的 `selectTools()`、`route()`；`GenuiClaims.js` 的 `generate()`、`answer()`。

**證據：**

- Router 只回前三個工具與 `tools_truncated`。
- Claims 沒有接收未執行工具清單的介面。
- v3 第二部分 §D-7 明定答案須列「本次未執行：…」，歸必顯示組。
- README 已坦承尚未實作。

**反例：** 現有測試「目前電量 上一趟紀錄 告警 手冊」截掉後續工具，只驗證工具數量及布林值，沒有驗證答案揭露缺項。

**建議修法：** 明確回傳 `omitted_tools`，傳入答案組裝器，固定顯示工具名稱。這項狀態不能交給模型選擇。其與每工具最多一句、最多三個工具的名額關係，也須寫清楚。

## C-09｜High｜能源趨勢圖沒有取得可繪製的序列

**位置：** `GenuiTools.js` 的 `energyTrend()`；`GenuiLayout.js` 的 `plan()`。

**證據：**

- `energyTrend()` 回傳趨勢 Fact 與目前值，沒有視窗樣本序列。
- `plan()` 遇 `T-TREND`，建立 `W2_SERIES` 並綁到趨勢 Fact。
- 該 Fact 有斜率、視窗及 R²，沒有序列點。
- §K-1 定義趨勢圖放「序列」。

**反例：** 現有「趨勢答案：W1＋W2＋W4」案例能產生 W2 節點，但沿其 binding 找不到時間／電量點列。

**建議修法：** 工具輸出明確的序列 Fact，W2 綁該序列。若要顯示回歸線，另明定回歸線資料與標示；單一斜率不能重建原始觀測序列。

## C-10｜High｜UiPlan 驗證未落實目錄與程式決定欄位的限制

**位置：** `GenuiLayout.js` 的 `validatePlan()`。

**證據：** §K-1、K-2 要求每種最多一個實例、節點編號由程式依序給、priority 與 required 由程式決定。驗證器目前僅檢查部分型別，未驗證：

- component_id 不重複。
- `node_id` 為依序的 `n1`、`n2`……。
- priority 符合目錄與告警條件。
- 必要性符合資料事實。

此外，`CATALOG[n.component_id]` 與 `SIZE_CLASS_COLS[n.size_class]` 使用一般物件屬性查找，會將 `toString` 等繼承屬性當成存在。

**反例：**

- 將節點 component 改成第二個 `W2_SERIES`，可通過。
- 將 `component_id` 改成 `"toString"`，不會得到預期的 `NOT_IN_CATALOG`。
- 將已知含嚴重告警的 W3 改成非必要、低分，驗證器不能發現其被竄改。

**建議修法：** 使用明確自有屬性檢查，驗證實例唯一與編號；從可信資料重新計算 priority／required，或只接受可信 builder 的輸出並在邊界驗證。

正常 `plan()` 會填入正確值；尚未證明模型可以直接控制整份 UiPlan。此處是**驗證契約未完成**，不是已證實的模型利用路徑。

## C-11｜Medium｜關鍵字檢索未實作 §L-3 去重

**位置：** `GenuiTools.js` 的 `manualSearch()`；`reference.py` 的 `manual()`。

**證據：** 兩版都是直接排序、取前五個，沒有依 `chunk_id` 或「同文件＋相同文字 hash」去重。

**反例：** 同文件的相同片段以不同 chunk_id 出現，會重複占用顯示名額。

**建議修法：** 在明定的檢索階段執行兩層去重。M1 只有關鍵字、標「降級」符合目前探索範圍，但這不能當成 §L-3 已完成；若去重由上游保證，需補上明確介面前置條件及驗證。

## C-12｜High｜G4 對照不能作為獨立正確性證據

**位置：** `reference.py` 的 `energy()`、`run_js.js`、`G4_RUN1_RECORD.md`。

**證據：**

- 兩版共享 `reserve >= 100`、零變異提前返回等問題。
- 電量步驟、提前返回位置及原因碼高度一致。
- 電量只比對 `status`、`detail`、`covered`，**沒有比對 Fact 內 ETA、保留值、假設標記、單位及完整 coverage**。

**判定：** 無法從貼文證明 Python 的撰寫過程是直接翻譯，也不能認定真正獨立。它有使用不同資料結構與寫法；但共享錯誤已足以說明：**兩邊一致不能驗證契約正確。** 對照仍有跨語言差異偵測價值，並非完全沒有意義。

**建議修法：** 補入先由契約及解析計算寫好的預期值，要求兩版各自符合；擴充電量 Fact 與 coverage 比對，不能只比較摘要。

## C-13｜Medium｜固定案例有弱斷言，向量產生器的雜訊維度實際未變動

**位置：** `test_m1.js`、`make_vectors.js`。

**證據與反例：**

1. 「時間戳重複只留最後到達的一筆」原始末筆已是 79，新增末筆仍是 79。即使錯誤地保留第一筆，測試也會過。
2. 雜訊索引是 `(i * 5) % 5`，對整數 i 永遠為 0；因此所有生成案例的 noise 都是 0。
3. `RUN1_RECORD.md` 明確記載幾何預期曾改成實際輸出。

**對「抄預期值」的判斷：** 紀錄證實幾何預期有依實際輸出修正，首次預期也未按演算法推導；但目前 1920×1080 的數值可從 §K-4 手算得到，600／400／200／120 的結果亦相符。**不能因此直接認定目前這些預期值錯誤。** 缺的是獨立推導與首次執行證據。

**建議修法：** 重複樣本使用不同數值；加入明確指定的非零雜訊案例；保留原 run，補上不依賴實際輸出的版面推導表。

## C-14｜Low｜比對器沒有嚴格區分布林與數字

**位置：** `compare.py` 的 `same()`。

**證據：** 遇到 bool 時使用 `a != b`；Python 中 `True == 1`、`False == 0`。

**反例：**

```text
JS：{"X":{"value":true}}
PY：{"X":{"value":1}}
```

可能被當成相同。

**建議修法：** 先核對 JSON 型別，再做值比較與數值容差判定。

---

另有幾項目前可正面確認的部分：

- **Claims 選擇邊界：** `validateSelection()` 會拒絕多餘欄位、非字串 ID、未知 ID、選中必顯示 ID、壞 JSON、空選擇及超額；成功後 `render()` 取程式建立的候選句。可見正常路徑中，**沒有模型自由文字或模型自填數字直接進入答案的路徑**。手冊原文、工具資料與 ctx 仍須由呼叫端保證來源。
- **必顯示順序與名額：** 可見實作符合「過期→不完整→樣本不足→查不到」及 `8 − mandatory.length`；無可選句時走固定答案。模型逾時與「不呼叫模型」的編排層未附，尚未驗證。
- **Layout 主演算法：** `layout()` 的排序、分列、剩餘欄數給第一個、先建議高度再最小高度、刪一個後重新分列，與 §K-4 相符。剩餘欄數只會增加尺寸，未見它使其他元件小於最小欄數的反例。
- **GenuiHash：** 對合法 Unicode 輸入未從靜態閱讀找到明確演算法差異；未執行驗證。RouteRecord 完整契約引用 v1，無法全面核對。
- `claims_truncated` 有回傳數量，但「還有 n 項，見資料表」的實際畫面沒有附上，不能認定已顯示。

# 四、需要 Claude 執行的檢查

以下均為**待執行**。新增輸入、版本及 run 目錄，原 G4 輸入與結果保留。每案先保存預期與推導，再執行並保留首次輸出。

為簡潔且確定地描述輸入，使用下列數學記法：

```text
R(a,b)：
依 t = 0,1,…,60 的順序，各一筆 {t, soc: a + b×t/60}。
b 是每分鐘變化量。

預設 opts：
{now:60, reservePct:20, vehicleType:"multirotor"}
```

所有未另指定的輸入均使用上述 opts。

## 4-1 電量：優先補進 JS／Python 對照

| 案例 | 確切輸入 | 預期輸出／檢查 |
|---|---|---|
| E01 正常 ETA | `R(80,-1)` | OK；斜率 −1；R²=1；下降；目前 79%；ETA=59 分鐘。趨勢 Fact 也須有 `eta_min:59`、`reserve_pct:20`。 |
| E02 假設值 | E01，加 `reserveAssumed:true` | ETA 仍為 59；Fact 假設標記為 true；Claims 的 ETA 句固定附「（依假設保留值估計）」。 |
| E03 保留值上界 | E01，`reservePct:100` | `reserve_invalid:false`；斜率與方向照算。依目前 ETA 政策不輸出 ETA。 |
| E04 保留值下界 | E01，`reservePct:0` | `reserve_invalid:false`；ETA=79。 |
| E05 無效值與下降 | E01，分別用 `-1`、`100.1`、`null` | 斜率 −1、下降；`reserve_invalid:true`；ETA 空值。 |
| E06 無效值與固定電量 | `R(80,0)`，分別用上述三個無效值 | OK；持平；斜率 0；R²空值；`reserve_invalid:true`；ETA 空值。 |
| E07 非有限保留值 | JS 直接呼叫，保留值分別為 NaN、Infinity | 與 E05／E06 對應結果相同。不可透過 JSON 將它們轉成 null 後宣稱覆蓋。 |
| E08 充分缺口 | 從 E01 移除 `t=21…30` | INSUFFICIENT；reason=`gap`；最大缺口 11 秒；不輸出趨勢或 ETA。 |
| E09 缺口邊界 | 從 E01 移除 `t=21…29` | 最大缺口 10 秒，其他條件充分；OK、下降、ETA=59。 |
| E10 上升 | `R(50,0.5)` | OK；斜率 +0.5；R²=1；上升；ETA 空值。 |
| E11 真正的覆寫測試 | E01 原本 `t=60` 改為 78，再於末尾追加 `{t:60,soc:79}` | 去重後 61 筆；末值 79；斜率 −1；R²=1；ETA=59。 |
| E12 可變 W | E01，加 `W:30` | 若保留此 API：31 筆、covered=[30,60]、requested=[30,60]、斜率 −1、ETA=59。JS／Python 均須符合。 |

E01、E02 的預期可用等速下降解析計算，不需取任一實作的輸出當標準答案。

下列邊界使用程式目前的 600 分鐘候選政策；**須在未附的 M1 v2 或補充條文確認該政策後，才能作為契約驗收案**：

```text
i = 0…16
t_i = 3.75×i
soc_i = 57.5625 − i/256
reservePct = 20，now = 60
```

預期斜率 −0.0625 %/min、末值 57.5%、ETA=600。將所有 soc 加 0.0625，理論 ETA=601，依目前政策應不輸出。這也能檢查浮點誤差是否使 600 的邊界被誤排除。

## 4-2 亂序：驗證分子、分母與處理順序

定義：

```text
B：t=0…99，soc=80−t/60，共100筆，依t遞增到達。
S(k)：從B出發，對 j=0…k−1，
交換到達位置 4j+1 與 4j+2 的兩筆。
opts.now=99，reservePct=20。
```

| 案例 | 輸入 | 預期 |
|---|---|---|
| O01 20% | `S(20)` | disorder_ratio=20/100=0.2；不因亂序拒絕；OK。 |
| O02 21% | `S(21)` | disorder_ratio=21/100=0.21；INSUFFICIENT；reason=`disorder`。 |
| O03 清理先於分母 | `S(20)` 末尾追加 `{t:101,soc:50}` | 未來超過容忍值，丟掉一筆；比例仍為 20/100，不能變成 20/101。 |
| O04 去重前計算 | `S(20)` 末尾追加 `{t:50,soc:80−50/60}` | 新增一筆亂序；比例=21/101，超過 20%；INSUFFICIENT。 |
| O05 等時戳不算亂序 | `S(20)` 末尾追加與 t=99 相同的一筆 | 比例=20/101；去重後視窗 61 筆；OK。 |
| O06 視窗外仍計入亂序 | 先到達 t=−981、−982、…、−1000 的20筆，soc均80，再到達 E01 | 前段19筆亂序；比例=19/81；即使最後視窗正常，仍須因亂序拒絕。 |

這六案直接依 v3 §C 推導，應加入 G4，不能只留在 JS 單邊測試。

## 4-3 尚須先明訂預期的電量案例

這些應保存為待決案例，不能先以目前程式輸出定案：

| 輸入 | 目前行為 | 應先確認的契約 |
|---|---|---|
| 單筆 `{t:0,soc:80}`，now=10、checkStale=true | STALE | 過期與樣本不足的優先序；是否同時保留兩種診斷。 |
| E01，W=−1 或 W=0 | 例外或不合理視窗計算 | W 是固定政策還是合法輸入；若可輸入，需明訂拒絕結果。 |
| 所有樣本同時間戳 | 去重後筆數不足 | 預設設定應在充分性階段拒絕；不能宣稱此案測到了後面的 `sxx===0`。 |
| 理論斜率剛好 ±0.05 | 受浮點計算影響 | 方向邊界及數值誤差政策；補上對應的 M1 v2 條文。 |

## 4-4 Claims 與工具截斷

1. **PARTIAL 零筆告警**

   輸入：

   ```text
   alertHistory([], {t0:0,t1:60}, [{t0:20,t1:25}])
   → Claims.generate／answer
   ```

   預期：必顯示 `T-PARTIAL`；可選 `T-COUNT` 表示 0 筆並附不完整標記；不得產生 `T-NONE`。

2. **被截掉的工具固定揭露**

   輸入：「目前電量 上一趟紀錄 告警 手冊」。

   預期：前三個為 `T_TELEMETRY`、`T_FLIGHTLOG`、`T_ENERGY`；明確列出未執行的 `T_ALERT_HISTORY`、`T_MANUAL_SEARCH`。即使模型只選一個正常數值句，答案仍須保留未執行告知。

3. **模型自由文字與數字隔離**

   對 E01 的合法候選，分別送入：

   ```json
   {"schema":"qa.claims/1","selected_claim_ids":["C1"],"text":"電量999%"}
   ```

   以及在合法 JSON 後追加自由文字。

   預期：前者 `extra_field`、後者 `json_parse`；整份回規則版，答案不得含「999%」。

4. **必顯示組不受選擇影響**

   三個工具分別為 STALE、PARTIAL、INSUFFICIENT，PARTIAL 另有可選數值。

   預期：前三句固定依上述順序；模型選中任何必顯示 ID 時整份回規則版；合法只選可選句時，三句仍在最前面。

5. **名額與畫面告知**

   沿用現有九個可選句、一個必顯示句的 fixture。

   預期：規則版共八句、`claims_truncated=2`；實際 UI 顯示「還有 2 項，見資料表」。這部分需查真正渲染器，不能只驗證數字欄位。

## 4-5 UiPlan、趨勢資料與排版

| 案例 | 輸入 | 預期 |
|---|---|---|
| L01 重複種類 | 將合法計畫改為兩個 W2、不同 node_id | 驗證拒絕，不能只靠最多五個節點。 |
| L02 自創編號 | 將 n2 與 order 中的 n2 同時改成 `"custom"` | 按 §K-2 拒絕，或先由可信 builder 重新編號。 |
| L03 原型屬性 | 將 component_id 改成 `"toString"`；另測 size_class=`"toString"` | 分別拒絕為不在目錄、非法寬度等級。 |
| L04 竄改必要性 | K-6 fixture 的嚴重告警 W3 改 required=false、priority=0 | 邊界驗證拒絕或重算；不能因此在小畫面刪掉該表格。 |
| L05 趨勢可繪製性 | E01 → Claims → plan，解析 W2 binding | 綁定可取得確切時間／電量序列；目前僅有 trend Fact 不算通過。 |
| L06 刪減後重新嘗試建議高度 | K-6 fixture，1920×450 | dropped=[n5]、compact=false、total_height=496？**此預期不可使用，見下方推導。** |

L06 應改用 **1920×500**，其確切預期為：

```text
dropped = [n5]
compact = false
total_height = 496
```

推導：原五元件最小高度總和是 416，會直接放得下，因此 **500 並不會觸發刪減**。所以也不能用它測到「刪減後回建議高度」。

這指出一個測試設計限制：**K-6 這組元件無法直接靠上述高度測到該分支。** 應另設合法 fixture，先手算出「刪減前最小總高 > H、刪減後建議總高 ≤ H」的條件，再固定輸入與預期；若目前目錄不存在此組合，應記為不可由合法目錄觸及，不能編造通過案例。

> 上述 L06 的數值推導用來排除錯誤測資，不列為可執行驗收案。其餘 L01～L05 可直接補測。

另應在實際 QJSEngine／QML 中載入 `.pragma library`，驗證：

```text
normalize("Ａ　Ｂ") = "a b"
「電量」＋198個「𠀀」：共200字，不得 INPUT_TOO_LONG
「電量」＋199個「𠀀」：共201字，應 INPUT_TOO_LONG
gate("㐀") = OUT_OF_DOMAIN
```

## 4-6 手冊去重、G4 比對範圍與工具邊界

**手冊去重固定案：**

四筆片段依序為：

```text
c01：doc=D1，text="battery"
c01：與第一筆完全相同
c02：doc=D1，text="battery"
c03：doc=D2，text="battery"
```

查詢 `"battery"`。預期去重後只保留 `c01`、`c03`；不限定此案的 BM25 分數，因去重在哪個階段執行須先固定。此案不涉及向量模型。

**比對器型別案：**

```text
js.json = {"X":{"value":true}}
py.json = {"X":{"value":1}}
```

預期：一案不同、非零結束碼。

**飛行紀錄同時戳分桶案：**

```text
前兩筆：{t:0,value:0}、{t:0,value:10}
其後：t=1…299，各筆value=5
field=alt，unit=m，t0=0，t1=299，gaps=[]
```

在同時戳排序保留到達順序的環境，JS 第一桶會輸出最大值再最小值；Python 依原位置輸出最小值再最大值。兩版可能不同。

預期至少須保留兩個極值；**同時戳的順序須先補契約，才能設定唯一的完整序列預期。** 現有向量產生器的飛行紀錄沒有同時戳，沒有覆蓋此差異。

G4 新版還應比較能源完整 Fact 與 coverage，並明確檢查新案例真的出現 ETA、gap、disorder、上升與非零雜訊。`METADATA`、`ROUTE`、`PROFILE`、`DEVIATION`、分頁完成判定及真實紀錄仍須另外完成；現有程式與報告已承認它們未完成。

---

**未見材料與本次界線：** 未見 M1 演算法說明 v2、附件 v1／v2、候選 ADR 全文、domains 原始詞庫、實際 `vectors.json` 與 G4 原始輸出、Qt 版本及正式 UI／編排層。因此，v1 才有的充分性細節、零變異、直線、方向、ETA 規範與 claim 完整模板表，不能宣告已核對；執行紀錄中的 103／0、120／0 也僅能視為貼文所載結果。

===== 檔案結束：run2b_codex-review（你上一輪的審查，閱讀副本） =====
