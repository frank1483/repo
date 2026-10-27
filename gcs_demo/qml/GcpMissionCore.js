.pragma library
// 任務規劃與智慧任務報告的演算法核心（gcs_demo/*.py 的 JS 移植，給 APK 內的 QML 用）。
// 純 JS、不碰 QML 物件；node 也能載入（test/test_core.js 用它和 Python 版比對）。
// 原則同共用介面：演算法算數字、產生候選、先做規則選擇；模型只在候選內選 ID 或改寫有證據的建議。

var R_EARTH = 6371000.0
var RHO = 1.225
var G = 9.81

function rnd(x, n) { var k = Math.pow(10, n || 0); return Math.round(x * k) / k }
function rad(d) { return d * Math.PI / 180 }
function clone(o) { return JSON.parse(JSON.stringify(o)) }

// ---------------- 能耗 ----------------

function haversineM(a, b) {
    var lat1 = rad(a[0]), lon1 = rad(a[1]), lat2 = rad(b[0]), lon2 = rad(b[1])
    var h = Math.pow(Math.sin((lat2 - lat1) / 2), 2) +
            Math.cos(lat1) * Math.cos(lat2) * Math.pow(Math.sin((lon2 - lon1) / 2), 2)
    return 2 * R_EARTH * Math.asin(Math.sqrt(h))
}

function bearingRad(a, b) {
    var lat1 = rad(a[0]), lon1 = rad(a[1]), lat2 = rad(b[0]), lon2 = rad(b[1])
    var y = Math.sin(lon2 - lon1) * Math.cos(lat2)
    var x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(lon2 - lon1)
    return Math.atan2(y, x)
}

function vehicle(over) {
    var v = { vehicle_id: "UAV-01", mass_kg: 2.0, battery_wh: 90.0, usable_frac: 0.9, p_hover_w: 190.0,
              cda_m2: 0.12, eta: 0.7, cruise_mps: 8.0, max_mps: 15.0, reserve_pct: 20.0, calib: 1.0 }
    for (var k in (over || {})) v[k] = over[k]
    return v
}

// NaN 不能用 || 0 靜默變成無風；僅缺省值使用 0。
function wind(speed, fromDeg) {
    return { speed_mps: speed === undefined ? 0 : speed, from_deg: fromDeg === undefined ? 0 : fromDeg }
}

function windVector(w) {
    var to = rad(w.from_deg + 180.0)
    return [w.speed_mps * Math.sin(to), w.speed_mps * Math.cos(to)]   // (east, north)
}

function powerW(v, vAir) { return v.p_hover_w + 0.5 * RHO * v.cda_m2 * Math.pow(vAir, 3) / v.eta }

function legEstimate(v, a, b, altA, altB, groundMps, w) {
    var dist = haversineM(a, b), t = 0, vAir = 0, head = 0
    if (dist >= 0.5) {
        var brg = bearingRad(a, b)
        var ge = groundMps * Math.sin(brg), gn = groundMps * Math.cos(brg)
        var wv = windVector(w)
        vAir = Math.hypot(ge - wv[0], gn - wv[1])
        head = -(wv[0] * Math.sin(brg) + wv[1] * Math.cos(brg))
        t = dist / groundMps
    }
    var eJ = powerW(v, vAir) * t
    var climb = Math.max(0, altB - altA)
    eJ += v.mass_kg * G * climb / v.eta
    var vt = climb > 0 ? climb / 3.0 : Math.max(0, altA - altB) / 2.0
    t += vt
    eJ += v.p_hover_w * vt
    return { dist_m: dist, time_s: t, energy_wh: eJ / 3600.0 * v.calib, v_air: vAir, headwind_mps: head }
}

function routeEstimate(v, points, groundMps, w, startPct, hoverS) {
    if (startPct === undefined) startPct = 100.0
    if (hoverS === undefined) hoverS = 5.0
    var legs = [], wh = 0, ts = 0, dm = 0, cap = v.battery_wh * v.usable_frac, pct = startPct
    for (var i = 0; i < points.length - 1; i++) {
        var a = points[i], b = points[i + 1]
        var e = legEstimate(v, [a.lat, a.lon], [b.lat, b.lon], a.alt || 0, b.alt || 0, groundMps, w)
        var hover = b.kind === "target" ? hoverS : 0
        e.energy_wh += v.p_hover_w * hover / 3600.0 * v.calib
        e.time_s += hover
        pct -= e.energy_wh / cap * 100.0
        e.from = a.id; e.to = b.id; e.pct_after = pct
        legs.push(e)
        wh += e.energy_wh; ts += e.time_s; dm += e.dist_m
    }
    return { dist_m: dm, time_s: ts, energy_wh: wh, end_pct: pct, used_pct: startPct - pct,
             margin_pct: pct - v.reserve_pct, feasible: pct >= v.reserve_pct, legs: legs }
}

function bestSpeed(v, w, headingDeg) {
    var a = [0, 0], b = [0.001 * Math.cos(rad(headingDeg || 0)), 0.001 * Math.sin(rad(headingDeg || 0))]
    var best = null
    for (var s = 4.0; s <= v.max_mps + 1e-9; s += 0.5) {
        var e = legEstimate(v, a, b, 0, 0, s, w)
        var perKm = e.energy_wh / Math.max(e.dist_m, 1) * 1000
        if (best === null || perKm < best[1]) best = [rnd(s, 1), perKm]
    }
    if (best === null) return { speed_mps: null, wh_per_km: null, error: "沒有可搜尋的速度" }
    return { speed_mps: best[0], wh_per_km: rnd(best[1], 2) }
}

// ---------------- 禁航區 ----------------

