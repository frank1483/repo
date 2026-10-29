.pragma library
// Pure bounded transaction controller. The host owns confirmation, scheduling and I/O.
// No Qt, HTTP, model backend, settings, flight command or parameter API here.
function create(spec, ports) {
    function copy(value) { return JSON.parse(JSON.stringify(value)) }
    function requireValue(ok, why) { if (!ok) throw new Error(why) }
    requireValue(spec && ports, "spec and ports required")
    var config = copy(spec), catalog = Object.create(null), initial = config.steps, finalExpected = config.expected
    var kinds = ["nav", "layout", "text_scale"]
    requireValue(Array.isArray(config.catalog) && config.catalog.length > 0 && config.catalog.length <= 128, "catalog size")
    requireValue(Array.isArray(initial) && initial.length > 0 && initial.length <= 5, "one to five steps required")
    requireValue(finalExpected && typeof finalExpected === "object" && !Array.isArray(finalExpected) &&
        (finalExpected.page !== undefined || (Array.isArray(finalExpected.modules) && finalExpected.modules.length) ||
         (Array.isArray(finalExpected.extraChecks) && finalExpected.extraChecks.length)), "explicit final expectation required")
    requireValue(!Object.prototype.hasOwnProperty.call(finalExpected, "before"), "host cannot replace transaction baseline")
    for (var k = 0; k < config.catalog.length; ++k) {
        var c = config.catalog[k]
        requireValue(c && typeof c.id === "string" && /^[A-Za-z0-9_:-]{1,100}$/.test(c.id) &&
            !Object.prototype.hasOwnProperty.call(catalog, c.id), "invalid or duplicate candidate id")
        requireValue(c.action && kinds.indexOf(c.action.kind) >= 0, "unsupported action kind")
        requireValue(c.expected && typeof c.expected === "object" && !Array.isArray(c.expected) &&
            !Object.prototype.hasOwnProperty.call(c.expected, "before") &&
            (c.expected.page !== undefined || (Array.isArray(c.expected.modules) && c.expected.modules.length) ||
             (Array.isArray(c.expected.extraChecks) && c.expected.extraChecks.length)), "trusted step expectation required")
        if (c.action.kind === "nav") requireValue(Number.isInteger(c.action.page) && c.action.page >= 0 && c.action.page <= 13 &&
            Number.isInteger(c.action.section) && c.action.section >= -1, "invalid navigation")
        if (c.action.kind === "layout") requireValue(typeof c.action.module === "string" &&
            ["move", "nudge", "scale", "show", "hide", "reset"].indexOf(c.action.op) >= 0, "invalid layout action")
        if (c.action.kind === "text_scale") requireValue([0.85, 1, 1.15, 1.3].indexOf(c.action.value) >= 0, "invalid text scale")
        catalog[c.id] = c
    }
    for (k = 0; k < initial.length; ++k)
        requireValue(typeof initial[k] === "string" && Object.prototype.hasOwnProperty.call(catalog, initial[k]) &&
            !catalog[initial[k]].repairFor, "initial candidate not in catalog or is repair-only")
    var required = ["begin", "commit", "rollback", "snapshot", "checkpoint", "restore", "execute", "verify"]
    for (k = 0; k < required.length; ++k) requireValue(typeof ports[required[k]] === "function", "missing port " + required[k])

    var phase = "ready", group = null, baseline = null, round = 1, index = 0, epoch = 0
    var plan = [], planIndex = 0, saved = [], failed = [], trace = [], repairPending = false, executions = 0
    function emit(event) {
        trace.push(copy(event))
        // Reporting cannot corrupt a committed or rolled-back transaction.
        if (typeof ports.report === "function") { try { ports.report(copy(event)) } catch (_) {} }
    }
    function state() { return copy({phase: phase, round: round, index: index, executions: executions, repairPending: repairPending, trace: trace}) }
    function end(ok, reason) {
        if (phase === "complete" || phase === "failed" || phase === "rollback_failed" || phase === "ready") return
        ++epoch; repairPending = false
        if (ok) {
            try { ports.commit(group, config.label || config.goal || "UI goal", "layout") }
            catch (e) { end(false, "COMMIT_FAILED: " + String(e)); return }
            phase = "complete"
        } else {
            try { ports.rollback(group); phase = "failed" }
            catch (error) { phase = "rollback_failed"; reason += "; ROLLBACK_FAILED: " + String(error) }
        }
        emit({phase: phase, reason: reason, round: round, index: index, alternatives: ok ? [] : initial.slice()})
        if (typeof ports.finished === "function") { try { ports.finished(state()) } catch (_) {} }
    }
    function check(expected) {
        var target = copy(expected)
        target.before = copy(baseline)
        var observation = ports.snapshot(), result = ports.verify(copy(observation), target)
        requireValue(result && typeof result.ok === "boolean" && Array.isArray(result.failures), "invalid verifier result")
        requireValue(result.ok === (result.failures.length === 0), "inconsistent verifier result")
        for (var n = 0; n < result.failures.length; ++n) {
            var f = result.failures[n]
            requireValue(f && typeof f.code === "string" && typeof f.detail === "string", "invalid verifier failure")
        }
        return {snapshot: observation, result: copy(result)}
    }
    function safe(work) {
        try { work() } catch (e) { end(false, "PORT_OR_CONTRACT_ERROR: " + String(e)) }
    }
    function fail(observed, stage) {
        if (round >= 5) { end(false, "ROUND_LIMIT"); return }
        var originalIndex = index
        failed[index] = (failed[index] || 0) + 1
        var backtracked = failed[index] >= 2
        if (backtracked) {
            // Restore pre-previous-step state; every dropped logical step is reverified.
            index = Math.max(0, index - 1)
            ports.restore(saved[index])
            saved = saved.slice(0, index + 1)
            emit({phase: "backtrack", from: originalIndex, to: index, round: round})
            if (phase !== "running") return
        }
        ++round
        var targetId = initial[index], codes = observed.result.failures.map(function(f) { return f.code })
        var allowed = [targetId]
        for (var id in catalog) {
            if (!Object.prototype.hasOwnProperty.call(catalog, id)) continue
            var candidate = catalog[id]
            if (Array.isArray(candidate.repairFor) && candidate.repairFor.indexOf(targetId) >= 0 &&
                Array.isArray(candidate.failureCodes) && candidate.failureCodes.some(function(code) { return codes.indexOf(code) >= 0 }))
                allowed.push(id)
        }
        var request = {goal: config.goal || "", round: round, logical_index: index, failed_index: originalIndex,
            backtracked: backtracked, stage: stage, failures: copy(observed.result.failures),
            snapshot: copy(observed.snapshot), expected: copy(catalog[targetId].expected),
            candidates: allowed.map(function(id) { return {id: id, label: catalog[id].label || id} }), max_steps: 5}
        emit({phase: "repair_requested", request: request})
        if (phase !== "running") return
        if (typeof ports.propose !== "function") { end(false, "REPAIR_UNAVAILABLE"); return }
        repairPending = true
        var token = ++epoch, consumed = false
        ports.propose(copy(request), function(response) {
            if (consumed || token !== epoch || phase !== "running") return
            consumed = true; repairPending = false
            safe(function() {
                requireValue(response && Array.isArray(response.steps) && response.steps.length > 0 && response.steps.length <= 5,
                    "repair must select one to five candidate ids")
                var ids = response.steps.map(function(s) {
                    requireValue(s && typeof s.choice_id === "string" && Object.keys(s).length === 1 &&
                        allowed.indexOf(s.choice_id) >= 0, "repair candidate outside trusted scope")
                    return s.choice_id
                })
                plan = ids; planIndex = 0
                emit({phase: "repair_selected", round: round, index: index, ids: ids,
                    reason: String(response.reason_zh || "").slice(0, 300)})
                dispatch()
            })
        })
    }
    function finishLogical() {
        var verified = check(catalog[initial[index]].expected)
        emit({phase: "logical_check", index: index, round: round, result: verified.result})
        if (phase !== "running") return
        if (!verified.result.ok) { fail(verified, "logical"); return }
        ++index
        if (index === initial.length) {
            var final = check(finalExpected)
            emit({phase: "final_check", round: round, result: final.result})
            if (phase !== "running") return
            // Final invariant failure has no safe logical repair target. Restore the whole group.
            if (!final.result.ok) { end(false, "FINAL_VERIFICATION_FAILED"); return }
            end(true, "VERIFIED"); return
        }
        saved[index] = ports.checkpoint()
        plan = [initial[index]]; planIndex = 0
        dispatch()
    }
    function dispatch() {
        if (phase !== "running") return
        if (planIndex === plan.length) { finishLogical(); return }
        if (executions >= 25) { end(false, "STEP_BUDGET"); return }
        var id = plan[planIndex], candidate = catalog[id], token = ++epoch, consumed = false
        ++executions
        emit({phase: "execute", round: round, index: index, id: id, action: copy(candidate.action)})
        if (phase !== "running") return
        ports.execute(copy(candidate.action), function(error) {
            if (consumed || token !== epoch || phase !== "running") return
            consumed = true
            safe(function() {
                if (error) { end(false, "EXECUTION_FAILED: " + String(error)); return }
                var verified = check(candidate.expected)
                emit({phase: "step_check", round: round, index: index, id: id, result: verified.result})
                if (phase !== "running") return
                if (!verified.result.ok) { fail(verified, "step"); return }
                ++planIndex; dispatch()
            })
        })
    }
    return {
        start: function(confirmed) {
            requireValue(phase === "ready", "loop already started")
            requireValue(confirmed === true, "explicit host confirmation required")
            // No ports are touched until confirmation. A failed begin cannot be rolled back with an unknown token.
            baseline = copy(ports.snapshot())
            group = ports.begin(); phase = "running"
            safe(function() {
                saved[0] = ports.checkpoint(); plan = [initial[0]]
                emit({phase: "started", round: round, steps: initial.slice()})
                dispatch()
            })
            return state()
        },
        cancel: function() { if (phase === "running") end(false, "CANCELLED"); return state() },
        state: state
    }
}

