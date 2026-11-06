.pragma library
.import "GcpSlotLoop.js" as SlotLoop
// UI agent method library on the shared slot-loop engine (GcpSlotLoop.js), decision side S1-S5.
// sm-v2: the engine (state object, prompt, parse, repair once, call cap, rule fallback) is shared
// with alerts and mission; this file only holds the UI states, options and methods.
// Program owns the loop: every state has exactly one output and one tool, and the next state
// is chosen by code. The model is asked only to fill ONE enum slot per call, from a short prompt
// rebuilt each time from the external state object (no chat history).
// Execution (S6) and post-execution check/repair (S7) stay with the host, Verifier and
// GcpAgentLoop (model repair = separate Codex task). Pure JS: no Qt, HTTP, files or devices.
//
// Host contract:
//   var s = create(Core).start(text, ctx, pendingText)
//   loop: var step = s.next()
//         step.type === "ask"  -> send step.call.messages with step.call.schema, then s.answer(rawText)
//         step.type === "done" -> step.decision is v6-compatible: {decision, choice_id, steps, reason_zh, ...}
//   s.fail(reason) records a transport error/timeout for the outstanding ask (counts as invalid answer).

var VERSION = "sm-v2"
var MAX_MODEL_CALLS = 4      // classify + up to two slots + one repair

var SYSTEM_PROMPT = "你是無人機地面站介面助理流程中的一個步驟，只負責填一格。" +
    "只回答一個 JSON：{\"value\":\"代碼\"}。代碼只能從「只能選」清單裡挑一個，不可自創。" +
    "不確定就回 UNKNOWN。"

var KINDS = [
    { code: "NAV", zh: "換頁或查看某個畫面、設定" },
    { code: "LAYOUT", zh: "移動、縮放、隱藏或顯示畫面上的模組" },
    { code: "TEXT", zh: "調整全系統文字大小" },
    { code: "HISTORY", zh: "復原、重做或全部還原介面變更" },
    { code: "OUT_OF_SCOPE", zh: "控制飛機、修改參數數值，或與介面無關" },
    { code: "AMBIGUOUS", zh: "太模糊，要問使用者想做什麼" },
    { code: "UNKNOWN", zh: "不知道" }
]

var SCALE_ACTIONS = [
    { code: "SCALE_UP", zh: "放大一點（×1.25）", factor: 1.25 },
    { code: "SCALE_DOWN", zh: "縮小一點（×0.8）", factor: 0.8 },
    { code: "SCALE_MAX", zh: "放到最大（×2）", factor: 2 },
    { code: "SCALE_MIN", zh: "縮到最小（×0.5）", factor: 0.5 }
]
var NUDGE_ACTIONS = [
    { code: "NUDGE_L", zh: "往左移一點", dir: "L", name: "往左" },
    { code: "NUDGE_R", zh: "往右移一點", dir: "R", name: "往右" },
    { code: "NUDGE_U", zh: "往上移一點", dir: "U", name: "往上" },
    { code: "NUDGE_D", zh: "往下移一點", dir: "D", name: "往下" }
]
var TEXT_OPTIONS = [
    { code: "T085", zh: "文字 85%", value: 0.85 },
    { code: "T100", zh: "文字 100%（預設）", value: 1.0 },
    { code: "T115", zh: "文字 115%", value: 1.15 },
    { code: "T130", zh: "文字 130%", value: 1.3 },
    { code: "BIGGER", zh: "比現在大一級", direction: 1 },
    { code: "SMALLER", zh: "比現在小一級", direction: -1 },
    { code: "UNKNOWN", zh: "不知道" }
]
var HISTORY_OPTIONS = [
    { code: "UNDO", zh: "復原上一步" },
    { code: "REDO", zh: "重做剛剛復原的變更" },
    { code: "RESET_ALL", zh: "全部回到 agent 介入前" },
    { code: "UNKNOWN", zh: "不知道" }
]

function copy(x) { return x === undefined ? undefined : JSON.parse(JSON.stringify(x)) }