function toXY(o, p) {
    var lat0 = rad(o[0])
    return [rad(p[1] - o[1]) * R_EARTH * Math.cos(lat0), rad(p[0] - o[0]) * R_EARTH]
}
function toLL(o, xy) {
    var lat0 = rad(o[0])
    return [o[0] + xy[1] / R_EARTH * 180 / Math.PI, o[1] + xy[0] / (R_EARTH * Math.cos(lat0)) * 180 / Math.PI]
}
function segCircleHit(a, b, c, r) {
    var dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy
    var t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((c[0] - a[0]) * dx + (c[1] - a[1]) * dy) / l2))
    var px = a[0] + t * dx, py = a[1] + t * dy
    return Math.hypot(px - c[0], py - c[1]) < r ? t : null
}

function insertDetours(points, zones, origin) {
    if (!points.length) return []
    var out = [points[0]], n = 0
    for (var i = 1; i < points.length; i++) {
        var b = points[i], a = out[out.length - 1]
        for (var j = 0; j < zones.length; j++) {
            var z = zones[j]
            var A = toXY(origin, [a.lat, a.lon]), B = toXY(origin, [b.lat, b.lon]), C = toXY(origin, [z.lat, z.lon])
            if (segCircleHit(A, B, C, z.radius_m) === null) continue
            var dx = B[0] - A[0], dy = B[1] - A[1], L = Math.hypot(dx, dy) || 1
            var nx = -dy / L, ny = dx / L, mx = (A[0] + B[0]) / 2, my = (A[1] + B[1]) / 2
            var side = (mx - C[0]) * nx + (my - C[1]) * ny >= 0 ? 1 : -1
            var r = z.radius_m * 1.35
            var w = toLL(origin, [C[0] + side * nx * r, C[1] + side * ny * r])
            n += 1
            out.push({ id: "繞" + z.id + "-" + n, lat: w[0], lon: w[1], alt: Math.max(a.alt || 0, b.alt || 0), kind: "detour" })
            break
        }
        out.push(b)
    }
    return out
}

function zoneViolations(points, zones, origin) {
    var bad = []
    for (var i = 0; i < points.length - 1; i++) {
        var A = toXY(origin, [points[i].lat, points[i].lon]), B = toXY(origin, [points[i + 1].lat, points[i + 1].lon])
        for (var j = 0; j < zones.length; j++) {
            var z = zones[j]
            if (segCircleHit(A, B, toXY(origin, [z.lat, z.lon]), z.radius_m) !== null)
                bad.push(points[i].id + "→" + points[i + 1].id + " 穿越 " + z.id)
        }
    }
    return bad
}

// ---------------- 排序 ----------------

function costFn(v, w, speed, mode) {
    return function (a, b) {
        if (mode === "dist") return haversineM([a.lat, a.lon], [b.lat, b.lon])
        return routeEstimate(v, [a, b], speed, w).energy_wh
    }
}

function orderTargets(start, targets, end, cost) {
    var rem = targets.slice(), seq = [], cur = start
    while (rem.length) {
        var bi = 0
        for (var i = 1; i < rem.length; i++) if (cost(cur, rem[i]) < cost(cur, rem[bi])) bi = i
        cur = rem.splice(bi, 1)[0]
        seq.push(cur)
    }
    function total(s) {
        var p = [start].concat(s, [end]), c = 0
        for (var i = 0; i < p.length - 1; i++) c += cost(p[i], p[i + 1])
        return c
    }
    var best = total(seq), improved = true
    while (improved && seq.length > 2) {
        improved = false
        for (var a = 0; a < seq.length - 1; a++)
            for (var b = a + 1; b < seq.length; b++) {
                var cand = seq.slice(0, a).concat(seq.slice(a, b + 1).reverse(), seq.slice(b + 1))
                var c = total(cand)
                if (c < best - 1e-9) { seq = cand; best = c; improved = true }
            }
    }
    return seq
}

// ---------------- 候選 ----------------

function evaluate(cid, label, how, mission, v, w, path, speed, startPct) {
    var origin = [mission.home.lat, mission.home.lon], zones = mission.no_fly || []
    path = insertDetours(path, zones, origin)
    var est = routeEstimate(v, path, speed, w, startPct)
    var viol = zoneViolations(path, zones, origin)
    var maxAlt = (mission.limits || {}).max_altitude_m || 120
    path.forEach(function (p) { if ((p.alt || 0) > maxAlt) viol.push(p.id + " 高度 " + p.alt + " m 超過上限 " + maxAlt + " m") })
    var tids = path.filter(function (p) { return p.kind === "target" }).map(function (p) { return p.id })
    var must = mission.targets.filter(function (t) { return (t.priority || 1) === 1 }).map(function (t) { return t.id })
    var done = mission.completed || []
    var missing = must.filter(function (m) { return tids.indexOf(m) < 0 && done.indexOf(m) < 0 })
    var mustRank = 0
    tids.forEach(function (t, i) { if (must.indexOf(t) >= 0) mustRank += i })
    return {
        id: cid, label: label, how: how, order: tids, speed_mps: speed, calib: v.calib,
        dist_km: rnd(est.dist_m / 1000, 2), time_min: rnd(est.time_s / 60, 1),
        energy_wh: rnd(est.energy_wh, 1), end_pct: rnd(est.end_pct, 1), margin_pct: rnd(est.margin_pct, 1),
        feasible: est.feasible && viol.length === 0 && missing.length === 0,
        violations: viol, missing_must: missing, must_rank: mustRank,
        path: path.map(function (p) { return { id: p.id, lat: p.lat, lon: p.lon, alt: p.alt || 0, kind: p.kind, priority: p.priority } }),
        legs: est.legs.map(function (l) {
            return { from: l.from, to: l.to, dist_m: rnd(l.dist_m, 2), time_s: rnd(l.time_s, 2), energy_wh: rnd(l.energy_wh, 2),
                     headwind_mps: rnd(l.headwind_mps, 2), pct_after: rnd(l.pct_after, 2) }
        })
    }
}