// Bounded rule goal template. A caller must build trusted candidates/expectations and a card.
// Main-map zoom is deliberately not invented: current Core catalog registers miniView only.
function goalTemplate(intent, context) {
    var text = String(intent || "").trim(), ctx = context || {}
    if (!/^(?:讓|把)?(?:小地圖|地圖)(?:能)?看(?:得)?清楚(?:一點|些)?[。！!]?$/i.test(text)) return null
    var m = (ctx.modules || {}).miniView
    if (text.indexOf("小地圖") < 0)
        return {decision: "CLARIFY", goal: text, reason_zh: "請指明主地圖或小地圖；此模板只支援小地圖", candidates: []}
    if (ctx.page !== 1 || !m || m.registered !== true || m.visible !== true)
        return {decision: "CLARIFY", goal: text, reason_zh: "請選擇要放大的地圖；小地圖目前未顯示", candidates: []}
    return {decision: "SELECT", goal: text, goal_intent: true, confirmation_required: true,
        candidates: [{id: "GOAL_MINIVIEW_READABLE", kind: "layout", module: "miniView", op: "scale", factor: 1.25,
            label_zh: "放大小地圖，檢查可見範圍、遮擋與可讀尺寸"}], steps: [{choice_id: "GOAL_MINIVIEW_READABLE"}]}
}