function create(core, options) {
    var opts = options || {}
    var maxCalls = opts.maxCalls || MAX_MODEL_CALLS

    function page(p) { return core.PAGES.filter(function(x) { return x.page === p })[0] }
    function sectionsOf(p) { return core.SECTIONS.filter(function(s) { return s.page === p }) }
    function moduleById(id) { return core.MODULES.filter(function(m) { return m.id === id })[0] }
    function regionName(key) { return { TL: "左上角", TR: "右上角", BL: "左下角", BR: "右下角", TC: "上方中間",
        BC: "下方中間", ML: "左側中間", MR: "右側中間", C: "畫面中央" }[key] }
    var REGION_KEYS = ["TL", "TR", "BL", "BR", "TC", "BC", "ML", "MR", "C"]

    function start(input, ctx, pending) {
        ctx = ctx || {}
        var result = core.analyzeTurn(input, ctx, pending || "")
        var st = null, finish = null
        function log(e) { h.log(e) }
        var h = null

        function pageModules() {
            var mods = ctx.modules || null
            return core.MODULES.filter(function(m) {
                if (m.page !== ctx.page) return false
                if (!mods) return true
                var v = mods[m.id]
                return v && v.registered && v.visible
            })
        }
        function knownLine() {
            var parts = []
            if (st.kind) parts.push("類別=" + st.kind)
            if (st.slots.page !== undefined) parts.push("頁面=" + page(st.slots.page).name)
            if (st.slots.module) parts.push("模組=" + moduleById(st.slots.module).name)
            return parts.join("；")
        }
        // S4 method library -> candidate (v6 IDs) ; S5 preconditions + second-layer gate.
        function selectCandidate(c, why) {
            var gate = core.gateSelection({ decision: "SELECT", choice_id: c.id }, [c], ctx)
            log({ event: "gate", ok: gate.ok, id: c.id, failures: gate.failures })
            if (!gate.ok) return "第二層安全關卡不通過：" + gate.failures.map(function(f) { return f.code }).join(",")
            finish({ decision: "SELECT", choice_id: c.id, steps: [{ choice_id: c.id }],
                     reason_zh: c.label_zh, candidates: [c], method: why }, "state_machine", why)
            return ""
        }
        function navMethod() {
            var p = st.slots.page, sec = st.slots.section === undefined ? -1 : st.slots.section
            var here = ctx.page === p && (sec < 0 ? true : ctx.section === sec)
            if (here) {
                finish({ decision: "HOLD", choice_id: "", reason_zh: "已經在「" + page(p).name + "」了", candidates: [] },
                    "state_machine", "nav.goto: already here")
                return ""
            }
            var label = sec < 0 ? "切到「" + page(p).name + "」"
                : "切到「" + page(p).name + " › " + sectionsOf(p).filter(function(x) { return x.section === sec })[0].name + "」"
            return selectCandidate({ id: sec < 0 ? "NAV_" + p : "NAV_" + p + "_" + sec, kind: "nav", page: p, section: sec,
                                     label_zh: label, score: 0 }, "nav.goto")
        }
        function layoutMethod(code) {
            var m = moduleById(st.slots.module)
            if (code.indexOf("MOVE_") === 0) {
                var r = code.slice(5)
                return selectCandidate({ id: "LAY_" + m.id + "_MOVE_" + r, kind: "layout", module: m.id, op: "move", region: r,
                    label_zh: "把" + m.name + "移到" + regionName(r), score: 0 }, "layout.move")
            }
            var n = NUDGE_ACTIONS.filter(function(a) { return a.code === code })[0]
            if (n) return selectCandidate({ id: "LAY_" + m.id + "_NUDGE_" + n.dir, kind: "layout", module: m.id, op: "nudge", dir: n.dir,
                    label_zh: "把" + m.name + n.name + "移一點", score: 0 }, "layout.nudge")
            var sc = SCALE_ACTIONS.filter(function(a) { return a.code === code })[0]
            if (sc) {
                if ((m.scales || []).indexOf(sc.factor) < 0) return "倍率 " + sc.factor + " 不在模組允許清單"
                return selectCandidate({ id: "LAY_" + m.id + "_SCALE_" + Math.round(sc.factor * 100), kind: "layout", module: m.id,
                    op: "scale", factor: sc.factor, label_zh: (sc.factor > 1 ? "放大" : "縮小") + m.name + "（×" + sc.factor + "）",
                    score: 0 }, "layout.scale")
            }
            if (code === "HIDE") {
                if (m.locked) return m.name + "為鎖定模組，不可隱藏"
                return selectCandidate({ id: "LAY_" + m.id + "_HIDE", kind: "layout", module: m.id, op: "hide",
                    label_zh: "隱藏" + m.name, score: 0 }, "layout.hide")
            }
            if (code === "SHOW") return selectCandidate({ id: "LAY_" + m.id + "_SHOW", kind: "layout", module: m.id, op: "show",
                    label_zh: "重新顯示" + m.name, score: 0 }, "layout.show")
            if (code === "RESET") return selectCandidate({ id: "LAY_" + m.id + "_RESET", kind: "layout", module: m.id, op: "reset",
                    label_zh: m.name + "回到原本位置與大小", score: 0 }, "layout.reset")
            return "未知動作"
        }
        function textMethod(code) {
            var o = TEXT_OPTIONS.filter(function(x) { return x.code === code })[0]
            var c = core.textScaleCandidate(o.value !== undefined ? { value: o.value } : { direction: o.direction }, ctx, 0)
            if ((ctx.textScale === undefined ? 1 : ctx.textScale) === c.value) {
                finish({ decision: "HOLD", choice_id: "", reason_zh: "文字比例已是 " + c.value, candidates: [] }, "state_machine", "text.scale: no change")
                return ""
            }
            return selectCandidate(c, "text.scale")
        }
        function historyMethod(code) {
            if (code === "UNDO" && !ctx.canUndo) return "目前沒有可復原的變更"
            if (code === "REDO" && !ctx.canRedo) return "沒有可重做的變更"
            var c = code === "UNDO" ? { id: "UNDO", kind: "undo", steps: 1, label_zh: "復原上一步變更", score: 0 }
                : code === "REDO" ? { id: "REDO", kind: "redo", label_zh: "重做剛剛復原的變更", score: 0 }
                : { id: "RESET_ALL", kind: "reset_all", label_zh: "版面與畫面全部回到 agent 介入前", score: 0 }
            return selectCandidate(c, "history." + code.toLowerCase())
        }
        function escalate(why) { h.escalate(why, { candidates: copy(result.candidates) }) }

        var lib = {
            ruleDecision: function() { var d = copy(result.rule); d.candidates = copy(result.candidates); return d },
            finalize: function(d) {
                if (d.decision === "SELECT" && !d.steps) d.steps = [{ choice_id: d.choice_id }]
                return d
            },
            begin: function(helper) {
                h = helper; st = h.st; finish = h.finish
                st.page = ctx.page; st.section = ctx.section
                // ---------------- S1 收訊：第一層安全閘、取消、待補合併（全在 analyzeTurn 內）
                log({ event: "receive", text: st.goal, pending: result.pending_intent || "" })
                if (result.cancelled || result.gate === "pre" || result.safety_hold) {
                    var held = copy(result.rule); held.candidates = []
                    finish(held, "rule", result.safety_hold ? "安全閘擋下" : "取消")
                    return
                }
                // ---------------- S2 分類（規則先）：規則已確定就跳過模型
                // opts.always (GCS_AGENT_LLM_ALWAYS=1): a rule SELECT with candidates is still checked by the model in S4.
                if (result.rule.final || result.generic_settings ||
                    (result.rule.decision === "SELECT" && !(opts.always && result.candidates.length))) {
                    var d0 = copy(result.rule); d0.candidates = copy(result.candidates)
                    st.state = "S2"
                    finish(d0, "rule", "規則已確定")
                    return
                }
                // An unclear multi-clause sentence is treated as ONE action (classify or pick).
                // Fully explicit multi-clause sentences are already rule SELECT (up to five steps) above.
                if (result.compound) st.compound = true
                if (result.candidates.length) h.go("S4_PICK", "規則找到 " + result.candidates.length + " 個可能，但沒有把握")
                else h.go("S2_CLASSIFY", "規則找不到對應的畫面或模組")
            },
            header: function() {
                var lines = ["句子：" + st.goal, "目前畫面：" + core.pageName(ctx.page)]
                var known = knownLine()
                if (known) lines.push("已知：" + known)
                if (st.last_observation && st.state === "S4_PICK") lines.push("觀察：" + st.last_observation)
                return lines
            },
            options: function() {
                var s = st.state
                if (s === "S4_PICK") return { need: "最符合句子的一個動作",
                    allowed: result.candidates.map(function(c) { return { code: c.id, zh: c.label_zh } })
                        .concat([{ code: "CLARIFY", zh: "兩個以上都說得通，要問使用者" },
                                 { code: "OTHER", zh: "都不是，要重新判斷" },
                                 { code: "NONE", zh: "都不符合，而且不是介面操作" }]) }
                if (s === "S2_CLASSIFY") return { need: "這句話屬於哪一類", allowed: copy(KINDS) }
                if (s === "S3_PAGE") return { need: "要去的畫面",
                    allowed: core.PAGES.map(function(p) { return { code: "P" + p.page, zh: p.name } })
                        .concat([{ code: "UNKNOWN", zh: "不知道" }]) }
                if (s === "S3_SECTION") return { need: "「" + page(st.slots.page).name + "」裡的哪個子頁",
                    allowed: [{ code: "WHOLE", zh: "整個畫面，不指定子頁" }]
                        .concat(sectionsOf(st.slots.page).map(function(x) { return { code: "S" + x.section, zh: x.name } }))
                        .concat([{ code: "UNKNOWN", zh: "不知道" }]) }
                if (s === "S3_MODULE") return { need: "要調整的模組",
                    allowed: pageModules().map(function(m) { return { code: m.id, zh: m.name } })
                        .concat([{ code: "UNKNOWN", zh: "不知道" }]) }
                if (s === "S3_ACTION") {
                    var m = moduleById(st.slots.module)
                    return { need: "對「" + m.name + "」做什麼",
                        allowed: REGION_KEYS.map(function(k) { return { code: "MOVE_" + k, zh: "移到" + regionName(k) } })
                            .concat(NUDGE_ACTIONS.map(function(a) { return { code: a.code, zh: a.zh } }))
                            .concat(SCALE_ACTIONS.map(function(a) { return { code: a.code, zh: a.zh } }))
                            .concat(m.locked ? [] : [{ code: "HIDE", zh: "隱藏" }])
                            .concat([{ code: "SHOW", zh: "重新顯示" }, { code: "RESET", zh: "回到原本位置與大小" },
                                     { code: "UNKNOWN", zh: "不知道" }]) }
                }
                if (s === "S3_TEXT") return { need: "全系統文字比例", allowed: TEXT_OPTIONS.map(function(o) { return { code: o.code, zh: o.zh } }) }
                if (s === "S3_HISTORY") return { need: "要復原還是重做", allowed: HISTORY_OPTIONS.map(function(o) { return { code: o.code, zh: o.zh } }) }
                throw new Error("no options for state " + s)
            },
            transition: function(code) {
                var s = st.state
                if (s === "S4_PICK") {
                    if (code === "CLARIFY") { h.ruleFallback("模型判斷有多個可能", "state_machine"); return "" }
                    if (code === "OTHER") {
                        // Rule candidates missed the target; re-enter classification once.
                        if (st.reclassified) { h.ruleFallback("重新判斷已用過"); return "" }
                        st.reclassified = true
                        h.go("S2_CLASSIFY", "規則候選都不對，重新分類"); return ""
                    }
                    if (code === "NONE") { finish({ decision: "HOLD", choice_id: "", reason_zh: "沒有對應的動作", candidates: [] }, "state_machine", "pick: none"); return "" }
                    return selectCandidate(core.candidateById(result, code), "pick")
                }
                if (s === "S2_CLASSIFY") {
                    st.kind = code
                    if (code === "OUT_OF_SCOPE") { finish({ decision: "HOLD", choice_id: "", candidates: [],
                        reason_zh: "介面助理只換頁與調整版面，不送飛行指令、不改參數" }, "state_machine", "classify: out of scope"); return "" }
                    if (code === "UNKNOWN") { h.ruleFallback("分類：不知道"); return "" }
                    if (code === "AMBIGUOUS") { escalate("請再說明想做什麼，例如要去哪個畫面或調整哪個模組"); return "" }
                    if (code === "LAYOUT" && !pageModules().length) { escalate("目前畫面沒有可調整的模組，請先切到要調整的畫面"); return "" }
                    h.go({ NAV: "S3_PAGE", LAYOUT: "S3_MODULE", TEXT: "S3_TEXT", HISTORY: "S3_HISTORY" }[code], "分類為 " + code)
                    return ""
                }
                if (s === "S3_PAGE") {
                    if (code === "UNKNOWN") { escalate("請說明要去哪個畫面"); return "" }
                    st.slots.page = parseInt(code.slice(1), 10)
                    if (sectionsOf(st.slots.page).length) { h.go("S3_SECTION"); return "" }
                    return navMethod()
                }
                if (s === "S3_SECTION") {
                    if (code === "UNKNOWN") { escalate("請說明要看「" + page(st.slots.page).name + "」的哪一項"); return "" }
                    st.slots.section = code === "WHOLE" ? -1 : parseInt(code.slice(1), 10)
                    return navMethod()
                }
                if (s === "S3_MODULE") {
                    if (code === "UNKNOWN") { escalate("請說明要調整哪個模組"); return "" }
                    st.slots.module = code
                    h.go("S3_ACTION"); return ""
                }
                if (s === "S3_ACTION") {
                    if (code === "UNKNOWN") { escalate("請說明要怎麼調整" + moduleById(st.slots.module).name); return "" }
                    return layoutMethod(code)
                }
                if (s === "S3_TEXT") {
                    if (code === "UNKNOWN") { escalate("請說明文字要放大還是縮小"); return "" }
                    return textMethod(code)
                }
                if (s === "S3_HISTORY") {
                    if (code === "UNKNOWN") { escalate("請說明要復原還是重做"); return "" }
                    return historyMethod(code)
                }
                return "未知狀態"
            }
        }
        return SlotLoop.session(lib, { version: VERSION, systemPrompt: SYSTEM_PROMPT, maxCalls: maxCalls,
            extractJson: core.extractJson, goal: String(result.intent || input || ""), modelEnabled: opts.modelEnabled })
    }
    return { start: start, VERSION: VERSION }
}

// Synchronous driver for offline evaluation: model(call) returns the raw reply text.
function runSync(core, input, ctx, pending, model, options) {
    return SlotLoop.run(create(core, options).start(input, ctx, pending), model)
}
