.pragma library
// Host bridge for one confirmed readability goal. Model I/O is a cancellable host port.
// Every State mutation belongs to the exact beginGroup token returned to this bridge.
function create(prepared, host, libs) {
    function need(ok, why) { if (!ok) throw new Error(why) }
    function copy(x) { return JSON.parse(JSON.stringify(x)) }
    function key(x) {
        if (x === null || typeof x !== "object") return JSON.stringify(x)
        if (Array.isArray(x)) return "[" + x.map(key).join(",") + "]"
        return "{" + Object.keys(x).sort().map(function(k) { return JSON.stringify(k) + ":" + key(x[k]) }).join(",") + "}"
    }
    need(prepared && prepared.basis && host && libs, "prepared host confirmation required")
    var original = copy(prepared), basis = original.basis
    var required = ["capture", "revision", "begin", "owns", "commit", "rollback", "checkpoint", "restore", "apply",
        "schedule", "cancelSchedule", "now"]
    required.forEach(function(p) { need(typeof host[p] === "function", "missing host port " + p) })
    var loop = null
    var token = null, scheduled = null, epoch = 0, started = false, ended = false
    var expectedRevision = basis.revision, deadline = 0, totalDeadline = 0
    var repairCalls = 0, modelEpoch = 0, cancelModel = null, modelPending = false
    var repairTrace = {repair_source: "none", candidates: [], raw: null, latency_ms: null}
    function report(e) {
        e.repair_source = repairTrace.repair_source
        if (typeof host.report === "function") { try { host.report(copy(e)) } catch (_) {} }
    }
    function abortModel() {
        ++modelEpoch; modelPending = false
        var cancel = cancelModel; cancelModel = null
        if (typeof cancel === "function") { try { cancel() } catch (_) {} }
    }
    function stop(reason) { return loop.cancel(reason) }
    function state(s) { s = s || loop.state(); s.repair = copy(repairTrace); return s }
    function own() { need(token !== null && host.owns(token) === true, "readability group ownership lost") }
    function cancelSchedule() {
        ++epoch
        if (scheduled !== null) { host.cancelSchedule(scheduled); scheduled = null }
    }
    function capture() {
        var fresh = host.capture()
        need(fresh && fresh.revision === expectedRevision, "external State revision during readability goal")
        need(key(fresh.goal) === key(basis.goal) && key(fresh.candidates) === key(basis.candidates), "readability policy or candidates changed")
        need(key(fresh.frame.base) === key(basis.frame.base) && key(fresh.frame.area) === key(basis.frame.area) &&
            key(fresh.frame.origin) === key(basis.frame.origin) && key(fresh.snapshot.viewport) === key(basis.snapshot.viewport),
            "readability frame changed")
        need(fresh.snapshot.page === basis.snapshot.page && fresh.snapshot.section === basis.snapshot.section,
            "readability location changed")
        return fresh
    }
    // Two consecutive measurements after dispatch must agree. A bounded timer polls
    // a condition; elapsed time alone never declares layout ready.
    function settle(done) {
        var last = null, equal = 0, stepDeadline = Math.min(deadline, host.now() + 2500)
        var generation = ++epoch
        function poll() {
            scheduled = null
            if (ended || generation !== epoch) return
            try {
                own()
                if (host.now() >= stepDeadline) { done("LAYOUT_SETTLE_TIMEOUT"); return }
                var observed = key(capture())
                equal = observed === last ? equal + 1 : 1
                last = observed
                if (equal >= 2) { done(null); return }
                scheduled = host.schedule(poll, 16)
            } catch (e) { done(String(e)) }
        }
        scheduled = host.schedule(poll, 16)
    }
    loop = libs.loop.create(original.spec, {
        gateSelection: function(d, candidates, ctx) { return libs.core.gateSelection(d, candidates, ctx) },
        snapshot: function() {
            if (token !== null) { own(); return copy(capture().snapshot) }
            var fresh = host.capture()
            libs.host.assertReadableCurrent(original, fresh, libs.core, libs.catalog)
            return copy(fresh.snapshot)
        },
        begin: function() {
            // Recheck immediately before acquisition; a thrown begin owns nothing.
            libs.host.assertReadableCurrent(original, host.capture(), libs.core, libs.catalog)
            token = host.begin()
            need(token !== null && token !== undefined, "missing owned group token")
            own()
            return token
        },
        commit: function(t, label, kind) {
            need(t === token, "foreign commit token"); own(); capture()
            host.commit(token, label, kind)
            token = null
        },
        rollback: function(t) {
            cancelSchedule()
            need(t === token, "foreign rollback token"); own()
            host.rollback(token)
            token = null
        },
        checkpoint: function() { own(); return copy(host.checkpoint()) },
        restore: function(s) { own(); host.restore(copy(s)); expectedRevision = host.revision() },
        execute: function(action, done) {
            own()
            need(!ended && host.now() < deadline && host.now() < totalDeadline, "readability session timeout")
            var fresh = capture()
            // Resolve the action against the detached, confirmed catalog. Never accept
            // model-supplied geometry, navigation or extra permissions.
            var selected = original.spec.catalog.filter(function(c) { return key(c.action) === key(action) })
            need(selected.length > 0 && action.kind === "layout" && action.module === "miniView" &&
                ((action.op === "scale" && action.factor === 1.25 && !selected[0].repairFor) ||
                 (selected[0].repairFor && ["move", "scale"].indexOf(action.op) >= 0)), "unconfirmed readability action")
            var policy = libs.core.MODULES.filter(function(p) { return p.id === "miniView" })[0]
            var f = fresh.frame
            var next = libs.core.layoutTarget(action.op, copy(f.base), copy(f.area), copy(f.override),
                action.op === "move" ? action.region : action.factor, copy(f.others), policy)
            host.apply("miniView", next)
            expectedRevision = host.revision()
            settle(done)
        },
        verify: function(s, e) { return libs.verifier.verify(s, e) },
        propose: function(request, done) {
            if (ended) return
            if (repairCalls >= 1) { stop("REPAIR_LIMIT"); return }
            if (host.now() >= deadline || host.now() >= totalDeadline) { stop("SESSION_TIMEOUT"); return }
            var current = capture().snapshot
            var allowed = request.candidates.filter(function(c) {
                var trusted = original.spec.catalog.filter(function(t) { return t.id === c.id })[0]
                return trusted && Array.isArray(trusted.repairFor) && trusted.repairFor.indexOf(original.spec.steps[0]) >= 0 &&
                    trusted.action.kind === "layout" && trusted.action.module === "miniView" &&
                    ["move", "scale"].indexOf(trusted.action.op) >= 0 &&
                    libs.core.gateSelection({decision:"SELECT", steps:[{choice_id:c.id}]}, [trusted], current).ok
            })
            if (!allowed.length || typeof host.propose !== "function") { stop("REPAIR_INVALID"); return }
            var ids = allowed.map(function(c) { return c.id })
            var outbound = copy(request)
            outbound.candidates = copy(allowed); outbound.max_steps = 1
            outbound.json_schema = {type:"object", additionalProperties:false, required:["steps", "reason_zh"], properties:{
                steps:{type:"array", minItems:1, maxItems:1, items:{type:"object", additionalProperties:false,
                    required:["choice_id"], properties:{choice_id:{type:"string", enum:ids}}}}, reason_zh:{type:"string"}}}
            var t0 = host.now(), modelDeadline = Math.min(totalDeadline, t0 + 20000), generation = ++modelEpoch
            outbound.timeout_ms = modelDeadline - t0
            outbound.deadline_ms = totalDeadline - t0
            ++repairCalls; modelPending = true
            repairTrace = {repair_source:"model", candidates:copy(allowed), raw:null, latency_ms:null, request:copy(outbound)}
            report({phase:"repair_model_request", request:outbound})
            if (ended || !modelPending || generation !== modelEpoch) return
            cancelSchedule()
            scheduled = host.schedule(function() {
                scheduled = null
                if (ended || !modelPending || generation !== modelEpoch) return
                repairTrace.latency_ms = host.now() - t0
                report({phase:"repair_model_response", error_code:"REPAIR_TIMEOUT", repair:copy(repairTrace)})
                stop("REPAIR_TIMEOUT")
            }, outbound.timeout_ms)
            try {
                // Account for synchronous trace/scheduler overhead before handing off.
                outbound.deadline_ms = Math.floor(totalDeadline - host.now())
                outbound.timeout_ms = Math.floor(modelDeadline - host.now())
                if (outbound.deadline_ms <= 0 || outbound.timeout_ms <= 0) { stop("REPAIR_TIMEOUT"); return }
                var cancel = host.propose(copy(outbound), function(result) {
                    if (ended || !modelPending || generation !== modelEpoch) return
                    if (host.now() >= modelDeadline) { stop("REPAIR_TIMEOUT"); return }
                    repairTrace.latency_ms = host.now() - t0
                    repairTrace.raw = result && typeof result.raw === "string" ? result.raw : JSON.stringify(result || null)
                    cancelSchedule(); abortModel()
                    // Only model waiting is excluded from the 12-second operation budget.
                    deadline = Math.min(totalDeadline, deadline + host.now() - t0)
                    report({phase:"repair_model_response", repair:copy(repairTrace)})
                    if (ended) return
                    if (!result || result.ok === false) {
                        stop(result && result.error_code === "REPAIR_TIMEOUT" ? "REPAIR_TIMEOUT" : "REPAIR_INVALID"); return
                    }
                    var response = result.response || result
                    if (!response || !Array.isArray(response.steps) || response.steps.length !== 1 ||
                        typeof response.reason_zh !== "string" || Object.keys(response).some(function(k) { return ["steps","reason_zh"].indexOf(k) < 0 }) ||
                        !response.steps[0] || Object.keys(response.steps[0]).length !== 1 ||
                        typeof response.steps[0].choice_id !== "string" || ids.indexOf(response.steps[0].choice_id) < 0) {
                        stop("REPAIR_INVALID"); return
                    }
                    // The Loop still performs its shared repair gate and per-step gate.
                    done(copy(response))
                })
                if (modelPending && generation === modelEpoch && !ended) cancelModel = cancel
                else if (typeof cancel === "function") cancel()
            } catch (e) { repairTrace.error = String(e); stop("REPAIR_INVALID") }
        },
        report: function(e) {
            report(e)
            if (repairCalls >= 1 && ((e.phase === "repair_requested") ||
                ((e.phase === "step_check" || e.phase === "logical_check") && e.result && !e.result.ok))) stop("REPAIR_LIMIT")
        },
        finished: function(s) {
            ended = true
            cancelSchedule()
            abortModel()
            if (typeof host.finished === "function") host.finished(state(copy(s)))
        }
    })
    return {
        start: function(confirmed) {
            need(confirmed === true && !started && !ended, "one explicit readability confirmation required")
            started = true
            deadline = host.now() + 12000
            totalDeadline = host.now() + 32000
            return state(loop.start(true))
        },
        cancel: function() { cancelSchedule(); abortModel(); return state(loop.cancel()) },
        state: function() { return state() }
    }
}
