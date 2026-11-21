.pragma library
// GenUI M1 規則版：Domain Gate 與 Task Router（純 JS，不依賴 Qt 物件，可用 node 測試）。
// 版本 m1v2：依契約附件 v3.1 草案 §A-0'、A-2'、A-2a'～c'、A-3'（尚未經使用者確認）修改 Gate；舊版 genui_m1/ 不動。
// 依據：契約附件 v3 第一部分 §A（Gate）、附件 v1 §B（Router）、v3 §B（沒有模型選參數階段）。
// M1 只有第 1 層規則，source 一律是 "rule"；不呼叫模型、不算 embedding。
// 所有門檻都是候選值〔待凍結〕，校準包跑完才凍結。

var POLICY_VERSION = "gate-m1-0.5"   // 0.5：F2 偏離航線意圖（規則 5a、8a；說明 f2_deviation_v1/F2_接進問答流程_說明_v2，使用者 11/21 12:51、13:11 裁決）
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
var CAPABILITY_GAP_MAX = 3   // v3.1c G2：碼位數（使用者 11/18 20:58「v3.1c 照草案」）
// 一般疑問詞：只用來判問句，不算領域證據，意圖權重為 0（v3 §A-2c）
var QUESTION_WORDS = ["怎麼", "如何", "為什麼", "為何", "哪", "多少", "幾", "什麼", "是否", "能不能", "可不可以", "會不會"]
var QUESTION_ENDINGS = ["?", "？", "嗎", "呢"]
var CAUSE_WORDS = ["原因", "為什麼", "為何", "怎麼會"]           // 規則 7（問原因）用
var CAUSE_PREFIX = ["為什麼", "為何", "怎麼會"]                  // v3.1c G2 第 5 點：動詞前的原因詞，不含「原因」
var COMMAND_MARKERS = ["請", "立即", "立刻", "馬上", "給我"]      // v3.1c G3
var TOPIC_CONNECTIVES = ["之後", "然後"]                          // v3.1c G4

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

// F2 偏離航線意圖（說明 v2 §2-1、§6）：線索＋航線指涉；GPS 類詞只有航線詞能保留（紀錄詞不算）
var DEV_CUES = ["偏離", "偏多遠", "偏了多遠", "偏了多少", "偏多少", "偏移", "離航線", "離規劃航線"]
// 有 GPS 類詞時，只有「偏移／偏離」直接接著航線的說法才算問航線偏離（「航線上的 GPS 偏移」是定位偏移）
var DEV_ROUTE_PHRASES = ["偏離航線", "偏離規劃", "偏離任務", "偏離路線", "偏移航線", "離航線", "離規劃航線"]
var DEV_ROUTE_WORDS = ["航線", "規劃", "任務", "航點", "路線"]
var DEV_RECORD_WORDS = ["上一趟", "最近一次", "這趟"]
var DEV_SENSOR_WORDS = ["gps", "定位", "位置", "羅盤", "磁力計", "訊號"]
// R-7：明確指定拿目前載入的航線比較（要同時有比較詞）
var DEV_CURRENT_ROUTE = ["目前載入的航線", "目前的航線", "目前航線", "現在的航線", "載入的航線", "這條航線"]
var DEV_COMPARE_WORDS = ["比較", "對照", "比"]
// R-2／R-5：同句另外問的事（這次不查，W1 請使用者另問）。即時遙測不列（「目前載入的航線」會誤中）。
var DEV_OTHER_ASKS = [
    { name: "飛行時間", any: ["飛了多久", "飛多久", "飛行時間", "飛行時長"] },
    { name: "電量", any: ["電量", "電池", "剩多久", "掉多快"] },
    { name: "告警", any: ["告警", "警告", "異常", "有沒有問題"] },
    { name: "手冊", any: ["怎麼設定", "是什麼意思", "手冊", "參數"] }
]
function deviationIntent(input) {
    var text = normalize(input), cues = matched(text, DEV_CUES), route = matched(text, DEV_ROUTE_WORDS), rec = matched(text, DEV_RECORD_WORDS)
    var sensor = matched(text, DEV_SENSOR_WORDS)
    var out = { hit: false, cues: cues, route_words: route, record_words: rec, sensor_words: sensor, basis: "record_check", other_asks: [] }
    if (!cues.length || !(route.length || rec.length)) return out
    if (sensor.length && !matched(text, DEV_ROUTE_PHRASES).length) { out.excluded = "sensor"; return out }
    out.hit = true
    if (matched(text, DEV_CURRENT_ROUTE).length && matched(text, DEV_COMPARE_WORDS).length) out.basis = "current_loaded"
    for (var i = 0; i < DEV_OTHER_ASKS.length; ++i) if (matched(text, DEV_OTHER_ASKS[i].any).length) out.other_asks.push(DEV_OTHER_ASKS[i].name)
    return out
}