function ruleChoice(cands) {
    var feas = cands.filter(function (c) { return c.feasible })
    if (!feas.length) return ""
    var best = feas.reduce(function (a, c) {
        if (c.order.length !== a.order.length) return c.order.length > a.order.length ? c : a
        return c.energy_wh < a.energy_wh ? c : a
    })
    // 能耗差 3% 以內視為同等，改選「必要目標較早完成」者
    var near = feas.filter(function (c) { return c.order.length === best.order.length && c.energy_wh <= best.energy_wh * 1.03 })
    return near.reduce(function (a, c) {
        if (c.must_rank !== a.must_rank) return c.must_rank < a.must_rank ? c : a
        return c.energy_wh < a.energy_wh ? c : a
    }).id
}

function evidenceFor(cands, v, w, extra) {
    var ev = [{ id: "E1", text: "風速 " + w.speed_mps + " m/s，風從 " + Math.round(w.from_deg) + "° 吹來" },
              { id: "E2", text: "電池 " + v.battery_wh + " Wh，可用 " + Math.round(v.usable_frac * 100) + "%，落地保留 " +
                                v.reserve_pct + "%，耗電修正係數 " + v.calib.toFixed(2) }]
    cands.forEach(function (c, i) {
        var why = c.violations.concat(c.missing_must)
        ev.push({ id: "E" + (i + 3), text: c.id + " " + c.label + "：落地剩 " + c.end_pct + "%，" + (c.feasible ? "可行" : "不可行") +
                                       (!c.feasible && why.length ? "（" + why.join("；") + "）" : "") })
    })
    ;(extra || []).forEach(function (e) { ev.push({ id: "E" + (ev.length + 1), text: e }) })
    return ev
}

function brief(c) {
    return { id: c.id, label: c.label, order: c.order, speed_mps: c.speed_mps, dist_km: c.dist_km, time_min: c.time_min,
             energy_wh: c.energy_wh, end_pct: c.end_pct, margin_pct: c.margin_pct, feasible: c.feasible }
}

function home(m) { var h = clone(m.home); if (!h.id) h.id = "H"; h.alt = 0; h.kind = "home"; return h }
function targets(m) { return m.targets.map(function (t) { var p = clone(t); p.kind = "target"; return p }) }

function rulePick(rc, text) {
    return rc ? { choice_id: rc, source: "rule", decision: "SELECT", reason_zh: text || "規則選擇：可行候選中能耗最低且涵蓋所有必要目標。", evidence_ids: [] }
              : { choice_id: "", source: "rule", decision: "HOLD", reason_zh: "所有候選都不可行（電量或限制不符），建議換電池、分兩趟或減少目標。", evidence_ids: [] }
}

// ---------------- 入口邊界（不改有效輸入的排序、能耗公式或候選 ID） ----------------
function finiteNumber(x) { return typeof x === "number" && isFinite(x) }
function coordinate(p) {
    return p && finiteNumber(p.lat) && finiteNumber(p.lon) && Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180
}
function inputError(m, v, w, allowEmpty) {
    if (!m || !coordinate(m.home) || !Array.isArray(m.targets)) return "home 或航點格式無效"
    if (!allowEmpty && !m.targets.length) return "沒有任務航點，請先加入目標"
    if (!v || !w || !finiteNumber(w.speed_mps) || w.speed_mps < 0 || !finiteNumber(w.from_deg)) return "風速或風向無效"
    var positive = ["mass_kg", "battery_wh", "usable_frac", "p_hover_w", "eta", "cruise_mps", "max_mps", "calib"]
    for (var i = 0; i < positive.length; ++i)
        if (!finiteNumber(v[positive[i]]) || v[positive[i]] <= 0) return "載具數值無效：" + positive[i]
    if (v.max_mps < 4 || v.usable_frac > 1 || v.eta > 1 || !finiteNumber(v.cda_m2) || v.cda_m2 < 0 ||
        !finiteNumber(v.reserve_pct) || v.reserve_pct < 0 || v.reserve_pct > 100) return "載具限制無效"
    if (m.speed_mps !== undefined && (!finiteNumber(m.speed_mps) || m.speed_mps <= 0)) return "任務速度無效"
    if (m.cruise_alt_m !== undefined && (!finiteNumber(m.cruise_alt_m) || m.cruise_alt_m < 0)) return "巡航高度無效"
    var seenIds = [String(m.home.id || "H")], positions = []
    for (i = 0; i < m.targets.length; ++i) {
        var t = m.targets[i]
        if (!coordinate(t) || typeof t.id !== "string" || !t.id ||
            (t.alt !== undefined && (!finiteNumber(t.alt) || t.alt < 0))) return "航點欄位無效"
        var xyz = [t.lat, t.lon, t.alt === undefined ? (m.cruise_alt_m || 50) : t.alt].join(",")
        if (seenIds.indexOf(t.id) >= 0 || positions.indexOf(xyz) >= 0) return "重複航點 ID 或位置，請先釐清目標"
        seenIds.push(t.id); positions.push(xyz)
    }
    if (m.no_fly !== undefined && !Array.isArray(m.no_fly)) return "禁航區格式無效"
    for (i = 0; i < (m.no_fly || []).length; ++i) {
        var z = m.no_fly[i]
        if (!coordinate(z) || !finiteNumber(z.radius_m) || z.radius_m <= 0) return "禁航區數值無效"
    }
    return ""
}
function boundaryHold(kind, why) {
    return { kind: kind, candidates: [], rule_choice: "", pick: {
        decision: "HOLD", choice_id: "", source: "rule", reason_zh: why, evidence_ids: ["E1"]
    }, evidence: [{ id: "E1", text: why }], task_zh: "輸入待釐清，未產生可執行建議" }
}
function stateError(m, s) {
    if (!s || !coordinate(s) || !finiteNumber(s.battery_pct) || s.battery_pct < 0 || s.battery_pct > 100 ||
        (s.alt !== undefined && (!finiteNumber(s.alt) || s.alt < 0)) ||
        (s.observed_ratio !== undefined && (!finiteNumber(s.observed_ratio) || s.observed_ratio <= 0)) ||
        !Array.isArray(s.remaining) || !Array.isArray(s.completed)) return "重規劃遙測或目標清單無效"
    var ids = m.targets.map(function (t) { return t.id }), seen = []
    var all = s.remaining.concat(s.completed)
    for (var i = 0; i < all.length; ++i) {
        if (ids.indexOf(all[i]) < 0 || seen.indexOf(all[i]) >= 0) return "剩餘／已完成航點重複或不存在"
        seen.push(all[i])
    }
    return ""
}

