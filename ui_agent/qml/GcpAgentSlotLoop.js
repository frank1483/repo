.pragma library
// Shared state-machine loop engine ("slot loop"), used by every feature that asks the shared model.
// Same contract is implemented in Python as gcs_demo/agent_loop.py; both pass
// test/slot_loop_vectors.json (conformance vectors), so UI, alerts and mission behave the same way.
//
// The program owns the loop. A feature supplies a METHOD LIBRARY; the engine supplies:
//   * the external state object st (goal, state, slots, allowed, observation, error, counters, trace)
//   * one prompt per step, rebuilt from st (no chat history), asking for ONE enum value: {"value":"CODE"}
//   * strict parsing: JSON object, exactly the key "value", a string, inside the allowed list
//   * one repair per session, a model-call cap, then the feature's rule fallback
//   * next() / answer(raw) / fail(reason) for an async host, run() for a sync driver
// Pure JS: no Qt, HTTP, files or devices. Transport, deadlines and logging stay with the host.
//
// Method library (lib) contract:
//   lib.begin(h)            -> start: call h.finish(...) or h.ruleFallback(...), or h.go(state, observation)
//   lib.options(st)         -> { need: "要填什麼", allowed: [{code, zh}] } for st.state
//   lib.header(st)          -> array of prompt lines shown before 要填 (句子、目前狀態、已知、觀察)
//   lib.transition(code, h) -> "" when it moved on (h.go / h.finish / h.escalate / h.ruleFallback),
//                              or a problem string = precondition failed -> treated as an invalid answer
//   lib.ruleDecision()      -> the feature's rule decision used for fallback (copied)
//   lib.finalize(decision)  -> optional; normalise a decision before it is returned
// Helper h: { st, log, go, finish, escalate, ruleFallback }

var ENGINE_VERSION = "slot-loop-1"
var DEFAULT_MAX_CALLS = 4

function copy(x) { return x === undefined ? undefined : JSON.parse(JSON.stringify(x)) }

function defaultExtract(text) {
    if (typeof text !== "string") return text && typeof text === "object" ? text : null
    try { return JSON.parse(text) } catch (e) {}
    var a = text.indexOf("{"), b = text.lastIndexOf("}")
    if (a < 0 || b <= a) return null
    try { return JSON.parse(text.slice(a, b + 1)) } catch (e2) { return null }
}

