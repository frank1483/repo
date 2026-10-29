.pragma library
// Qt host adapter, separated from the pure verifier. AABB after mapToItem transforms.
// paintOrder covers registered ordinary QQuickItems under one root; it is not a
// renderer inspection API for popups, layers, shaders, external windows or native video.
function capture(viewport, registry, policies, location, overrides) {
    function finite(n) { return typeof n === "number" && isFinite(n) }
    if (!viewport || !finite(viewport.width) || !finite(viewport.height) || viewport.width <= 0 || viewport.height <= 0)
        throw new Error("viewport is not ready")
    var order = [], visited = [], budget = 2048
    function walk(item) {
        if (--budget < 0 || visited.indexOf(item) >= 0) throw new Error("unsupported scene size or cycle")
        visited.push(item)
        if (item.layer && item.layer.enabled) throw new Error("layered rendering requires a renderer adapter")
        var children = [], list = item.children || []
        for (var i = 0; i < list.length; ++i) {
            if (!finite(list[i].z)) throw new Error("invalid stacking geometry")
            children.push({item: list[i], z: list[i].z, sibling: i})
        }
        children.sort(function(a, b) { return a.z - b.z || a.sibling - b.sibling })
        for (i = 0; i < children.length; ++i) if (children[i].z < 0) walk(children[i].item)
        order.push(item)
        for (i = 0; i < children.length; ++i) if (children[i].z >= 0) walk(children[i].item)
    }
    walk(viewport)
    var modules = {}, policyById = {}, loc = location || {}
    for (var p = 0; p < (policies || []).length; ++p) policyById[policies[p].id] = policies[p]
    for (var id in registry) {
        if (!Object.prototype.hasOwnProperty.call(registry, id)) continue
        var entry = registry[id], item = entry && entry.item, policy = policyById[id]
        if (!item || !policy) throw new Error("unrecognized registered module " + id)
        var rank = order.indexOf(item)
        if (rank < 0) throw new Error("module outside viewport " + id)
        if (!finite(item.width) || !finite(item.height)) throw new Error("invalid item size " + id)
        var points = [item.mapToItem(viewport, 0, 0), item.mapToItem(viewport, item.width, 0),
            item.mapToItem(viewport, 0, item.height), item.mapToItem(viewport, item.width, item.height)]
        var xs = [], ys = [], opacity = 1, visible = true, clipped = false, cursor = item, parentBudget = 2048
        for (var n = 0; n < points.length; ++n) {
            if (!points[n] || !finite(points[n].x) || !finite(points[n].y)) throw new Error("non-finite transform " + id)
            xs.push(points[n].x); ys.push(points[n].y)
        }
        while (cursor) {
            if (--parentBudget < 0) throw new Error("invalid parent chain " + id)
            visible = visible && cursor.visible === true
            if (!finite(cursor.opacity)) throw new Error("invalid opacity " + id)
            opacity *= cursor.opacity
            // Clipping needs polygon intersection, which this conservative adapter cannot prove.
            if (cursor !== item && cursor.clip === true) clipped = true
            if (cursor === viewport) break
            cursor = cursor.parent
        }
        if (cursor !== viewport) throw new Error("detached parent chain " + id)
        if (clipped) throw new Error("clipped ancestor requires a clipping adapter: " + id)
        var ov = overrides && overrides(id) || {}
        modules[id] = {page: policy.page, visible: visible, opacity: opacity, paintOrder: rank,
            rect: {x: Math.min.apply(Math, xs), y: Math.min.apply(Math, ys),
                w: Math.max.apply(Math, xs) - Math.min.apply(Math, xs), h: Math.max.apply(Math, ys) - Math.min.apply(Math, ys)},
            scale: typeof ov.scale === "number" ? ov.scale : 1, locked: policy.locked === true,
            // Conservative registered-module coverage; background/overlap exemptions require host metadata.
            occludes: true, collisionGroup: "content", textTruncated: false}
    }
    return {page: loc.page, section: loc.section, viewport: {x: 0, y: 0, w: viewport.width, h: viewport.height},
        modules: modules, geometryCoverage: "registered-items-aabb", paintOrderCoverage: "ordinary-qquickitems-single-root"}
}