function planMission(mission, v, w) {
    var invalid = inputError(mission, v, w, false)
    if (invalid) return boundaryHold("plan", invalid)
    var alt = mission.cruise_alt_m || 50, h = home(mission), tg = targets(mission)
    tg.forEach(function (t) { if (t.alt === undefined) t.alt = alt })
    var v0 = mission.speed_mps || v.cruise_mps, end = home(mission), c = []
    c.push(evaluate("C1", "照輸入順序", "使用者給的順序", mission, v, w, [h].concat(tg, [end]), v0, 100))
    var sd = orderTargets(h, tg, end, costFn(v, w, v0, "dist"))
    c.push(evaluate("C2", "最短距離", "最近鄰居＋2-opt（距離）", mission, v, w, [h].concat(sd, [end]), v0, 100))
    var se = orderTargets(h, tg, end, costFn(v, w, v0, "energy"))
    c.push(evaluate("C3", "最省電順序", "最近鄰居＋2-opt（含風的能耗）", mission, v, w, [h].concat(se, [end]), v0, 100))
    var bs = bestSpeed(v, w, w.from_deg % 360).speed_mps
    if (Math.abs(bs - v0) >= 0.5)
        c.push(evaluate("C4", "最省電順序＋改速 " + bs + " m/s", "能耗最低地速", mission, v, w, [h].concat(se, [end]), bs, 100))
    var tm = tg.filter(function (t) { return (t.priority || 1) === 1 })
    if (tm.length < tg.length) {
        var sm = orderTargets(h, tm, end, costFn(v, w, v0, "energy"))
        c.push(evaluate("C5", "只做必要目標", "刪除選配目標後重排", mission, v, w, [h].concat(sm, [end]), v0, 100))
    }
    var rc = ruleChoice(c)
    return { kind: "plan", candidates: c, rule_choice: rc, pick: rulePick(rc), evidence: evidenceFor(c, v, w),
             task_zh: "出發前任務規劃：選一條航線。必要目標都要做到，落地電量要高於保留值。",
             vehicle: v, wind: w }
}

