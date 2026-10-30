.pragma library
// Host bridge for the single readability goal. No network, model, Settings or flight API.
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
    var token = null, scheduled = null, epoch = 0, started = false, ended = false
    var expectedRevision = basis.revision, deadline = 0
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
    var loop = libs.loop.create(original.spec, {
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
            need(host.now() < deadline, "readability session timeout")
            var fresh = capture()
            // This first bridge intentionally supports the initial scale only.
            // Model repair, navigation and extra actions require a later reviewed bridge.
            need(action.kind === "layout" && action.module === "miniView" && action.op === "scale" && action.factor === 1.25,
                "readability repair dispatch not connected")
            var policy = libs.core.MODULES.filter(function(p) { return p.id === "miniView" })[0]
            var f = fresh.frame
            var next = libs.core.layoutTarget("scale", copy(f.base), copy(f.area), copy(f.override), action.factor, copy(f.others), policy)
            host.apply("miniView", next)
            expectedRevision = host.revision()
            settle(done)
        },
        verify: function(s, e) { return libs.verifier.verify(s, e) },
        // No propose port: verifier failures roll back with REPAIR_UNAVAILABLE.
        report: function(e) { if (typeof host.report === "function") host.report(copy(e)) },
        finished: function(s) {
            ended = true
            cancelSchedule()
            if (typeof host.finished === "function") host.finished(copy(s))
        }
    })
    return {
        start: function(confirmed) {
            need(confirmed === true && !started && !ended, "one explicit readability confirmation required")
            started = true
            deadline = host.now() + 12000
            return loop.start(true)
        },
        cancel: function() { cancelSchedule(); return loop.cancel() },
        state: function() { return loop.state() }
    }
}