// config: { version, systemPrompt, maxCalls, extractJson, goal, modelEnabled }
function session(lib, config) {
    var cfg = config || {}
    var maxCalls = cfg.maxCalls || DEFAULT_MAX_CALLS
    var extract = cfg.extractJson || defaultExtract
    var st = {
        version: cfg.version || ENGINE_VERSION, goal: String(cfg.goal || ""), state: "S1",
        kind: "", slots: {}, need: "", allowed: [], last_observation: "", last_error: "",
        repair_used: false, model_calls: 0, trace: [], done: null
    }
    function log(event) { event.state = st.state; st.trace.push(copy(event)) }
    function finish(decision, source, why) {
        decision = copy(decision)
        if (lib.finalize) decision = lib.finalize(decision)
        decision.source = source
        decision.model_errors = st.trace.filter(function(e) { return e.event === "invalid" }).map(function(e) { return e.why })
        st.state = "END"
        st.done = decision
        log({ event: "done", decision: decision.decision, ids: (decision.steps || []).map(function(s) { return s.choice_id }),
              source: source, why: why || "" })
    }
    function ruleFallback(why, source) {
        finish(lib.ruleDecision(), "rule_fallback", why)
        if (source) st.done.source = source
    }
    function escalate(why, extra) {
        var d = { decision: "CLARIFY", choice_id: "", reason_zh: why }
        if (extra) for (var k in extra) d[k] = extra[k]
        finish(d, "state_machine", why)
    }
    function go(state, observation) {
        st.state = state
        if (observation !== undefined) st.last_observation = observation
        var o = lib.options(st)
        st.need = o.need
        st.allowed = o.allowed
        st.last_error = ""
    }
    var h = { st: st, log: log, go: go, finish: finish, escalate: escalate, ruleFallback: ruleFallback }

    function renderCall() {
        var lines = lib.header(st).slice()
        lines.push("要填：" + st.need)
        lines.push("只能選：" + st.allowed.map(function(a) { return a.code + " " + a.zh }).join("｜"))
        if (st.last_error) lines.push("上次錯誤：" + st.last_error + "。請只從清單重選一個代碼。")
        lines.push("只輸出 JSON：{\"value\":\"代碼\"}")
        var codes = st.allowed.map(function(a) { return a.code })
        return {
            version: st.version, state: st.state, repair: st.last_error !== "",
            messages: [{ role: "system", content: cfg.systemPrompt }, { role: "user", content: lines.join("\n") }],
            schema: { type: "object", additionalProperties: false, required: ["value"],
                      properties: { value: { type: "string", enum: codes } } },
            codes: codes
        }
    }
    function invalid(why, raw) {
        log({ event: "invalid", why: why, raw: String(raw === undefined ? "" : raw).slice(0, 200) })
        if (!st.repair_used && st.model_calls < maxCalls) {
            st.repair_used = true
            st.last_error = why
            log({ event: "repair_requested", why: why })
            return
        }
        ruleFallback(st.repair_used ? "修正一次後仍無效：" + why : "模型呼叫已達上限：" + why)
    }
    function parse(raw) {
        var obj = extract(raw)
        if (!obj || typeof obj !== "object" || Array.isArray(obj)) return { error: "回覆不是 JSON 物件" }
        var keys = Object.keys(obj)
        if (keys.length !== 1 || keys[0] !== "value") return { error: "只能有 value 一個欄位" }
        if (typeof obj.value !== "string") return { error: "value 必須是字串" }
        var codes = st.allowed.map(function(a) { return a.code })
        if (codes.indexOf(obj.value) < 0) return { error: "回答「" + String(obj.value).slice(0, 40) + "」不在可選清單內" }
        return { value: obj.value }
    }

    lib.begin(h)
    if (!st.done && cfg.modelEnabled === false) ruleFallback("模型未啟用", "rule")

    return {
        state: function() { return copy(st) },
        next: function() {
            if (st.done) return { type: "done", decision: copy(st.done), trace: copy(st.trace), model_calls: st.model_calls }
            if (st.model_calls >= maxCalls) { ruleFallback("模型呼叫已達上限"); return this.next() }
            return { type: "ask", call: renderCall() }
        },
        answer: function(raw) {
            if (st.done) throw new Error("session already finished")
            st.model_calls++
            log({ event: "model_reply", raw: String(raw === undefined ? "" : (typeof raw === "string" ? raw : JSON.stringify(raw))).slice(0, 200),
                  repair: st.last_error !== "" })
            var p = parse(raw)
            if (p.error) { invalid(p.error, raw); return }
            log({ event: "filled", value: p.value })
            var problem = lib.transition(p.value, h)
            // A filled value that fails the method's preconditions counts as an invalid answer (repair once).
            if (problem) invalid(problem, p.value)
        },
        fail: function(reason) {
            if (st.done) return
            st.model_calls++
            invalid("模型未回覆：" + String(reason || "error"), "")
        }
    }
}

// Synchronous driver: model(call) returns the raw reply text (null/undefined = no reply).
function run(s, model) {
    var calls = []
    for (var guard = 0; guard < 16; ++guard) {
        var step = s.next()
        if (step.type === "done") return { decision: step.decision, trace: step.trace, model_calls: step.model_calls, calls: calls }
        calls.push(step.call)
        var reply
        try { reply = model ? model(step.call) : null } catch (e) { s.fail(String(e)); continue }
        if (reply === null || reply === undefined) s.fail("no model")
        else s.answer(reply)
    }
    throw new Error("slot loop did not terminate")
}