function replan(mission, v0in, w, state, event) {
    var invalid = inputError(mission, v0in, w, true)
    if (invalid) return boundaryHold("replan", invalid)
    invalid = stateError(mission, state)
    if (invalid || !event || typeof event !== "object") return boundaryHold("replan", invalid || "事件格式無效")
    if (event.type === "add_target" && !event.target) return boundaryHold("replan", "新增目標格式無效")
    var m = clone(mission), note = event.text_zh || ""
    var v = clone(v0in)
    var ratio = state.observed_ratio !== undefined ? state.observed_ratio : v.calib
    v.calib = rnd(ratio, 3)
    if (event.type === "wind") w = wind(event.speed_mps, event.from_deg)
    else if (event.type === "no_fly") { m.no_fly = (m.no_fly || []).concat([event.zone]) }
    else if (event.type === "add_target") { m.targets.push(event.target); state = clone(state); state.remaining.push(event.target.id) }
    else if (event.type === "battery") { state = clone(state); state.battery_pct = event.battery_pct }
    invalid = inputError(m, v, w, true) || stateError(m, state)
    if (invalid) return boundaryHold("replan", invalid)
    m.completed = state.completed
    var cur = { id: "現在位置", lat: state.lat, lon: state.lon, alt: state.alt !== undefined ? state.alt : (m.cruise_alt_m || 50), kind: "current" }
    var end = home(m)
    var rem = state.remaining.map(function (id) { return targets(m).filter(function (t) { return t.id === id })[0] }).filter(Boolean)
    rem.forEach(function (t) { if (t.alt === undefined) t.alt = m.cruise_alt_m || 50 })
    var s0 = m.speed_mps || v.cruise_mps, pct = state.battery_pct, c = []
    var local = evaluate("L1", "LOCAL 局部修補", "保留剩餘順序，只繞禁航區", m, v, w, [cur].concat(rem, [end]), s0, pct)
    c.push(local)
    if (!local.feasible) {
        var trimmed = rem.slice(), lc = null
        while (trimmed.length && trimmed.some(function (t) { return (t.priority || 1) === 2 })) {
            var idx = -1
            trimmed.forEach(function (t, i) { if ((t.priority || 1) === 2) idx = i })
            trimmed.splice(idx, 1)
            lc = evaluate("L2", "LOCAL 刪選配目標", "保留順序，刪掉尾端選配目標", m, v, w, [cur].concat(trimmed, [end]), s0, pct)
            if (lc.feasible) break
        }
        if (lc) c.push(lc)
        var mustOnly = rem.filter(function (t) { return (t.priority || 1) === 1 })
        var ids = function (a) { return a.map(function (t) { return t.id }).join(",") }
        if (mustOnly.length && mustOnly.length < rem.length && ids(mustOnly) !== ids(trimmed))
            c.push(evaluate("L3", "LOCAL 只留必要目標", "保留順序，刪掉所有選配目標", m, v, w, [cur].concat(mustOnly, [end]), s0, pct))
    }
    var sf = orderTargets(cur, rem, end, costFn(v, w, s0, "energy"))
    c.push(evaluate("F1", "FULL 全部重排", "剩餘目標以能耗重新排序", m, v, w, [cur].concat(sf, [end]), s0, pct))
    var bs = bestSpeed(v, w, w.from_deg % 360).speed_mps
    if (Math.abs(bs - s0) >= 0.5)
        c.push(evaluate("F2", "FULL 重排＋改速 " + bs + " m/s", "重排並改用最省電速度", m, v, w, [cur].concat(sf, [end]), bs, pct))
    if (!c.some(function (x) { return x.feasible }) && rem.length > 1) {
        var best = null
        ;[["LOCAL", rem], ["FULL", sf]].forEach(function (p) {
            for (var k = p[1].length - 1; k > 0; k--) {
                var pc = evaluate("P1", p[0] + " 做 " + k + " 個後返航", "依 " + p[0] + " 順序完成前 " + k + " 個再回家", m, v, w,
                                  [cur].concat(p[1].slice(0, k), [end]), s0, pct)
                pc.feasible = pc.end_pct >= v.reserve_pct && pc.violations.length === 0
                pc.partial = true
                if (pc.feasible) {
                    if (!best || pc.order.length > best.order.length || (pc.order.length === best.order.length && pc.energy_wh < best.energy_wh)) best = pc
                    break
                }
            }
        })
        if (best) c.push(best)
    }
    var rtl = evaluate("R1", "立即返航", "放棄剩餘目標直接回家", m, v, w, [cur, end], s0, pct)
    rtl.feasible = rtl.end_pct >= v.reserve_pct && rtl.violations.length === 0
    c.push(rtl)
    var rc = ruleChoice(c.filter(function (x) { return x.id !== "R1" })) || (rtl.feasible ? "R1" : "")
    var ev = evidenceFor(c, v, w, ["觸發事件：" + note, "目前電量 " + pct + "%", "起飛後實際耗電是預估的 " + Math.round(ratio * 100) + "%，剩餘航線已用此比例修正"])
    return { kind: "replan", event: event, state: state, candidates: c, rule_choice: rc, pick: rulePick(rc), evidence: ev,
             task_zh: "飛行中重規劃：事件發生後選一條剩餘航線。必要目標盡量完成，但落地電量必須高於保留值；返航也必須可行，全部不可行則 HOLD。",
             vehicle: v, wind: w }
}

// ---------------- 模型（H-a）：提示與驗證；HTTP 由 QML 端呼叫 ----------------

var PICK_SYSTEM = "你是無人機地面站的任務規劃助理。只能從給定候選中選一個 id，或在資訊不足、全部有風險時回 HOLD。只輸出 JSON：" +
                  "{\"decision\":\"SELECT|HOLD\",\"choice_id\":\"<候選id或空字串>\",\"reason_zh\":\"一句繁體中文理由\",\"evidence_ids\":[\"證據id\"]}"

function pickPrompt(result) {
    return { system: PICK_SYSTEM,
             user: JSON.stringify({ task: result.task_zh, candidates: result.candidates.map(brief), evidence: result.evidence }) }
}

function extractJson(text) {
    text = String(text || "").trim()
    var s = text.indexOf("{"), e = text.lastIndexOf("}")
    if (s < 0 || e <= s) return null
    try { return JSON.parse(text.slice(s, e + 1)) } catch (err) { return null }
}

// 模型回覆 → pick；不合法就退回規則選擇（附原因）
function validatePick(result, text) {
    var rc = result.rule_choice, d = extractJson(text)
    var fb = result.pick && result.pick.decision === "HOLD" ? clone(result.pick) : rulePick(rc)
    if (!d) { fb.reason_zh += "（模型回覆不是 JSON，已退回規則）"; return fb }
    var ids = result.candidates.map(function (c) { return c.id }), ev = result.evidence.map(function (e) { return e.id })
    var cited = (Array.isArray(d.evidence_ids) ? d.evidence_ids : []).filter(function (x) { return ev.indexOf(x) >= 0 })
    var dec = String(d.decision || "").toUpperCase()
    if (dec === "HOLD") return { choice_id: "", source: "llm", decision: "HOLD", reason_zh: String(d.reason_zh || ""), evidence_ids: cited }
    if (dec !== "SELECT" || ids.indexOf(d.choice_id) < 0) { fb.reason_zh += "（模型選了不存在的候選，已退回規則）"; return fb }
    var selected = result.candidates.filter(function (c) { return c.id === d.choice_id })[0]
    if (!selected.feasible) { fb.reason_zh += "（模型選了不可行候選，已退回規則）"; return fb }
    return { choice_id: d.choice_id, source: "llm", decision: "SELECT", reason_zh: String(d.reason_zh || ""), evidence_ids: cited }
}

// ---------------- 模擬飛行（demo 用；實機改吃 QGC 遙測） ----------------

function mulberry32(seed) {
    return function () {
        seed |= 0; seed = seed + 0x6D2B79F5 | 0
        var t = Math.imul(seed ^ seed >>> 15, 1 | seed)
        t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t
        return ((t ^ t >>> 14) >>> 0) / 4294967296
    }
}

