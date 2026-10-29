.pragma library
// Pure snapshot checks. No Qt objects, model, filesystem or execution API.
// All rectangles are measured after transforms in the same viewport coordinates.
function verify(snapshot, expected, extensions) {
    var failures = [], s = snapshot || {}, e = expected || {}, eps = 1e-6
    function fail(code, module, detail) { failures.push({code: code, module: module || "", detail: detail}) }
    function finite(n) { return typeof n === "number" && isFinite(n) }
    function rect(m) { return m && m.rect }
    function valid(r) { return r && finite(r.x) && finite(r.y) && finite(r.w) && finite(r.h) && r.w > 0 && r.h > 0 }
    function intersects(a, b) {
        return Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)>eps &&
               Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)>eps
    }
    function shown(m) { return m && m.visible === true && m.opacity !== 0 }
    function same(a, b) { return finite(a) && finite(b) && Math.abs(a-b) <= eps }
    var modules = s.modules || {}, area = s.viewport
    if (e.page !== undefined && s.page !== e.page)
        fail("PAGE_NOT_REACHED", "", "Expected page " + e.page + ", observed " + s.page)
    if (e.section !== undefined && s.section !== e.section)
        fail("PAGE_NOT_REACHED", "", "Expected section " + e.section + ", observed " + s.section)
    var targets = e.modules || []
    if (!Array.isArray(targets)) {
        fail("INVALID_EXPECTATION", "", "expected.modules must be an array")
        targets = []
    }
    for (var i=0; i<targets.length; ++i) {
        var t = targets[i], id = t && t.id, m = modules[id]
        if (!id) { fail("INVALID_EXPECTATION", "", "Every target needs an id"); continue }
        if (t.visible === false) {
            if (shown(m)) fail("MODULE_NOT_VISIBLE", id, "Expected hidden, observed visible")
            continue
        }
        if (!shown(m) || (m.page !== undefined && m.page !== s.page)) {
            fail("MODULE_NOT_VISIBLE", id, "Required module is missing, hidden, transparent or on another page")
            continue
        }
        var r = rect(m)
        if (!valid(r) || !valid(area)) {
            fail("OUT_OF_BOUNDS", id, "Missing or invalid finite module/viewport geometry")
            continue
        }
        if (r.x < area.x-eps || r.y < area.y-eps || r.x+r.w > area.x+area.w+eps || r.y+r.h > area.y+area.h+eps)
            fail("OUT_OF_BOUNDS", id, "Module rectangle exceeds viewport")
        if (t.rect) {
            var tol = finite(t.tolerance) && t.tolerance >= 0 ? t.tolerance : eps
            if (!valid(t.rect) || ["x","y","w","h"].some(function(k) { return Math.abs(r[k]-t.rect[k]) > tol }))
                fail("EXPECTED_GEOMETRY_NOT_REACHED", id, "Module did not reach expected rectangle")
        }
        if ((finite(t.minWidth) && r.w < t.minWidth-eps) || (finite(t.minHeight) && r.h < t.minHeight-eps) || m.textTruncated === true)
            fail("TEXT_TRUNCATED", id, "Below declared minimum readable size or Qt reports truncated text")
        for (var otherId in modules) {
            if (!Object.prototype.hasOwnProperty.call(modules, otherId) || otherId === id) continue
            var other = modules[otherId], or = rect(other)
            if (!shown(other) || (other.page !== undefined && other.page !== s.page) || !valid(or) || !intersects(r,or)) continue
            // Intentional nesting (e.g. map as background) must be explicit.
            var allowed = (t.allowOverlapWith || []).indexOf(otherId) >= 0 ||
                          (m.allowOverlapWith || []).indexOf(otherId) >= 0 ||
                          (other.allowOverlapWith || []).indexOf(id) >= 0
            if (allowed || m.background === true || other.background === true) continue
            if (t.avoidOverlap !== false && m.collisionGroup !== "none" && other.collisionGroup !== "none" &&
                (m.collisionGroup || "content") === (other.collisionGroup || "content"))
                fail("OVERLAP", id, "Overlaps " + otherId)
            // paintOrder is absolute renderer stacking order; z alone is insufficient across parents.
            if (t.allowOcclusion !== true && other.occludes === true && finite(m.paintOrder) &&
                finite(other.paintOrder) && other.paintOrder > m.paintOrder)
                fail("OCCLUDED", id, "Covered by higher painted module " + otherId)
        }
    }
    var before = e.before && e.before.modules || {}
    for (var lockedId in before) {
        if (!Object.prototype.hasOwnProperty.call(before,lockedId) || before[lockedId].locked !== true) continue
        var old = before[lockedId], now = modules[lockedId]
        var changed = !now || old.visible !== now.visible || old.page !== now.page || old.opacity !== now.opacity ||
                      old.scale !== now.scale || old.locked !== now.locked
        if (!valid(rect(old)) || !valid(rect(now))) changed = true
        else for (var j=0; j<4; ++j) {
            var key = ["x","y","w","h"][j]
            if (!same(old.rect[key],now.rect[key])) changed = true
        }
        if (changed) fail("LOCKED_VIOLATION", lockedId, "Locked module differs from pre-transaction snapshot")
    }
    // Future situation checks (required components, data source, control target) are opt-in.
    for (var n=0; n<(e.extraChecks || []).length; ++n) {
        var name = e.extraChecks[n], check = extensions && extensions[name]
        if (typeof check !== "function") { fail("CHECK_UNAVAILABLE", "", "Missing extension " + name); continue }
        try {
            var extra = check(s,e)
            if (!Array.isArray(extra)) throw new Error("Extension must return failures array")
            for (var q=0; q<extra.length; ++q) {
                var f = extra[q]
                if (!f || typeof f.code !== "string" || typeof f.detail !== "string") throw new Error("Invalid extension failure")
                fail(f.code, f.module, f.detail)
            }
        } catch (error) { fail("CHECK_UNAVAILABLE", "", name + ": " + String(error.message || error)) }
    }
    return {ok: failures.length === 0, failures: failures}
}
