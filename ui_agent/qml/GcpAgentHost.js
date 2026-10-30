.pragma library
// Read-only Qt host input for the single miniView goal. No model or execution ports.
// Only direct-child targets and measured translation-only container mappings qualify.
function captureReadable(viewport, registry, policies, location, overrideOf, revision, goal, candidates, snapshotAdapter) {
    function need(ok, why) { if (!ok) throw new Error(why) }
    function finite(n) { return typeof n === "number" && isFinite(n) }
    function copy(x) { return JSON.parse(JSON.stringify(x)) }
    function close(a, b) { return finite(a) && finite(b) && Math.abs(a - b) <= 0.01 }
    function point(p, x, y) { return p && close(p.x, x) && close(p.y, y) }
    need(Number.isInteger(revision) && revision >= 0, "host revision required")
    need(snapshotAdapter && typeof snapshotAdapter.capture === "function" && typeof overrideOf === "function", "snapshot and override adapters required")
    need(registry && Object.keys(registry).length <= 128, "bounded registry required")
    var entry = registry.miniView, item = entry && entry.item, container = entry && entry.container
    need(item && container && item.parent === container, "miniView must be a direct child of its executor container")
    need(finite(container.width) && finite(container.height) && container.width > 0 && container.height > 0 &&
        container.width <= 32768 && container.height <= 32768, "container bounds unsupported")
    need(finite(item.x) && finite(item.y) && finite(item.width) && finite(item.height) && item.width > 0 && item.height > 0, "target geometry unavailable")
    need(typeof container.mapToItem === "function" && typeof item.mapToItem === "function", "Qt mapping ports required")
    var origin = container.mapToItem(viewport, 0, 0), w = container.width, h = container.height
    need(origin && finite(origin.x) && finite(origin.y), "invalid container origin")
    var samples = [[w, 0], [0, h], [w, h], [w / 2, h / 2], [1, 0], [0, 1]]
    for (var i = 0; i < samples.length; ++i) {
        var xy = samples[i]
        need(point(container.mapToItem(viewport, xy[0], xy[1]), origin.x + xy[0], origin.y + xy[1]),
            "container mapping is not translation-only")
    }
    var ov = overrideOf("miniView")
    need(ov && finite(ov.dx) && finite(ov.dy) && finite(ov.scale) && ov.scale > 0 && ov.hidden === false, "visible finite override required")
    var localX = item.x + ov.dx, localY = item.y + ov.dy
    var targetSamples = [[0, 0], [item.width, 0], [0, item.height], [item.width, item.height], [item.width / 2, item.height / 2]]
    for (i = 0; i < targetSamples.length; ++i) {
        var q = targetSamples[i]
        need(point(item.mapToItem(container, q[0], q[1]), localX + q[0] * ov.scale, localY + q[1] * ov.scale),
            "target transform does not match executor override")
    }
    var snapshot = snapshotAdapter.capture(viewport, registry, policies, location, overrideOf)
    need(snapshot && snapshot.modules && snapshot.modules.miniView, "measured target missing")
    var others = []
    // Include every registered visible current-page module, even in another container.
    // Unregistered items and native/popup rendering remain outside this adapter's coverage.
    for (var id in snapshot.modules) {
        if (!Object.prototype.hasOwnProperty.call(snapshot.modules, id) || id === "miniView") continue
        var m = snapshot.modules[id], r = m.rect
        if (m.page !== snapshot.page || m.visible !== true || !(m.opacity > 0)) continue
        need(r && finite(r.x) && finite(r.y) && finite(r.w) && finite(r.h) && r.w >= 0 && r.h >= 0, "invalid measured obstacle")
        if (r.w > 0 && r.h > 0) others.push({x: r.x - origin.x, y: r.y - origin.y, w: r.w, h: r.h})
    }
    return {revision: revision, candidates: copy(candidates), goal: copy(goal), snapshot: copy(snapshot),
        frame: {mapping: "translation-only", base: {x: item.x, y: item.y, w: item.width, h: item.height},
            area: {w: w, h: h}, origin: {x: origin.x, y: origin.y}, override: copy(ov), others: others}}
}

// Trusted host policy only; the model must never construct or mutate this object.
function prepareReadable(host, core, catalogAdapter) {
    if (!catalogAdapter || typeof catalogAdapter.buildReadableSpec !== "function") throw new Error("catalog adapter required")
    var input = JSON.parse(JSON.stringify(host))
    var spec = catalogAdapter.buildReadableSpec("GOAL_MINIVIEW_READABLE", input, core)
    var g = input.goal
    var summary = "小地圖可讀下限：寬 " + g.minWidth + " × 高 " + g.minHeight + "（畫面座標單位）\n" +
        "修補權限：移動" + (g.allowMove ? "允許" : "不允許") + "；降尺寸" + (g.allowShrink ? "允許" : "不允許") +
        "；回所在畫面" + (g.allowNavigate ? "允許" : "不允許") + "\n" +
        "降尺寸仍須保留可讀下限；最多五輪，失敗整組復原。"
    return {spec: spec, summary: summary, basis: input,
        limitations: ["host-policy-only", "confirm-and-recapture-before-start", "registered-items-only", "Qt-layout-unverified"]}
}

// Compare the complete fresh input, not revision alone: resize/animation/opacity may
// change without State.revision. Object key order is irrelevant; array order is retained.
function assertReadableCurrent(prepared, fresh, core, catalogAdapter) {
    function canonical(x) {
        if (x === null || typeof x !== "object") return JSON.stringify(x)
        if (Array.isArray(x)) return "[" + x.map(canonical).join(",") + "]"
        return "{" + Object.keys(x).sort().map(function(k) { return JSON.stringify(k) + ":" + canonical(x[k]) }).join(",") + "}"
    }
    if (!prepared || !prepared.basis || !fresh) throw new Error("confirmation basis required")
    var rebuilt = prepareReadable(fresh, core, catalogAdapter)
    if (canonical(prepared.basis) !== canonical(rebuilt.basis)) throw new Error("readability confirmation is stale; show a fresh card")
    if (canonical(prepared.spec) !== canonical(rebuilt.spec) || prepared.summary !== rebuilt.summary)
        throw new Error("confirmation payload changed")
    // Return a rebuilt detached spec so a stale/mutated caller object cannot execute.
    return rebuilt.spec
}