function MissionRun(v, w, trueCalib, windEvents, seed, dt) {
    this.v = v; this.wind = w; this.trueCalib = trueCalib === undefined ? 1.15 : trueCalib
    this.windEvents = (windEvents || []).slice().sort(function (a, b) { return a.t_s - b.t_s })
    this.rand = mulberry32(seed || 7); this.dt = dt || 2.0
    this.t = 0; this.pct = 100; this.usedWh = 0; this.log = []; this.legs = []; this.completed = []; this.pos = null
}

MissionRun.prototype.u = function (lo, hi) { return lo + (hi - lo) * this.rand() }

MissionRun.prototype.windNow = function () {
    var w = this.wind
    for (var i = 0; i < this.windEvents.length; i++) if (this.t >= this.windEvents[i].t_s) w = wind(this.windEvents[i].speed_mps, this.windEvents[i].from_deg)
    return w
}

// onTick(rec, nextIdx) 回 true 就停（例如預測告警成立）
MissionRun.prototype.fly = function (plan, stopAtS, onTick) {
    var cap = this.v.battery_wh * this.v.usable_frac, path = plan.path, speed = plan.speed_mps, calib = plan.calib || 1
    var pred = {}
    plan.legs.forEach(function (l) { pred[l.from + ">" + l.to] = l })
    for (var i = 0; i < path.length - 1; i++) {
        var a = path[i], b = path[i + 1]
        if (!this.pos) this.pos = [a.lat, a.lon, a.alt || 0]
        var st = this.pos.slice()
        var dist = haversineM(st, [b.lat, b.lon]), brg = bearingRad(st, [b.lat, b.lon])
        var climb = (b.alt || 0) - st[2]
        var hover = b.kind === "target" ? 5.0 : 0
        var tLeg = dist / speed + Math.abs(climb) / (climb > 0 ? 3.0 : 2.0) + hover
        var used = 0, heads = [], n = Math.max(1, Math.ceil(tLeg / this.dt))
        for (var k = 1; k <= n; k++) {
            var wn = this.windNow(), gust = 1 + this.u(-0.25, 0.25), wv = windVector(wn)
            var we = wv[0] * gust, wnn = wv[1] * gust, frac = k / n, hovering = hover && k * this.dt > tLeg - hover
            var vAir = hovering ? Math.hypot(we, wnn) : Math.hypot(speed * Math.sin(brg) - we, speed * Math.cos(brg) - wnn)
            heads.push(-(we * Math.sin(brg) + wnn * Math.cos(brg)))
            var p = powerW(this.v, vAir)
            if (climb > 0) p += this.v.mass_kg * G * 3.0 / this.v.eta * Math.min(1, climb / 3.0 / Math.max(tLeg, 1))
            p *= this.trueCalib * (1 + this.u(-0.03, 0.03))
            var wh = p * this.dt / 3600
            used += wh; this.usedWh += wh; this.pct -= wh / cap * 100; this.t += this.dt
            this.pos = [st[0] + (b.lat - st[0]) * frac, st[1] + (b.lon - st[1]) * frac, st[2] + climb * frac]
            var rec = { t_s: rnd(this.t, 1), lat: this.pos[0], lon: this.pos[1], alt: rnd(this.pos[2], 1), battery_pct: rnd(this.pct, 2),
                        power_w: rnd(p, 1), wind_mps: wn.speed_mps, wind_from: wn.from_deg, leg: a.id + "→" + b.id,
                        vel_e: hovering ? 0 : speed * Math.sin(brg), vel_n: hovering ? 0 : speed * Math.cos(brg), used_wh: rnd(this.usedWh, 3) }
            this.log.push(rec)
            var stop = onTick ? !!onTick(rec, i) : false
            if ((stop || (stopAtS !== undefined && stopAtS !== null && this.t >= stopAtS)) && k < n) {
                this.legs.push(this.legRec(a, b, pred, used, heads, calib, frac))
                return this.state(plan, i, true)
            }
        }
        this.pos = [b.lat, b.lon, b.alt || 0]
        this.legs.push(this.legRec(a, b, pred, used, heads, calib, 1))
        if (b.kind === "target") this.completed.push(b.id)
        if (stopAtS !== undefined && stopAtS !== null && this.t >= stopAtS && i < path.length - 2) return this.state(plan, i + 1, false)
    }
    return this.state(plan, path.length - 1, false, true)
}

MissionRun.prototype.legRec = function (a, b, pred, used, heads, calib, partial) {
    var p = pred[a.id + ">" + b.id]
    var hw = heads.length ? heads.reduce(function (s, x) { return s + x }, 0) / heads.length : 0
    return { from: a.id, to: b.id, actual_wh: rnd(used, 2), pred_wh: p ? rnd(p.energy_wh * partial / calib, 2) : null,
             headwind_mps: rnd(hw, 2), partial: partial < 1, end_t_s: rnd(this.t, 1) }
}

MissionRun.prototype.state = function (plan, idx, partial, done) {
    var rem = plan.path.slice(idx + 1).filter(function (p) { return p.kind === "target" }).map(function (p) { return p.id })
    if (partial) { var nx = plan.path[idx + 1]; if (nx.kind === "target" && rem.indexOf(nx.id) < 0) rem.unshift(nx.id) }
    var pl = this.legs.filter(function (l) { return l.pred_wh })
    var pr = pl.reduce(function (s, l) { return s + l.pred_wh }, 0), ac = pl.reduce(function (s, l) { return s + l.actual_wh }, 0)
    return { observed_ratio: pr ? rnd(ac / pr, 3) : 1.0, t_s: rnd(this.t, 1), lat: this.pos[0], lon: this.pos[1], alt: this.pos[2],
             battery_pct: rnd(this.pct, 1), completed: this.completed.slice(), remaining: rem, done: !!done }
}

