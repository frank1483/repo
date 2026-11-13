.pragma library
// Host-only catalog builder for Loop.goalTemplate's single miniView readability goal.
// No model fields, Qt objects, I/O or execution ports enter this module.
// The host must present the minimum readable size and repair permissions on its
// confirmation card, then recheck guard/revision and geometry before Loop.start.
function buildReadableSpec(choiceId, host, core) {
    function need(ok, why) { if (!ok) throw new Error(why) }
    function finite(n) { return typeof n === "number" && isFinite(n) }
    function copy(x) { return JSON.parse(JSON.stringify(x)) }
    function rect(r) { return r && finite(r.x) && finite(r.y) && finite(r.w) && finite(r.h) && r.w > 0 && r.h > 0 }
    function close(a, b) { return finite(a) && finite(b) && Math.abs(a - b) <= 0.01 }
    function own(o, key) { return Object.prototype.hasOwnProperty.call(o, key) }
    need(host && core && typeof core.layoutTarget === "function" && typeof core.overlaps === "function", "host and Core required")
    need(choiceId === "GOAL_MINIVIEW_READABLE", "only the trusted miniView goal is supported")
    need(Array.isArray(host.candidates) && host.candidates.length > 0 && host.candidates.length <= 128, "bounded host candidates required")
    var selected = host.candidates.filter(function(c) { return c && c.id === choiceId })
    need(selected.length === 1, "missing or duplicate host goal")
    var c = selected[0]
    need(!own(c, "expected") && !own(c, "before") && !own(c, "repairFor"), "candidate cannot supply expectations or repair scope")
    need(c.kind === "layout" && c.module === "miniView" && c.op === "scale" && c.factor === 1.25, "goal template action mismatch")
    var policies = core.MODULES.filter(function(p) { return p.id === "miniView" })
    need(policies.length === 1 && policies[0].locked === false, "unlocked Core module policy required")
    var policy = policies[0], s = host.snapshot, g = host.goal, f = host.frame
    need(s && s.modules && rect(s.viewport) && Number.isInteger(s.page) && Number.isInteger(s.section), "measured snapshot required")
    var m = s.modules.miniView
    need(m && rect(m.rect) && m.page === policy.page && s.page === policy.page && m.visible === true && finite(m.opacity) && m.opacity > 0 && m.locked === false, "current visible unlocked miniView required")
    need(Number.isInteger(host.revision) && host.revision >= 0, "host revision required")
    need(g && g.kind === "readable" && finite(g.minWidth) && g.minWidth > 0 && finite(g.minHeight) && g.minHeight > 0, "explicit host readability minimums required")
    need(typeof g.allowMove === "boolean" && typeof g.allowShrink === "boolean" && typeof g.allowNavigate === "boolean", "explicit confirmation permissions required")
    // The existing executor uses container coordinates. Restrict this adapter to
    // host-attested translation-only frames and verify the measured current AABB.
    // Rotations, inherited scale, clipping and later layout changes need a fresh host adapter.
    need(f && f.mapping === "translation-only" && rect(f.base) && f.area && finite(f.area.w) && finite(f.area.h) &&
        f.area.w > 0 && f.area.h > 0 && f.area.w <= 32768 && f.area.h <= 32768, "supported container frame required (maximum 32768 per axis)")
    need(f.origin && finite(f.origin.x) && finite(f.origin.y) && f.override, "viewport origin and override required")
    var ov = f.override
    need(finite(ov.dx) && finite(ov.dy) && finite(ov.scale) && ov.scale > 0 && ov.hidden === false, "finite visible override required")
    need(Array.isArray(f.others) && f.others.length <= 128 && f.others.every(rect), "bounded measured container obstacles required")
    function projected(next) {
        return {x: f.origin.x + f.base.x + next.dx, y: f.origin.y + f.base.y + next.dy,
            w: f.base.w * next.scale, h: f.base.h * next.scale}
    }
    var current = projected(ov)
    need(["x", "y", "w", "h"].every(function(k) { return close(current[k], m.rect[k]) }), "frame does not match measured snapshot")
    function fits(next, avoid) {
        var r = projected(next), local = {x: r.x - f.origin.x, y: r.y - f.origin.y, w: r.w, h: r.h}
        return rect(r) && r.w >= g.minWidth && r.h >= g.minHeight &&
            local.x >= 0 && local.y >= 0 && local.x + local.w <= f.area.w && local.y + local.h <= f.area.h &&
            r.x >= s.viewport.x && r.y >= s.viewport.y && r.x + r.w <= s.viewport.x + s.viewport.w && r.y + r.h <= s.viewport.y + s.viewport.h &&
            (!avoid || !f.others.some(function(other) { return core.overlaps(local, other) }))
    }
    var expectation = {page: policy.page, modules: [{id: "miniView", visible: true,
        minWidth: g.minWidth, minHeight: g.minHeight, avoidOverlap: true}]}
    function action(op, arg) {
        var out = {kind: "layout", module: "miniView", op: op}
        if (op === "move") out.region = arg
        else if (op === "scale") out.factor = arg
        return out
    }
    function target(op, arg, before) {
        return core.layoutTarget(op, copy(f.base), copy(f.area), copy(before), arg, copy(f.others), policy)
    }
    var initial = target("scale", 1.25, ov)
    // A readability goal may start with overlap or overflow: these are precisely
    // the verifier failures for which the confirmed repair catalog is prepared.
    need(finite(initial.scale) && initial.scale >= ov.scale && initial.scale > 0, "invalid initial scale")
    var catalog = [{id: choiceId, label: String(c.label_zh || "放大小地圖並檢查可讀性").slice(0, 160),
        action: action("scale", 1.25), expected: copy(expectation)}]
    function add(id, label, a, expected, codes) {
        catalog.push({id: id, label: label, action: a, expected: copy(expected),
            repairFor: [choiceId], failureCodes: codes})
    }
    if (g.allowMove) {
        var regions = ["TL", "TC", "TR", "ML", "C", "MR", "BL", "BC", "BR"], seen = {}
        for (var i = 0; i < regions.length; ++i) {
            var next = target("move", regions[i], initial)
            var key = next.dx + ":" + next.dy + ":" + next.scale
            // Core.freeSpot returns its input when there is no space. Never
            // advertise that fallback as an available collision-free repair.
            if (!fits(next, true) || own(seen, key)) continue
            seen[key] = true
            add("REPAIR_MINIVIEW_MOVE_" + regions[i], "移動小地圖至可用空位", action("move", regions[i]), expectation,
                ["OVERLAP", "OCCLUDED", "OUT_OF_BOUNDS"])
        }
    }
    if (g.allowShrink) {
        // A relative factor is re-evaluated by the existing executor at dispatch.
        // Only a preview that stays above the declared minimum is advertised;
        // every actual step and the logical goal still require verification.
        var smaller = target("scale", 0.8, initial)
        if (smaller.scale < initial.scale && fits(smaller, false))
            add("REPAIR_MINIVIEW_SHRINK", "降一級尺寸並保留已確認的可讀下限", action("scale", 0.8), expectation,
                ["OVERLAP", "OCCLUDED", "OUT_OF_BOUNDS"])
    }
    if (g.allowNavigate) {
        need(core.PAGES.some(function(p) { return p.page === policy.page }), "module page absent from Core")
        add("REPAIR_MINIVIEW_PAGE", "回到小地圖所在畫面", {kind: "nav", page: policy.page, section: -1},
            {page: policy.page}, ["PAGE_NOT_REACHED", "MODULE_NOT_VISIBLE"])
    }
    return {goal: "小地圖可見、可讀、在畫面內且沒有未授權重疊", label: String(c.label_zh || "小地圖可讀性").slice(0, 160),
        catalog: catalog, steps: [choiceId], expected: copy(expectation),
        guard: {revision: host.revision, page: s.page, section: s.section},
        limitations: ["single-miniView-readability-goal", "translation-only-frame", "host-must-recheck-guard-before-start",
            "host-must-remeasure-after-layout-change", "registered-module-verification-only"]}
}
