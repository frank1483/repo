.pragma library
// Pure host-side arithmetic; no I/O, model calls, token defaults or UI mutation.
// Public action colors are opaque #RRGGBB. Internal QML colors may be #AARRGGBB.
function need(ok, message) { if (!ok) throw new Error(message) }
function finite(x) { return typeof x === "number" && isFinite(x) }
function clamp(x) { return Math.max(0, Math.min(1, x)) }
function byte(x) { return Math.round(clamp(x) * 255) }
function hex(x) { return ("0" + byte(x).toString(16)).slice(-2).toUpperCase() }
function actionColor(value) {
    need(typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value), "opaque #RRGGBB required")
    return value.toUpperCase()
}
function rgba(value) {
    need(typeof value === "string" && /^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(value), "invalid QML color")
    var v = value.slice(1), alpha = 1
    if (v.length === 8) { alpha = parseInt(v.slice(0, 2), 16) / 255; v = v.slice(2) }
    return {r: parseInt(v.slice(0, 2), 16) / 255, g: parseInt(v.slice(2, 4), 16) / 255,
        b: parseInt(v.slice(4, 6), 16) / 255, a: alpha}
}
function rgbHex(c) { return "#" + hex(c.r) + hex(c.g) + hex(c.b) }
function checkedRgba(c) {
    need(c && [c.r, c.g, c.b, c.a].every(function(v) { return finite(v) && v >= 0 && v <= 1 }), "invalid rgba")
    return c
}
function composite(foreground, background) {
    var f = checkedRgba(foreground), b = checkedRgba(background), a = f.a + b.a * (1 - f.a)
    if (a === 0) return {r: 0, g: 0, b: 0, a: 0}
    function channel(key) { return (f[key] * f.a + b[key] * b.a * (1 - f.a)) / a }
    return {r: channel("r"), g: channel("g"), b: channel("b"), a: a}
}
function backdrop(layers) {
    need(Array.isArray(layers) && layers.length > 0 && layers.length <= 32, "bounded background stack required")
    var out = rgba(layers[0])
    need(out.a === 1, "bottom background must be opaque")
    for (var i = 1; i < layers.length; ++i) out = composite(rgba(layers[i]), out)
    return out
}
function luminance(color) {
    var c = checkedRgba(color)
    need(c.a === 1, "luminance requires an opaque composed color")
    function linear(x) { return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4) }
    return 0.2126 * linear(c.r) + 0.7152 * linear(c.g) + 0.0722 * linear(c.b)
}
function contrast(foreground, backgrounds) {
    var bg = backdrop(backgrounds), fg = composite(rgba(foreground), bg)
    var a = luminance(fg), b = luminance(bg)
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}
// Host supplies the real, complete token pairs and alpha stacks. No guessed pairs.
// normal includes ordinary labels; secondary is only the explicitly classified
// secondary text/icons allowed by the task (not a general WCAG text exemption).
function checkPairs(colors, pairs) {
    need(colors && typeof colors === "object" && !Array.isArray(colors), "palette required")
    need(Array.isArray(pairs) && pairs.length > 0 && pairs.length <= 512, "bounded contrast pairs required")
    var seen = {}, rows = [], pass = true
    function token(name) {
        need(typeof name === "string" && Object.prototype.hasOwnProperty.call(colors, name), "unknown color token")
        rgba(colors[name]); return colors[name]
    }
    for (var i = 0; i < pairs.length; ++i) {
        var p = pairs[i]
        need(p && typeof p.id === "string" && /^[A-Za-z0-9_.-]{1,96}$/.test(p.id) &&
            !Object.prototype.hasOwnProperty.call(seen, p.id), "invalid or duplicate pair id")
        seen[p.id] = true
        need(p.role === "normal" || p.role === "secondary", "explicit contrast role required")
        need(Array.isArray(p.backgrounds), "background token stack required")
        var value = contrast(token(p.foreground), p.backgrounds.map(token)), min = p.role === "normal" ? 4.5 : 3
        var ok = value >= min // Do not round up a failing ratio for display or acceptance.
        rows.push({id: p.id, ratio: value, minimum: min, pass: ok})
        if (!ok) pass = false
    }
    return {pass: pass, rows: rows}
}
function hsl(value) {
    var c = rgba(actionColor(value)), hi = Math.max(c.r, c.g, c.b), lo = Math.min(c.r, c.g, c.b)
    var d = hi - lo, l = (hi + lo) / 2, h = 0, s = 0
    if (d !== 0) {
        // Floating point division can yield 1.0000000000000002 at gamut edges.
        s = clamp(d / (1 - Math.abs(2 * l - 1)))
        if (hi === c.r) h = ((c.g - c.b) / d) % 6
        else if (hi === c.g) h = (c.b - c.r) / d + 2
        else h = (c.r - c.g) / d + 4
        h = (h * 60 + 360) % 360
    }
    return {h: h, s: s, l: l}
}
function fromHsl(h, s, l) {
    need(finite(h) && finite(s) && finite(l) && s >= 0 && s <= 1 && l >= 0 && l <= 1, "invalid HSL")
    h = (h % 360 + 360) % 360
    var c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = l - c / 2
    var v = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] :
        h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x]
    return rgbHex({r: v[0] + m, g: v[1] + m, b: v[2] + m})
}
function parseInput(value) {
    if (typeof value !== "string" || value.length > 256) return {kind: "clarify", reason: "invalid-input"}
    var text = value.trim(), names = {
        "青": "#00FFFF", "青色": "#00FFFF", "藍": "#0000FF", "藍色": "#0000FF",
        "紫": "#800080", "紫色": "#800080", "白": "#FFFFFF", "白色": "#FFFFFF",
        "黑": "#000000", "黑色": "#000000", "灰": "#808080", "灰色": "#808080",
        "紅": "#FF0000", "紅色": "#FF0000", "黃": "#FFFF00", "黃色": "#FFFF00",
        "綠": "#008000", "綠色": "#008000", "橘色": "#FFA500", "粉紅色": "#FFC0CB",
        "橘": "#FFA500", "橙": "#FFA500", "橙色": "#FFA500",
        "粉紅": "#FFC0CB", "粉": "#FFC0CB", "粉色": "#FFC0CB",
        "淺藍": "#ADD8E6", "淺藍色": "#ADD8E6", "淡藍": "#ADD8E6", "淡藍色": "#ADD8E6",
        "淡黃": "#FFFFE0", "淡黃色": "#FFFFE0", "淺黃": "#FFFFE0", "淺黃色": "#FFFFE0"
    }
    if (/^#[0-9a-fA-F]{6}$/.test(text)) return {kind: "color", color: actionColor(text)}
    if (Object.prototype.hasOwnProperty.call(names, text)) return {kind: "color", color: names[text]}
    var m = /^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/i.exec(text)
    if (m && [+m[1], +m[2], +m[3]].every(function(n) { return n <= 255 }))
        return {kind: "color", color: rgbHex({r: +m[1] / 255, g: +m[2] / 255, b: +m[3] / 255})}
    var relative = {"亮一點": "lighter", "暗一點": "darker", "暖一點": "warmer", "冷一點": "cooler"}
    if (Object.prototype.hasOwnProperty.call(relative, text)) return {kind: "relative", direction: relative[text]}
    // The caller may ask its already-authorized model to propose a color value.
    // This module never calls one, turns vague language into approval or executes it.
    return {kind: "clarify", reason: "unresolved-color", text: text}
}
function relativeColor(current, direction, amount) {
    var source = actionColor(current)
    need(finite(amount) && amount > 0 && amount <= 1, "explicit relative amount required")
    need(["lighter", "darker", "warmer", "cooler"].indexOf(direction) >= 0, "invalid relative direction")
    if (direction === "lighter" || direction === "darker") {
        var c = hsl(source)
        return fromHsl(c.h, c.s, clamp(c.l + (direction === "lighter" ? amount : -amount)))
    }
    // A declared channel tilt, not a claim to perceptual temperature invariance.
    var rgb = rgba(source), sign = direction === "warmer" ? 1 : -1
    return rgbHex({r: clamp(rgb.r + sign * amount), g: rgb.g, b: clamp(rgb.b - sign * amount)})
}
// Host-derived token generation; mix/alpha recipes must come from the actual
// theme integration, not a model. This primitive assigns no token names itself.
function derive(base, mix, alpha) {
    var c = rgba(actionColor(base))
    need(finite(mix) && mix >= -1 && mix <= 1 && finite(alpha) && alpha >= 0 && alpha <= 1, "invalid host recipe")
    function channel(x) { return mix < 0 ? x * (1 + mix) : x + (1 - x) * mix }
    var value = rgbHex({r: channel(c.r), g: channel(c.g), b: channel(c.b)})
    return alpha === 1 ? value : "#" + hex(alpha) + value.slice(1)
}
function hueDistance(a, b) { var d = Math.abs(a - b) % 360; return Math.min(d, 360 - d) }
function safeAccent(value, statusColors, minimumHueDistance) {
    var c = hsl(value)
    need(Array.isArray(statusColors) && statusColors.length > 0 && statusColors.length <= 128, "actual status colors required")
    need(finite(minimumHueDistance) && minimumHueDistance > 0 && minimumHueDistance <= 180, "explicit host hue distance required")
    var statuses = statusColors.map(function(v) { return hsl(actionColor(v)) })
    // Achromatic shortcuts have no hue. Their contrast is still checked separately.
    return c.s === 0 || statuses.every(function(s) { return s.s === 0 || hueDistance(c.h, s.h) >= minimumHueDistance })
}
// Search a bounded lightness grid in nearest-first order. Host check must rebuild
// all derived tokens and test all real pairs. No mutation/candidate is returned
// unless the FINAL quantized #RRGGBB passes. Search failure never applies a color.
function fitLightness(requested, check) {
    requested = actionColor(requested)
    need(typeof check === "function", "trusted host palette check required")
    var calls = 0, seen = {}, c = hsl(requested)
    function passes(value) {
        if (Object.prototype.hasOwnProperty.call(seen, value)) return false
        seen[value] = true; calls++
        var result = check(value)
        need(typeof result === "boolean", "host check must return boolean")
        return result
    }
    if (passes(requested)) return {ok: true, requested: requested, color: requested, confirmation: false, checks: calls}
    var levels = []
    for (var i = 0; i <= 1024; ++i) levels.push(i / 1024)
    levels.sort(function(a, b) { return Math.abs(a - c.l) - Math.abs(b - c.l) || a - b })
    for (var j = 0; j < levels.length; ++j) {
        var color = fromHsl(c.h, c.s, levels[j])
        if (passes(color)) return {ok: true, requested: requested, color: color, confirmation: true, checks: calls}
    }
    return {ok: false, requested: requested, color: null, confirmation: false, checks: calls, reason: "no-grid-solution"}
}
// Nearest hue search after the caller supplies the actual status palette and
// explicit separation policy. A passing original hue always takes precedence.
function fitAccent(requested, statusColors, minimumHueDistance, check) {
    requested = actionColor(requested)
    need(typeof check === "function", "trusted host palette check required")
    var originalSafe = safeAccent(requested, statusColors, minimumHueDistance), c = hsl(requested)
    function gate(color) { return safeAccent(color, statusColors, minimumHueDistance) && check(color) }
    if (originalSafe) return fitLightness(requested, gate)
    var hues = []
    for (var i = 0; i < 360; ++i) hues.push(i)
    hues.sort(function(a, b) { return hueDistance(a, c.h) - hueDistance(b, c.h) || a - b })
    var calls = 0
    for (var j = 0; j < hues.length; ++j) {
        var trial = fromHsl(hues[j], c.s, c.l)
        if (!safeAccent(trial, statusColors, minimumHueDistance)) continue
        var result = fitLightness(trial, gate)
        calls += result.checks
        if (result.ok) return {ok: true, requested: requested, color: result.color, confirmation: true, checks: calls,
            reason: "status-hue-conflict"}
    }
    return {ok: false, requested: requested, color: null, confirmation: false, checks: calls, reason: "no-safe-hue-grid-solution"}
}