// 預測告警（最小版）：用重規劃的 L1（保留原順序）候選推估照原計畫飛完的落地電量
function predictiveAlert(v, state, rp) {
    var keep = rp.candidates.filter(function (c) { return c.id === "L1" })[0]
    if (!keep || keep.end_pct >= v.reserve_pct) return null
    return { t_s: state.t_s, level: keep.end_pct > 0 ? "warn" : "crit", title: "電量不足以飛完航線", projected_end_pct: keep.end_pct,
             text_zh: "照原計畫飛完，預估落地電量只剩 " + keep.end_pct.toFixed(1) + "%（門檻 " + v.reserve_pct + "%）；起飛後實際耗電是預估的 " +
                      Math.round((state.observed_ratio || 1) * 100) + "%" }
}

// ---------------- 智慧任務報告 ----------------

function buildFacts(run, mission, plan, replans, alerts) {
    var v = run.v, facts = []
    function add(key, text, value) { facts.push({ id: "F" + (facts.length + 1), key: key, text: text, value: value }) }
    var legs = run.legs.filter(function (l) { return l.pred_wh })
    var act = legs.reduce(function (s, l) { return s + l.actual_wh }, 0), pred = legs.reduce(function (s, l) { return s + l.pred_wh }, 0)
    var ratio = pred ? act / pred : 1, dist = 0
    for (var i = 1; i < run.log.length; i++) dist += haversineM([run.log[i - 1].lat, run.log[i - 1].lon], [run.log[i].lat, run.log[i].lon])
    var must = mission.targets.filter(function (t) { return (t.priority || 1) === 1 }).map(function (t) { return t.id })
    var all = mission.targets.map(function (t) { return t.id }), done = run.completed
    add("completion", "完成目標 " + done.length + "/" + all.length + "（必要目標 " + must.filter(function (m) { return done.indexOf(m) >= 0 }).length + "/" + must.length + "）：" + (done.join("、") || "無"),
        { done: done, all: all, must: must })
    add("duration", "飛行 " + (run.t / 60).toFixed(1) + " 分鐘、" + (dist / 1000).toFixed(2) + " 公里", { t_s: run.t, dist_m: dist })
    add("energy_ratio", "實際耗電 " + act.toFixed(1) + " Wh，物理模型預估 " + pred.toFixed(1) + " Wh，實際是預估的 " + Math.round(ratio * 100) + "%",
        { actual_wh: act, pred_wh: pred, ratio: ratio })
    add("end_battery", "落地電量 " + run.pct.toFixed(1) + "%（保留門檻 " + v.reserve_pct + "%，起飛前預估落地 " + plan.end_pct + "%）",
        { end_pct: run.pct, reserve: v.reserve_pct, planned_end: plan.end_pct })
    if (legs.length) {
        var worst = legs.reduce(function (a, l) { return l.actual_wh / Math.max(l.pred_wh, 1e-6) > a.actual_wh / Math.max(a.pred_wh, 1e-6) ? l : a })
        add("worst_leg", "超耗最多的航段 " + worst.from + "→" + worst.to + "：實際 " + worst.actual_wh + " Wh／預估 " + worst.pred_wh + " Wh，平均逆風 " + worst.headwind_mps + " m/s", worst)
    }
    var head = legs.filter(function (l) { return l.headwind_mps > 2 })
    if (head.length) {
        var hr = head.reduce(function (s, l) { return s + l.actual_wh }, 0) / Math.max(head.reduce(function (s, l) { return s + l.pred_wh }, 0), 1e-6)
        add("headwind", "逆風超過 2 m/s 的航段共 " + head.length + " 段，耗電是預估的 " + Math.round(hr * 100) + "%", { n: head.length, ratio: hr })
    }
    var seen = {}, winds = []
    run.log.forEach(function (r) { var k = r.wind_mps + "|" + r.wind_from; if (!seen[k]) { seen[k] = 1; winds.push([r.wind_mps, r.wind_from]) } })
    winds.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1] })
    if (winds.length > 1) add("wind_change", "飛行中風況改變：" + winds.map(function (x) { return x[0] + " m/s（從 " + Math.round(x[1]) + "°）" }).join("→"), winds)
    ;(replans || []).forEach(function (r) {
        add("replan", "第 " + (r.state.t_s / 60).toFixed(1) + " 分鐘因「" + (r.event.text_zh || "事件") + "」重規劃，採用 " + (r.final_choice || r.pick.choice_id || "HOLD") +
            "（" + (r.pick.source === "llm" ? "模型選擇" : "規則選擇") + "）", { choice: r.final_choice || r.pick.choice_id, source: r.pick.source })
    })
    ;(alerts || []).forEach(function (a) { add("alert", "第 " + (a.t_s / 60).toFixed(1) + " 分鐘告警：" + a.text_zh, a) })
    var nc = rnd(ratio, 3)
    add("calib", "耗電修正係數建議由 " + v.calib.toFixed(2) + " 更新為 " + nc.toFixed(2), { old: v.calib, "new": nc })
    var wl = winds.length ? wind(winds[winds.length - 1][0], winds[winds.length - 1][1]) : wind(0, 0)
    var bs = bestSpeed(v, wl, wl.from_deg)
    add("best_speed", "以本次最大風況（" + wl.speed_mps + " m/s）估算，逆風最省電地速約 " + bs.speed_mps + " m/s（" + bs.wh_per_km + " Wh/km），本次巡航 " + plan.speed_mps + " m/s",
        { speed_mps: bs.speed_mps, wh_per_km: bs.wh_per_km, cruise: plan.speed_mps })
    return facts
}