// ---------------------------------------------------------------- 小工具
// 依碼位切字串。Qt 6.8.3 的 Array.from(字串) 會按 UTF-16 切（qt_poc_run1 發現），所以用 for…of。
function codePoints(s) { var out = []; for (var ch of s) out.push(ch); return out }
// 能力檢查（v3.1 §A-0'）：沒有 NFKC 或碼位走訪就不啟用 Gate，不做降級替代。
// 另依賴 String.prototype.codePointAt（hasContentChar 用；v3.1c G6 明寫）。
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
    // 長的優先；同長度依詞表原順序（v3.1c G6，不依賴 sort 是否穩定）
    var ex = NOUN_EXCEPTIONS.slice().sort(function (a, b) { return b.length - a.length || NOUN_EXCEPTIONS.indexOf(a) - NOUN_EXCEPTIONS.indexOf(b) })
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
        if (p) out.push({ text: p, q: QUESTION_MARKS.indexOf(sep) >= 0, sep: sep })
    }
    return out
}
function splitClauses(text) { var c = splitClausesQ(text), out = []; for (var i = 0; i < c.length; ++i) out.push(c[i].text); return out }
// 子句裡每個飛控動詞的位置是不是「被問」（v3.1b §A-3'、v3.1c G2～G4）。回傳命令用的動詞清單（空 = 沒有命令）。
// 位置一律用碼位計算（v3.1c G2 第 1 點）。next：下一個子句（判 G4 用），可省略。
function cpIndexOf(cps, term, from) {
    var t = codePoints(term)
    for (var i = from || 0; i + t.length <= cps.length; ++i) {
        var ok = true
        for (var j = 0; j < t.length && ok; ++j) if (cps[i + j] !== t[j]) ok = false
        if (ok) return i
    }
    return -1
}
function cpLastEnd(cps, term, before) {   // term 在 [0, before) 內最後一次出現的結尾位置；沒有回 -1
    var t = codePoints(term), best = -1
    for (var i = 0; i + t.length <= before; ++i) { var k = cpIndexOf(cps, term, i); if (k < 0 || k + t.length > before) break; best = k + t.length; i = k }
    return best
}
function commandVerbs(clause, next) {
    var text = clause.text, cps = codePoints(text), cmds = []
    var trimmed = text.replace(/\s+$/, ""), endsQ = clause.q || /[嗎呢]$/.test(trimmed)
    for (var v = 0; v < FLIGHT_VERBS.length; ++v) {
        var verb = FLIGHT_VERBS[v], vlen = codePoints(verb).length, at = cpIndexOf(cps, verb, 0)
        while (at >= 0) {
            var before = cps.slice(0, at).join(""), after = cps.slice(at + vlen).join("")
            var wordOk = isAsciiWord(verb) ? (!/[a-z0-9]/.test(at > 0 ? cps[at - 1] : " ") && !/[a-z0-9]/.test(at + vlen < cps.length ? cps[at + vlen] : " ")) : true
            if (wordOk) {
                var asked = false
                // G3 明確命令優先：同子句、動詞前有命令標記 → 一律命令
                if (!matched(before, COMMAND_MARKERS).length) {
                    for (var k = 0; k < CAPABILITY_WORDS.length && !asked; ++k) {
                        var e = cpLastEnd(cps, CAPABILITY_WORDS[k], at)
                        if (e >= 0 && at - e <= CAPABILITY_GAP_MAX) asked = true
                    }
                    if (!asked && (endsQ || matched(after, QUESTION_WORDS).length)) asked = true      // 嗎／呢／問號只在子句尾
                    if (!asked && matched(before, CAUSE_PREFIX).length) asked = true
                    // G4：子句只有這個動詞、後面接「之後／然後」、下一子句是問句 → 話題
                    if (!asked && text.replace(/\s/g, "") === verb && next && TOPIC_CONNECTIVES.indexOf(clause.sep) >= 0 && clauseIsQuestion(next)) asked = true
                }
                if (!asked && cmds.indexOf(verb) < 0) cmds.push(verb)
            }
            at = cpIndexOf(cps, verb, at + 1)
        }
    }
    return cmds
}
function clauseIsQuestion(c) { return c.q || /[嗎呢]$/.test(c.text.replace(/\s+$/, "")) || matched(c.text, QUESTION_WORDS).length > 0 }
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
        var verbs = commandVerbs(clauses[i], clauses[i + 1])
        if (verbs.length) {
            res.matched_terms.flight = verbs
            return done("FLIGHT_CMD", 4, REPLY_HOLD)
        }
    }
    // 5 領域證據（和意圖分數分開）
    var domain = matched(text, DOMAIN_KEYWORDS).concat(matched(text, TELEMETRY_TERMS), matched(text, SYSTEM_TERMS),
                                                       matched(text, FLIGHT_VERBS), masked.hits)
    res.matched_terms.domain = domain
    // 5a F2 偏離航線意圖：本身就是領域證據（「上一趟偏了多遠」沒有其他領域詞）
    var dev = deviationIntent(input)
    if (dev.hit) res.matched_terms.deviation = dev.cues
    // 6 沒有領域證據
    if (!domain.length && !dev.hit) return done("OUT_OF_DOMAIN", 6, REPLY_OUT_OF_DOMAIN)
    // 7 問原因
    var cause = matched(text, CAUSE_WORDS)
    if (cause.length) { res.matched_terms.cause = cause; return done("NO_CAUSE_ANALYSIS", 7, REPLY_NO_CAUSE) }
    // 8a F2 偏離航線意圖 → QA（不打分；問原因的已在 7 擋下）
    if (dev.hit) return done("QA", 12)
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
    // F2（說明 v2 §2-1、§2-2）：只跑飛行紀錄的 DEVIATION；同句其他事不查，列進 deferred_asks
    var dev = deviationIntent(input)
    if (dev.hit && cls !== "ALERT_Q")
        return { tools: ["T_FLIGHTLOG"], tools_truncated: false, omitted_tools: [], reasons: { T_FLIGHTLOG: ["(F2) "].concat(dev.cues) },
                 flightlog_op: "DEVIATION", route_basis: dev.basis, deferred_asks: dev.other_asks }
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
             tools_truncated: tools.tools_truncated, omitted_tools: tools.omitted_tools, tool_reasons: tools.reasons, reply: g.reply, record: record,
             flightlog_op: tools.flightlog_op || null, route_basis: tools.route_basis || null, deferred_asks: tools.deferred_asks || [] }
}