function ruleSuggestions(facts) {
    var f = {}, out = []
    facts.forEach(function (x) { if (x.key !== "replan" && x.key !== "alert") f[x.key] = x })
    function sug(text, keys, level) {
        out.push({ text_zh: text, evidence_ids: keys.filter(function (k) { return f[k] }).map(function (k) { return f[k].id }), level: level || "info" })
    }
    var r = f.energy_ratio.value.ratio
    if (r > 1.08) sug("實際耗電比預估多 " + Math.round((r - 1) * 100) + "%，下次規劃請套用新的修正係數 " + f.calib.value["new"].toFixed(2) + "（系統可自動帶入），並檢查電池健康度與循環次數。", ["energy_ratio", "calib"], "warn")
    else if (r < 0.92) sug("實際耗電比預估少 " + Math.round((1 - r) * 100) + "%，預估偏保守，可考慮套用修正係數 " + f.calib.value["new"].toFixed(2) + " 以排入更多目標。", ["energy_ratio", "calib"])
    var eb = f.end_battery.value
    if (eb.end_pct < eb.reserve) sug("落地電量 " + eb.end_pct.toFixed(1) + "% 低於保留門檻 " + eb.reserve + "%，同樣的任務下次應分兩趟或減少選配目標。", ["end_battery"], "crit")
    else if (eb.end_pct < eb.reserve + 8) sug("落地電量只比保留門檻多 " + (eb.end_pct - eb.reserve).toFixed(1) + "%，餘裕偏小，建議出發前預留更多電量或提高保留門檻。", ["end_battery"], "warn")
    if (f.headwind && f.headwind.value.ratio > 1.1) sug("逆風航段是超耗主因，建議把逆風段排在電量充足的前段，回程順風；規劃時選用「最省電順序」候選。", ["headwind", "worst_leg"], "warn")
    if (f.wind_change && Math.abs(f.best_speed.value.speed_mps - f.best_speed.value.cruise) >= 1)
        sug("風大時把逆風段速度調到約 " + f.best_speed.value.speed_mps + " m/s 可降低單位距離耗電。", ["best_speed", "wind_change"])
    var comp = f.completion.value
    var missing = comp.all.filter(function (t) { return comp.done.indexOf(t) < 0 })
    var missMust = comp.must.filter(function (t) { return comp.done.indexOf(t) < 0 })
    var doneOpt = comp.done.filter(function (t) { return comp.must.indexOf(t) < 0 })
    if (missMust.length && doneOpt.length) sug("本次先做了選配目標（" + doneOpt.join("、") + "），卻漏掉必要目標（" + missMust.join("、") + "）；下次請選「必要目標優先」順序。", ["completion"], "warn")
    if (missing.length) sug("未完成目標：" + missing.join("、") + "，建議排入下一趟任務（可從本報告一鍵帶入規劃）。", ["completion"])
    if (!out.length) sug("本次任務耗電與預估相符、電量餘裕充足，維持目前設定即可。", ["energy_ratio", "end_battery"])
    return out
}

function makeReport(run, mission, plan, replans, alerts) {
    var facts = buildFacts(run, mission, plan, replans, alerts)
    var by = function (k) { return facts.filter(function (x) { return x.key === k })[0] }
    return { facts: facts, suggestions: ruleSuggestions(facts), source: "rule",
             summary_zh: by("completion").text + "。" + by("energy_ratio").text + "。" + by("end_battery").text + "。",
             next_calib: by("calib").value["new"] }
}

var REPORT_SYSTEM = "你是無人機任務報告助理。只能根據給定事實（facts）寫，不可新增數字。輸出 JSON：{\"summary_zh\":\"3 句內繁體中文摘要\"," +
                    "\"suggestions\":[{\"text_zh\":\"建議\",\"evidence_ids\":[\"F1\"]}]}。建議依重要性排序，最多 5 條，每條都要引用 facts 的 id。可改寫給定的規則建議，但不可捏造。"

function reportPrompt(rep) {
    return { system: REPORT_SYSTEM,
             user: JSON.stringify({ facts: rep.facts.map(function (x) { return { id: x.id, text: x.text } }), rule_suggestions: rep.suggestions }) }
}

// 模型改寫的報告：沒引用事實的建議丟掉；全部被丟就保留規則版
function applyReportLlm(rep, text) {
    var d = extractJson(text)
    if (!d || typeof d.summary_zh !== "string" || !Array.isArray(d.suggestions)) return rep
    var ids = rep.facts.map(function (x) { return x.id }), kept = []
    d.suggestions.slice(0, 5).forEach(function (s) {
        if (!s || typeof s.text_zh !== "string") return
        var ev = (s.evidence_ids || []).filter(function (e) { return ids.indexOf(e) >= 0 })
        if (ev.length) kept.push({ text_zh: s.text_zh, evidence_ids: ev, level: "info" })
    })
    if (!kept.length) return rep
    var out = clone(rep)
    out.rule_suggestions = rep.suggestions; out.suggestions = kept; out.summary_zh = d.summary_zh; out.source = "llm"
    return out
}

// node 測試用
if (typeof module !== "undefined") module.exports = {
    haversineM: haversineM, vehicle: vehicle, wind: wind, routeEstimate: routeEstimate, bestSpeed: bestSpeed,
    planMission: planMission, replan: replan, MissionRun: MissionRun, makeReport: makeReport, predictiveAlert: predictiveAlert,
    pickPrompt: pickPrompt, validatePick: validatePick, reportPrompt: reportPrompt, applyReportLlm: applyReportLlm
}
