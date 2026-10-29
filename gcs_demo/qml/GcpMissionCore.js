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

// T5a: pure profile primitives. JSON/file loading belongs to the QML caller.
function profileNumber(x, name, low, high, positive) {
    if (typeof x !== "number" || !isFinite(x)) throw new Error(name + ": finite number required")
    if (low === undefined) low = 0
    if (x < low || (positive && x <= low) || (high !== undefined && x > high)) throw new Error(name + ": out of range")
    return x
}
function profileObject(x, name) {
    if (!x || typeof x !== "object" || Array.isArray(x)) throw new Error(name + ": object required")
    return x
}
function profileMerge(defaults, value, name) {
    profileObject(value, name)
    var result = clone(defaults)
    for (var k in value) if (Object.prototype.hasOwnProperty.call(value, k)) result[k] = value[k]
    return result
}
function profileMc(p, prefix) {
    p = profileMerge({p_hover_w:190, cda_m2:0.12, eta:0.7}, p, prefix)
    profileNumber(p.p_hover_w, prefix + ".p_hover_w", 0, undefined, true)
    profileNumber(p.cda_m2, prefix + ".cda_m2")
    profileNumber(p.eta, prefix + ".eta", 0, 1, true)
    return p
}
function profileFw(p, prefix) {
    profileObject(p, prefix)
    var keys = ["wing_area_m2", "cd0", "k_induced", "eta_prop", "p_avionics_w", "v_stall_mps", "min_turn_radius_m"]
    keys.forEach(function(k) {
        profileNumber(p[k], prefix + "." + k, 0, k === "eta_prop" ? 1 : undefined, k !== "p_avionics_w")
    })
    return p
}
function profileLoadFactor(bankDeg) {
    profileNumber(bankDeg, "bank_deg", -90, 90)
    if (Math.abs(bankDeg) >= 90) throw new Error("bank_deg: absolute bank must be less than 90 degrees")
    return 1 / Math.cos(rad(bankDeg))
}
function profileSpeedRange(p, bankDeg) {
    if (bankDeg === undefined) bankDeg = 0
    var lo = p.limits.min_airspeed_mps
    if (p.type !== "multirotor") {
        var f = p.type === "fixed_wing" ? p.power : p.power.fw
        lo = Math.max(lo, 1.2 * f.v_stall_mps * Math.sqrt(profileLoadFactor(bankDeg)))
    }
    return [lo, p.limits.max_airspeed_mps]
}
function validateAirframeProfile(value) {
    profileObject(value, "profile")
    // Copy without JSON round-tripping until validation: JSON turns NaN/Infinity
    // into null and would lose unknown provenance fields. Only JSON data accepted.
    function copy(x) {
        if (x === null || typeof x === "string" || typeof x === "boolean") return x
        if (typeof x === "number") {
            if (!isFinite(x)) throw new Error("profile: nonfinite JSON number")
            return x
        }
        if (Array.isArray(x)) return x.map(copy)
        profileObject(x, "profile value")
        var o = {}
        Object.keys(x).forEach(function(k) {
            if (k === "__proto__" || k === "constructor" || k === "prototype") throw new Error("profile: reserved key")
            o[k] = copy(x[k])
        })
        return o
    }
    var p = copy(value)
    if (p.id === undefined) p.id = "UAV-01"
    if (typeof p.id !== "string" || !p.id.trim()) throw new Error("id: nonempty string required")
    if (p.type === undefined) p.type = "multirotor"
    if (["multirotor", "fixed_wing", "vtol_hybrid"].indexOf(p.type) < 0) throw new Error("type: unsupported airframe")
    if (p.schema === undefined) p.schema = 0
    if (p.schema !== 0) throw new Error("schema: only version 0 is supported")
    if (p.mass_kg === undefined) p.mass_kg = 2
    if (p.calib === undefined) p.calib = 1
    if (p.source === undefined) p.source = "assumed"
    if (typeof p.source !== "string" || !p.source.trim()) throw new Error("source: nonempty string required")
    profileNumber(p.mass_kg, "mass_kg", 0, undefined, true)
    profileNumber(p.calib, "calib", 0, undefined, true)
    p.battery = profileMerge({wh:90, usable_frac:0.9, cell_count:4, cell_empty_v:3.55, cell_r_ohm:0.004}, p.battery === undefined ? {} : p.battery, "battery")
    p.limits = profileMerge({reserve_pct:20, wind_limit_mps:12, min_airspeed_mps:0, max_airspeed_mps:15, cruise_mps:8}, p.limits === undefined ? {} : p.limits, "limits")
    p.uncertainty = profileMerge({power_pct:10, capacity_pct:5, wind_mps:2}, p.uncertainty === undefined ? {} : p.uncertainty, "uncertainty")
    var b = p.battery, l = p.limits, u = p.uncertainty
    profileNumber(b.wh, "battery.wh", 0, undefined, true)
    profileNumber(b.usable_frac, "battery.usable_frac", 0, 1, true)
    profileNumber(b.cell_count, "battery.cell_count", 0, undefined, true)
    if (Math.floor(b.cell_count) !== b.cell_count) throw new Error("battery.cell_count: integer required")
    profileNumber(b.cell_empty_v, "battery.cell_empty_v", 0, undefined, true)
    profileNumber(b.cell_r_ohm, "battery.cell_r_ohm")
    Object.keys({reserve_pct:0, wind_limit_mps:0, min_airspeed_mps:0, max_airspeed_mps:0, cruise_mps:0}).forEach(function(k) {
        profileNumber(l[k], "limits." + k, 0, k === "reserve_pct" ? 100 : undefined, k === "max_airspeed_mps" || k === "cruise_mps")
    })
    Object.keys({power_pct:0, capacity_pct:0, wind_mps:0}).forEach(function(k) {
        profileNumber(u[k], "uncertainty." + k, 0, k === "wind_mps" ? undefined : 100)
    })
    if (u.capacity_pct >= 100) throw new Error("uncertainty.capacity_pct: must leave positive capacity")
    var pw = p.power === undefined ? {} : p.power
    if (p.type === "multirotor") p.power = profileMc(pw, "power")
    else if (p.type === "fixed_wing") p.power = profileFw(pw, "power")
    else {
        profileObject(pw, "power")
        pw.mc = profileMc(pw.mc === undefined ? {} : pw.mc, "power.mc")
        pw.fw = profileFw(pw.fw === undefined ? {} : pw.fw, "power.fw")
        p.power = pw
        p.transition = profileObject(p.transition === undefined ? {} : p.transition, "transition")
        ;["to_fw_wh", "to_fw_s", "to_fw_dist_m", "to_mc_wh", "to_mc_s"].forEach(function(k) {
            profileNumber(p.transition[k], "transition." + k)
        })
    }
    var prop = p.prop_model
    if (prop !== undefined && prop !== null) {
        if (typeof prop === "string") {
            if (!prop.trim()) throw new Error("prop_model: nonempty identifier required")
        } else {
            profileObject(prop, "prop_model")
            if (typeof prop.id !== "string" || !prop.id.trim()) throw new Error("prop_model.id: nonempty string required")
            if ((prop.rpm !== undefined) !== (prop.diameter_m !== undefined)) throw new Error("prop_model: rpm and diameter_m must appear together")
            ;["rpm", "diameter_m"].forEach(function(k) {
                if (prop[k] !== undefined) profileNumber(prop[k], "prop_model." + k, 0, undefined, true)
            })
        }
    }
    if (p.eta_table !== undefined) {
        if (!prop || !Array.isArray(p.eta_table) || p.eta_table.length < 2) throw new Error("eta_table: prop_model and at least two [J, eta] rows required")
        var previous = -1
        p.eta_table.forEach(function(row) {
            if (!Array.isArray(row) || row.length !== 2) throw new Error("eta_table: rows must be [J, eta]")
            profileNumber(row[0], "eta_table.J")
            profileNumber(row[1], "eta_table.eta", 0, 1, true)
            if (row[0] <= previous) throw new Error("eta_table: J must be strictly increasing")
            previous = row[0]
        })
    }
    var range = profileSpeedRange(p)
    if (range[0] > range[1] || l.cruise_mps < range[0] || l.cruise_mps > range[1]) throw new Error("limits: cruise and max must satisfy the effective airspeed range")
    return p
}
function loadAirframe(jsonOrObject) {
    // QML supplies file contents; this core never reads disk or downloads files.
    var p = validateAirframeProfile(typeof jsonOrObject === "string" ? JSON.parse(jsonOrObject.replace(/^\uFEFF/, "")) : jsonOrObject)
    var mc = p.type === "multirotor" ? p.power : p.type === "vtol_hybrid" ? p.power.mc : {p_hover_w:0, cda_m2:0, eta:1}
    return vehicle({vehicle_id:p.id, mass_kg:p.mass_kg, battery_wh:p.battery.wh, usable_frac:p.battery.usable_frac,
                    p_hover_w:mc.p_hover_w, cda_m2:mc.cda_m2, eta:mc.eta, cruise_mps:p.limits.cruise_mps,
                    max_mps:p.limits.max_airspeed_mps, reserve_pct:p.limits.reserve_pct, calib:p.calib,
                    airframe_profile:p})
}
function airframeType(v) { return v.airframe_profile ? v.airframe_profile.type : "multirotor" }
function speedRange(v, bankDeg) {
    return v.airframe_profile ? profileSpeedRange(v.airframe_profile, bankDeg) : [0, v.max_mps]
}
function propEfficiency(p, vAir, fallback, advanceRatio) {
    var table = p.eta_table
    if (!table) return fallback
    var j = advanceRatio, prop = p.prop_model
    if ((j === undefined || j === null) && prop && typeof prop === "object" && prop.rpm !== undefined) j = vAir / (prop.rpm / 60 * prop.diameter_m)
    if (j === undefined || j === null) return fallback
    profileNumber(j, "advance_ratio")
    if (j <= table[0][0]) return table[0][1]
    for (var i = 1; i < table.length; i++) {
        if (j <= table[i][0]) {
            var a = table[i - 1], b = table[i]
            return a[1] + (b[1] - a[1]) * (j - a[0]) / (b[0] - a[0])
        }
    }
    return table[table.length - 1][1]
}
function profilePowerW(p, vAir, mode, bankDeg, climbMps, advanceRatio, massKg) {
    if (bankDeg === undefined) bankDeg = 0
    if (climbMps === undefined) climbMps = 0
    profileNumber(vAir, "v_air")
    profileNumber(climbMps, "climb_mps", -1e100)
    profileLoadFactor(bankDeg)
    var pw
    if (p.type === "vtol_hybrid") {
        if (mode !== "mc" && mode !== "fw") throw new Error("vtol_hybrid power requires explicit mode='mc' or 'fw'")
        pw = p.power[mode]
    } else {
        var active = p.type === "multirotor" ? "mc" : "fw"
        if (mode !== undefined && mode !== null && mode !== active) throw new Error("mode is incompatible with airframe type")
        mode = active; pw = p.power
    }
    var mass = massKg === undefined ? p.mass_kg : massKg
    profileNumber(mass, "mass_kg", 0, undefined, true)
    var climb = mass * G * Math.max(0, climbMps)
    if (mode === "mc") {
        if (bankDeg !== 0) throw new Error("multirotor bank compensation is not modeled")
        return pw.p_hover_w + 0.5 * RHO * pw.cda_m2 * Math.pow(vAir, 3) / pw.eta + climb / pw.eta
    }
    var n = profileLoadFactor(bankDeg), range = profileSpeedRange(p, bankDeg)
    if (vAir < range[0] || vAir > range[1]) throw new Error("v_air: outside fixed-wing airspeed/stall envelope")
    var eta = propEfficiency(p, vAir, pw.eta_prop, advanceRatio)
    var drag = 0.5 * RHO * Math.pow(vAir, 3) * pw.wing_area_m2 * pw.cd0 +
            2 * pw.k_induced * Math.pow(mass * G, 2) * n * n / (RHO * vAir * pw.wing_area_m2)
    return (drag + climb) / eta + pw.p_avionics_w
}
function turnGeometry(v, vAir, bankDeg, radiusM) {
    if (airframeType(v) === "multirotor") throw new Error("turn geometry is defined only for fixed-wing flight")
    var p = v.airframe_profile, pw = p.type === "fixed_wing" ? p.power : p.power.fw
    profileNumber(vAir, "v_air", 0, undefined, true)
    var hasBank = bankDeg !== undefined && bankDeg !== null, hasRadius = radiusM !== undefined && radiusM !== null
    if (hasBank && hasRadius) throw new Error("specify bank_deg or radius_m, not both")
    if (!hasBank) {
        if (!hasRadius) radiusM = pw.min_turn_radius_m
        profileNumber(radiusM, "radius_m", 0, undefined, true)
        bankDeg = Math.atan(vAir * vAir / (G * radiusM)) * 180 / Math.PI
    }
    var n = profileLoadFactor(bankDeg)
    var radius = bankDeg === 0 ? null : vAir * vAir / (G * Math.abs(Math.tan(rad(bankDeg))))
    if (radius !== null && radius < pw.min_turn_radius_m - 1e-9) throw new Error("turn radius below configured minimum")
    var range = profileSpeedRange(p, bankDeg)
    if (vAir < range[0] || vAir > range[1]) throw new Error("turn exceeds bank-adjusted stall/airspeed envelope")
    return {bank_deg:bankDeg, load_factor:n, radius_m:radius, min_airspeed_mps:range[0]}
}
function requireLegacyRoute(v) {
    if (airframeType(v) !== "multirotor") throw new Error("T5b route/transition/bounds integration pending; fixed-wing/hybrid routes unavailable")
}


// NaN 不能用 || 0 靜默變成無風；僅缺省值使用 0。
function wind(speed, fromDeg) {
    return { speed_mps: speed === undefined ? 0 : speed, from_deg: fromDeg === undefined ? 0 : fromDeg }
}

function windVector(w) {
    var to = rad(w.from_deg + 180.0)
    return [w.speed_mps * Math.sin(to), w.speed_mps * Math.cos(to)]   // (east, north)
}

function powerW(v, vAir, mode, bankDeg, climbMps, advanceRatio) {
    if (!v.airframe_profile && (mode === undefined || mode === null) && (bankDeg === undefined || bankDeg === 0) &&
            (climbMps === undefined || climbMps === 0) && (advanceRatio === undefined || advanceRatio === null))
        return v.p_hover_w + 0.5 * RHO * v.cda_m2 * Math.pow(vAir, 3) / v.eta
    var p = v.airframe_profile || {type:"multirotor", power:{}}
    if (airframeType(v) === "multirotor") {
        p = profileMerge({}, p, "profile")
        p.power = profileMerge(p.power, {p_hover_w:v.p_hover_w, cda_m2:v.cda_m2, eta:v.eta}, "power")
    }
    return profilePowerW(p, vAir, mode, bankDeg, climbMps, advanceRatio, v.mass_kg)
}

function legEstimate(v, a, b, altA, altB, groundMps, w, mode) {
    if (airframeType(v) !== "multirotor") return airframeLegEstimate(v,a,b,altA,altB,groundMps,w,mode)
    flightMode(v,mode)
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

function routeEstimate(v, points, groundMps, w, startPct, hoverS, mode) {
    if (airframeType(v) !== "multirotor") return airframeRouteEstimate(v,points,groundMps,w,startPct,hoverS,mode)
    flightMode(v,mode)
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

function bestSpeed(v, w, headingDeg, lo, hi, mode) {
    if (airframeType(v) !== "multirotor") return airframeBestSpeed(v,w,headingDeg,lo,hi,mode)
    flightMode(v,mode)
    if (lo === undefined) lo = 4
    if (hi === undefined || hi === null) hi = v.max_mps
    var a = [0, 0], b = [0.001 * Math.cos(rad(headingDeg || 0)), 0.001 * Math.sin(rad(headingDeg || 0))]
    var best = null
    for (var s = lo; s <= hi + 1e-9; s += 0.5) {
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
        constraint_deltas: constraintDeltas(mission, v, path, est, missing),
        path: path.map(function (p) { return { id: p.id, lat: p.lat, lon: p.lon, alt: p.alt || 0, kind: p.kind, priority: p.priority } }),
        legs: est.legs.map(function (l) {
            return { from: l.from, to: l.to, dist_m: rnd(l.dist_m, 2), time_s: rnd(l.time_s, 2), energy_wh: rnd(l.energy_wh, 2),
                     headwind_mps: rnd(l.headwind_mps, 2), pct_after: rnd(l.pct_after, 2) }
        })
    }
}

function ruleChoice(cands) {
    // 分兩趟（S1）需要換電、目前無法一次套用：只列為建議，不當規則選擇
    var feas = cands.filter(function (c) { return c.feasible && !c.requires_battery_swap })
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
    cands.forEach(function (c, i) {
        var entry = ev[i + 2]
        if (!c.feasible) {
            entry.value = {candidate_id: c.id, violations: c.constraint_deltas}
            entry.text += "；約束差額：" + JSON.stringify(c.constraint_deltas)
        }
        if (c.sorties) {
            entry.value = {candidate_id: c.id, sorties: c.sorties.map(function (s) { return {id:s.id, end_pct:s.end_pct, margin_pct:s.margin_pct} })}
            entry.text += "（兩趟各自返航／滿電出發；落地電量表示兩趟較低值，非累積值）"
        }
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
    if (!c.some(function (x) { return x.feasible && x.order.length === tg.length })) {
        var split = splitSorties(mission, v, w, [tg, sd, se], [v0, bs])
        if (split) c.push(split)
    }
    var rc = ruleChoice(c)
    return { kind: "plan", mission_version: missionVersion(mission, v, w, null), candidates: c, rule_choice: rc, pick: rulePick(rc), evidence: evidenceFor(c, v, w),
             task_zh: "出發前任務規劃：選一條航線。必要目標都要做到，落地電量要高於保留值。",
             vehicle: v, wind: w }
}

function replan(mission, v0in, w, state, event) {
    var invalid = inputError(mission, v0in, w, true)
    if (invalid) return boundaryHold("replan", invalid)
    invalid = stateError(mission, state)
    if (invalid || !event || typeof event !== "object") return boundaryHold("replan", invalid || "事件格式無效")
    if (event.type === "add_target" && !event.target) return boundaryHold("replan", "新增目標格式無效")
    var note = event.text_zh || "", ratio = state.observed_ratio !== undefined ? state.observed_ratio : v0in.calib
    var context = replanContext(mission, v0in, w, state, event)
    var m = context.mission, v = context.vehicle
    w = context.wind; state = context.state
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
    return { kind: "replan", mission_version: missionVersion(m, v, w, state), event: event, state: state, candidates: c, rule_choice: rc, pick: rulePick(rc), evidence: ev,
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
    if (selected.requires_battery_swap) { fb.reason_zh += "（模型選了需換電的分趟候選，已退回規則）"; return fb }
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

// T3 report helpers. CSV/Plan file I/O stays in the Python offline adapter;
// a serialized RunLike (including data_quality) uses the same report gates here.
function sha256Text(text) {
    var encoded=encodeURIComponent(text),bytes=[],i,j
    for(i=0;i<encoded.length;i++) {
        if(encoded[i]==="%") {bytes.push(parseInt(encoded.slice(i+1,i+3),16));i+=2}
        else bytes.push(encoded.charCodeAt(i))
    }
    var bits=bytes.length*8
    bytes.push(128);while(bytes.length%64!==56)bytes.push(0)
    for(i=7;i>=0;i--)bytes.push(Math.floor(bits/Math.pow(256,i))%256)
    var h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]
    var k=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]
    function rotr(x,n){return (x>>>n)|(x<<(32-n))}
    for(i=0;i<bytes.length;i+=64) {
        var w=[]
        for(j=0;j<16;j++)w[j]=(bytes[i+4*j]<<24)|(bytes[i+4*j+1]<<16)|(bytes[i+4*j+2]<<8)|bytes[i+4*j+3]
        for(j=16;j<64;j++) {
            var x=w[j-15],y=w[j-2],s0=rotr(x,7)^rotr(x,18)^(x>>>3),s1=rotr(y,17)^rotr(y,19)^(y>>>10)
            w[j]=(w[j-16]+s0+w[j-7]+s1)|0
        }
        var a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7]
        for(j=0;j<64;j++) {
            var t1=(hh+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^((~e)&g))+k[j]+w[j])|0
            var t2=((rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c)))|0
            hh=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0
        }
        var v=[a,b,c,d,e,f,g,hh];for(j=0;j<8;j++)h[j]=(h[j]+v[j])|0
    }
    return h.map(function(n){return ("00000000"+(n>>>0).toString(16)).slice(-8)}).join("")
}

function qualityFor(run) {
    if (run.data_quality && Object.keys(run.data_quality).length) return clone(run.data_quality)
    var gaps = [], log = run.log || []
    for (var i = 1; i < log.length; i++) if (log[i].t_s > log[i-1].t_s) gaps.push(log[i].t_s-log[i-1].t_s)
    gaps.sort(function (a,b) { return a-b })
    var missing = !log.length || log.some(function (r) { return r.wind_mps == null || r.wind_from == null })
    var estimated = !!run.energy_estimated, mid = Math.floor(gaps.length/2)
    return { source: "simulation_or_supplied_run", missing_wind: missing, missing_current: estimated,
        soc_estimated: estimated, calibration_eligible: !estimated && !missing, sample_count: log.length, trimmed_samples: 0,
        sample_interval_s: gaps.length ? {min:gaps[0],median:gaps.length%2 ? gaps[mid] : (gaps[mid-1]+gaps[mid])/2,max:gaps[gaps.length-1]} : null }
}

function numberTokens(text) {
    var s = String(text)
    if (s.normalize) s = s.normalize("NFKC")
    return s.match(/[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/g) || []
}
function unsupportedNumbers(texts, facts) {
    var values = [], bad = []
    function visit(x) {
        if (typeof x === "number" && isFinite(x)) values.push(x)
        else if (typeof x === "string") numberTokens(x).forEach(function (s) { if (isFinite(Number(s))) values.push(Number(s)) })
        else if (Array.isArray(x)) x.forEach(visit)
        else if (x && typeof x === "object") Object.keys(x).forEach(function (k) { visit(x[k]) })
    }
    facts.forEach(function (f) { visit(f.text); visit(f.value) })
    texts.forEach(function (text) { numberTokens(text).forEach(function (token) {
        var parts = token.toLowerCase().split("e"), decimals = parts[0].split(".")[1] || ""
        var tolerance = 0.5 * Math.pow(10, Number(parts[1] || 0)-decimals.length), value = Number(token)
        if (!isFinite(tolerance)) tolerance = 0
        if ((!isFinite(value) || !values.some(function (n) { return Math.abs(n-value) <= tolerance+1e-10 })) && bad.indexOf(token)<0) bad.push(token)
    }) })
    return bad
}

function reportEvents(run, mission, replans, alerts) {
    var events = [], airborne = false, seen = {}, ids = mission.targets.map(function (t) { return t.id })
    run.log.forEach(function (r,i) {
        if (r.alt == null) return
        if (!airborne && r.alt>1) { events.push({kind:i===0 ? "start_in_air" : "takeoff",t_s:r.t_s,basis:"altitude_threshold_inference"}); airborne=true }
        else if (airborne && Math.abs(r.alt)<=1) {
            var speed = r.ground_speed_mps == null ? Math.hypot(r.vel_e || 0,r.vel_n || 0) : r.ground_speed_mps
            if (speed<=0.5 && !r.armed) { events.push({kind:"landing",t_s:r.t_s,basis:"stationary_ground_inference"}); airborne=false }
        }
    })
    run.legs.forEach(function (l) { if (!l.partial && ids.indexOf(l.to)>=0 && !seen[l.to] && l.end_t_s!=null) {
        seen[l.to]=true; events.push({kind:"waypoint",target_id:l.to,t_s:l.end_t_s,basis:"sample_arrival_or_supplied_leg"})
    } })
    ;(replans || []).forEach(function (r) { if (r.state && r.state.t_s!=null) events.push({kind:"replan",t_s:r.state.t_s,choice_id:r.final_choice || r.pick.choice_id || ""}) })
    ;(alerts || []).forEach(function (a) { if (a.t_s!=null) events.push({kind:"alert",t_s:a.t_s,text_zh:a.text_zh || ""}) })
    return events.sort(function (a,b) { return a.t_s-b.t_s })
}

function reserveAlertLeads(run, alerts) {
    var result=[]
    ;(alerts || []).forEach(function (a,i) {
        if (a.t_s==null) return
        var breach=a.predicted_reserve_breach_t_s, basis="caller_reserve_prediction"
        if (breach==null) {
            var samples=run.log.filter(function (r) { return r.t_s<=a.t_s })
            if (samples.length<2) return
            var p=samples[samples.length-2],q=samples[samples.length-1],dt=q.t_s-p.t_s
            if (dt<=0 || a.t_s-q.t_s>dt) return
            var slope=(q.battery_pct-p.battery_pct)/dt
            if (slope>=0) return
            breach=q.t_s+(run.v.reserve_pct-q.battery_pct)/slope
            basis="linear_soc_at_alert_not_future_observation"
        }
        if (typeof breach==="number" && isFinite(breach)) result.push({alert_index:i,alert_t_s:a.t_s,predicted_reserve_breach_t_s:breach,lead_s:Math.max(0,breach-a.t_s),basis:basis})
    })
    return result
}

function buildFacts(run, mission, plan, replans, alerts) {
    var v = run.v, facts = []
    var quality = qualityFor(run), windKnown = !quality.missing_wind, eligible = quality.calibration_eligible
    var estimated = !!run.energy_estimated
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
    add("energy_ratio", (estimated ? "以電量差估算耗電 " : "實際耗電 ") + act.toFixed(1) + " Wh，物理模型預估 " + pred.toFixed(1) + " Wh，能耗是預估的 " + Math.round(ratio * 100) + "%",
        { actual_wh: act, pred_wh: pred, ratio: ratio, calibration_eligible: eligible })
    add("end_battery", "落地電量 " + run.pct.toFixed(1) + "%（保留門檻 " + v.reserve_pct + "%，起飛前預估落地 " + plan.end_pct + "%）",
        { end_pct: run.pct, reserve: v.reserve_pct, planned_end: plan.end_pct })
    if (legs.length) {
        var worst = legs.reduce(function (a, l) { return l.actual_wh / Math.max(l.pred_wh, 1e-6) > a.actual_wh / Math.max(a.pred_wh, 1e-6) ? l : a })
        var worstValue=clone(worst); if (!windKnown) delete worstValue.headwind_mps
        add("worst_leg", "超耗最多的航段 " + worst.from + "→" + worst.to + "：實際 " + worst.actual_wh.toFixed(2) + " Wh／預估 " + worst.pred_wh.toFixed(2) + " Wh" + (windKnown ? "，平均逆風 " + worst.headwind_mps + " m/s" : "；風況未知"), worstValue)
    }
    var head = legs.filter(function (l) { return windKnown && l.headwind_mps != null && l.headwind_mps > 2 })
    if (head.length) {
        var hr = head.reduce(function (s, l) { return s + l.actual_wh }, 0) / Math.max(head.reduce(function (s, l) { return s + l.pred_wh }, 0), 1e-6)
        add("headwind", "逆風超過 2 m/s 的航段共 " + head.length + " 段，耗電是預估的 " + Math.round(hr * 100) + "%", { n: head.length, ratio: hr })
    }
    var seen = {}, winds = []
    if (windKnown) run.log.forEach(function (r) { var k = r.wind_mps + "|" + r.wind_from; if (!seen[k]) { seen[k] = 1; winds.push([r.wind_mps, r.wind_from]) } })
    winds.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1] })
    if (winds.length > 1) add("wind_change", "飛行中風況改變：" + winds.map(function (x) { return x[0] + " m/s（從 " + Math.round(x[1]) + "°）" }).join("→"), winds)
    ;(replans || []).forEach(function (r) {
        add("replan", "第 " + (r.state.t_s / 60).toFixed(1) + " 分鐘因「" + (r.event.text_zh || "事件") + "」重規劃，採用 " + (r.final_choice || r.pick.choice_id || "HOLD") +
            "（" + (r.pick.source === "llm" ? "模型選擇" : "規則選擇") + "）", { choice: r.final_choice || r.pick.choice_id, source: r.pick.source })
    })
    ;(alerts || []).forEach(function (a) { add("alert", "第 " + (a.t_s / 60).toFixed(1) + " 分鐘告警：" + a.text_zh, a) })
    var nc = eligible ? rnd(ratio, 3) : v.calib
    add("calib", eligible ? "耗電修正係數建議由 " + v.calib.toFixed(2) + " 更新為 " + nc.toFixed(2) : "缺電流或風況資料，能耗不足以校正；維持耗電修正係數", { old: v.calib, "new": nc, eligible: eligible })
    if (windKnown) {
        var wl = winds.length ? wind(winds[winds.length - 1][0], winds[winds.length - 1][1]) : wind(0, 0)
        var bs = bestSpeed(v, wl, wl.from_deg)
        add("best_speed", "以本次最大風況（" + wl.speed_mps + " m/s）估算，逆風最省電地速約 " + bs.speed_mps + " m/s（" + bs.wh_per_km + " Wh/km），本次巡航 " + plan.speed_mps + " m/s",
            { speed_mps: bs.speed_mps, wh_per_km: bs.wh_per_km, cruise: plan.speed_mps })
    }
    if (run.provenance) add("telemetry_source", "CSV 遙測來源：" + run.provenance.energy_source + "；已用 PX4 SITL 匯出核對欄位，尚未用實機核對", run.provenance)
    var missing=[]; if (quality.missing_wind) missing.push("風速／風向"); if (quality.missing_current) missing.push("電流")
    add("data_quality", "資料品質：" + (missing.length ? "缺少"+missing.join("、") : "所需風況與能耗資料可用") + (estimated ? "；耗電採 SOC 差值估算" : "") + "；取樣間隔（秒）"+JSON.stringify(quality.sample_interval_s), quality)
    var timeline=reportEvents(run,mission,replans,alerts)
    add("timeline", timelineText(timeline),timeline)
    var flightEvents=timeline.filter(function (e) {return ["takeoff","start_in_air","landing"].indexOf(e.kind)>=0})
    var landed=!!flightEvents.length && flightEvents[flightEvents.length-1].kind==="landing"
    add("energy_margin", (landed ? "落地" : "紀錄終點")+"能量餘裕 M = "+(run.pct-v.reserve_pct).toFixed(1)+"%", {margin_pct:run.pct-v.reserve_pct,landing_inferred:landed,basis:"terminal_soc_minus_reserve"})
    if (alerts && alerts.length) add("alert_lead_time", "告警至預估跌破保留門檻的提前秒數；無可靠估計時不填數字",reserveAlertLeads(run,alerts))
    return facts
}

function ruleSuggestions(facts) {
    var f = {}, out = []
    facts.forEach(function (x) { if (x.key !== "replan" && x.key !== "alert") f[x.key] = x })
    function sug(text, keys, level) {
        out.push({ text_zh: text, evidence_ids: keys.filter(function (k) { return f[k] }).map(function (k) { return f[k].id }), level: level || "info" })
    }
    var r = f.energy_ratio.value.calibration_eligible ? f.energy_ratio.value.ratio : 1
    if (r > 1.08) sug("實際耗電比預估多 " + Math.round((r - 1) * 100) + "%，下次規劃請套用新的修正係數 " + f.calib.value["new"].toFixed(2) + "（系統可自動帶入），並檢查電池健康度與循環次數。", ["energy_ratio", "calib"], "warn")
    else if (r < 0.92) sug("實際耗電比預估少 " + Math.round((1 - r) * 100) + "%，預估偏保守，可考慮套用修正係數 " + f.calib.value["new"].toFixed(2) + " 以排入更多目標。", ["energy_ratio", "calib"])
    var eb = f.end_battery.value
    if (eb.end_pct < eb.reserve) sug("落地電量 " + eb.end_pct.toFixed(1) + "% 低於保留門檻 " + eb.reserve + "%，同樣的任務下次應分兩趟或減少選配目標。", ["end_battery"], "crit")
    else if (eb.end_pct < eb.reserve + 8) sug("落地電量只比保留門檻多 " + (eb.end_pct - eb.reserve).toFixed(1) + "%，餘裕偏小，建議出發前預留更多電量或提高保留門檻。", ["end_battery"], "warn")
    if (f.energy_ratio.value.calibration_eligible && f.headwind && f.headwind.value.ratio > 1.1) sug("逆風航段是超耗主因，建議把逆風段排在電量充足的前段，回程順風；規劃時選用「最省電順序」候選。", ["headwind", "worst_leg"], "warn")
    if (f.wind_change && f.best_speed && Math.abs(f.best_speed.value.speed_mps - f.best_speed.value.cruise) >= 1)
        sug("風大時把逆風段速度調到約 " + f.best_speed.value.speed_mps + " m/s 可降低單位距離耗電。", ["best_speed", "wind_change"])
    var comp = f.completion.value
    var missing = comp.all.filter(function (t) { return comp.done.indexOf(t) < 0 })
    var missMust = comp.must.filter(function (t) { return comp.done.indexOf(t) < 0 })
    var doneOpt = comp.done.filter(function (t) { return comp.must.indexOf(t) < 0 })
    if (missMust.length && doneOpt.length) sug("本次先做了選配目標（" + doneOpt.join("、") + "），卻漏掉必要目標（" + missMust.join("、") + "）；下次請選「必要目標優先」順序。", ["completion"], "warn")
    if (missing.length) sug("未完成目標：" + missing.join("、") + "，建議排入下一趟任務（可從本報告一鍵帶入規劃）。", ["completion"])
    if (!out.length) sug(f.data_quality.value.missing_wind ? "缺少風速／風向，未產生逆風建議；請補充資料後再評估校正。" :
        (f.data_quality.value.missing_current ? "本次能耗為電量差估算，尚不足以判定模型誤差；請補充電流紀錄再評估校正。" : "本次任務耗電與預估相符、電量餘裕充足，維持目前設定即可。"), ["energy_ratio", "end_battery"])
    return out
}

function makeReport(run, mission, plan, replans, alerts, versions) {
    var facts = buildFacts(run, mission, plan, replans, alerts)
    var by = function (k) { return facts.filter(function (x) { return x.key === k })[0] }
    var out = { facts: facts, suggestions: ruleSuggestions(facts), source: "rule",
             summary_zh: by("completion").text + "。" + by("energy_ratio").text + "。" + by("end_battery").text + "。" + by("data_quality").text + "。",
             next_calib: by("calib").value["new"], data_quality: by("data_quality").value,
             timeline: by("timeline").value, energy_margin: by("energy_margin").value,
             versions: {git_short_hash:(versions || {}).git_short_hash || null,prompt_hash:null,model:null} }
    if (alerts && alerts.length) out.alert_lead_time=by("alert_lead_time").value
    if (run.provenance) { out.data_provenance=run.provenance; out.calibration_eligible=out.data_quality.calibration_eligible }
    return out
}

var REPORT_SYSTEM = "你是無人機任務報告助理。只能根據給定事實（facts）寫，不可新增數字。輸出 JSON：{\"summary_zh\":\"3 句內繁體中文摘要\"," +
                    "\"suggestions\":[{\"text_zh\":\"建議\",\"evidence_ids\":[\"F1\"]}]}。建議依重要性排序，最多 5 條，每條都要引用 facts 的 id。可改寫給定的規則建議，但不可捏造。"

function reportPrompt(rep) {
    var p = { system: REPORT_SYSTEM,
             user: JSON.stringify({ facts: rep.facts.map(function (x) { return { id: x.id, text: x.text } }), rule_suggestions: rep.suggestions }) }
    p.prompt_hash=sha256Text(p.system+"\n---\n"+p.user).slice(0,16)
    return p
}

// 模型改寫的報告：沒引用事實的建議丟掉；全部被丟就保留規則版
function applyReportLlm(rep, text, metadata) {
    // Always rebuild from the rule snapshot, including after a prior accepted rewrite.
    var base=rep.rule_report ? clone(rep.rule_report) : clone(rep)
    var version=base.versions || {git_short_hash:null,prompt_hash:null,model:null}
    version.prompt_hash=(metadata || {}).prompt_hash || reportPrompt(base).prompt_hash
    version.model=(metadata || {}).model || null
    base.versions=version
    var d = extractJson(text)
    if (!d || typeof d.summary_zh !== "string" || !Array.isArray(d.suggestions)) { base.llm_fallback_reason="invalid_report_shape"; return base }
    var texts=[d.summary_zh]
    d.suggestions.forEach(function (s) { if (s && typeof s.text_zh==="string") texts.push(s.text_zh) })
    var bad=unsupportedNumbers(texts,base.facts)
    if (bad.length) { base.llm_fallback_reason="unsupported_numbers:"+bad.join(","); return base }
    if (base.data_quality && base.data_quality.missing_wind && texts.some(function (s) {return /逆風|順風|風況改變|風速增強|headwind|wind_change/i.test(s)})) {
        base.llm_fallback_reason="wind_advice_without_measurements"; return base
    }
    var ids = base.facts.map(function (x) { return x.id }), kept = []
    d.suggestions.slice(0, 5).forEach(function (s) {
        if (!s || typeof s.text_zh !== "string") return
        var ev = (Array.isArray(s.evidence_ids) ? s.evidence_ids : []).filter(function (e) { return ids.indexOf(e) >= 0 })
        if (ev.length) kept.push({ text_zh: s.text_zh, evidence_ids: ev, level: "info" })
    })
    if (!kept.length) return base
    var out = clone(base)
    out.rule_report=base
    out.rule_suggestions = base.suggestions; out.suggestions = kept; out.summary_zh = d.summary_zh; out.source = "llm"
    return out
}

// node 測試用
if (typeof module !== "undefined") module.exports = {
    transitionEstimate:transitionEstimate, rtlEnergy:rtlEnergy, estimateRouteEnergy:estimateRouteEnergy,
    turnEstimate:turnEstimate, loiterEstimate:loiterEstimate,
    missionVersion:missionVersion,checkApply:checkApply,replanContext:replanContext,
    canonicalVersion:canonicalVersion,constraintDeltas:constraintDeltas,splitSorties:splitSorties,ruleChoice:ruleChoice,timelineText:timelineText,
    loadAirframe:loadAirframe, airframeType:airframeType, speedRange:speedRange, powerW:powerW,
    turnGeometry:turnGeometry, validateAirframeProfile:validateAirframeProfile, propEfficiency:propEfficiency,
    legEstimate:legEstimate,
    haversineM: haversineM, vehicle: vehicle, wind: wind, routeEstimate: routeEstimate, bestSpeed: bestSpeed,
    planMission: planMission, replan: replan, MissionRun: MissionRun, makeReport: makeReport, predictiveAlert: predictiveAlert,
    pickPrompt: pickPrompt, validatePick: validatePick, reportPrompt: reportPrompt, applyReportLlm: applyReportLlm,
    unsupportedNumbers:unsupportedNumbers, reportEvents:reportEvents, reserveAlertLeads:reserveAlertLeads, sha256Text:sha256Text
}

// T3 version contract: finite IEEE754 doubles and UTF-8 hex strings/keys.
function timelineText(events) {
    var labels={takeoff:"起飛（推定）",start_in_air:"紀錄起點已在空中",landing:"降落（推定）",waypoint:"到達航點",alert:"告警",replan:"重規劃"}
    var parts=events.slice(0,5).map(function(e){return (e.t_s.toFixed(1)+" 秒 "+(labels[e.kind]||e.kind)+" "+(e.target_id||e.choice_id||"")).trim()})
    if(events.length>5) parts.push("另 "+(events.length-5)+" 件，詳見結構化時間軸")
    return "事件時間軸（起降為取樣推定，不代表上鎖確認）："+(parts.length?parts.join("；"):"無可推定事件")
}

function utf8Hex(text) {
    var bytes = unescape(encodeURIComponent(text)), out = ""
    for (var i = 0; i < bytes.length; ++i) out += ("0" + bytes.charCodeAt(i).toString(16)).slice(-2)
    return out
}
function canonicalVersion(value) {
    if (value === null) return "z"
    if (value === true) return "t"
    if (value === false) return "f"
    if (typeof value === "number") {
        if (!isFinite(value)) throw new Error("nonfinite mission version input")
        var buffer = new ArrayBuffer(8), view = new DataView(buffer), hex = ""
        view.setFloat64(0, value === 0 ? 0 : value, false)
        for (var i = 0; i < 8; ++i) hex += ("0" + view.getUint8(i).toString(16)).slice(-2)
        return "n" + hex
    }
    if (typeof value === "string") return "s" + utf8Hex(value)
    if (Array.isArray(value)) return "a[" + value.map(canonicalVersion).join(",") + "]"
    if (value && typeof value === "object") {
        var keys = Object.keys(value).sort(function (a,b) { var x=utf8Hex(a),y=utf8Hex(b); return x<y?-1:x>y?1:0 })
        return "o{" + keys.map(function (k) { return canonicalVersion(k) + ":" + canonicalVersion(value[k]) }).join(",") + "}"
    }
    throw new Error("unsupported mission version input")
}
function missionVersion(m, v, w, s) {
    return "t3-v1:" + sha256Text(canonicalVersion({mission:m,vehicle:v,wind:w,state:s === undefined ? null : s}))
}
function checkApply(result, m, v, w, s) {
    try { if (result && result.mission_version === missionVersion(m,v,w,s)) return {ok:true} } catch (e) {}
    return {ok:false,reason_zh:"任務已變更，請重新規劃"}
}
function replanContext(mission, vehicleIn, windIn, stateIn, event) {
    var m=clone(mission),v=clone(vehicleIn),w=clone(windIn),s=clone(stateIn)
    v.calib = rnd(s.observed_ratio !== undefined ? s.observed_ratio : v.calib,3)
    if (event.type === "wind") w=wind(event.speed_mps,event.from_deg)
    else if (event.type === "no_fly") m.no_fly=(m.no_fly||[]).concat([clone(event.zone)])
    else if (event.type === "add_target") {m.targets.push(clone(event.target));s.remaining.push(event.target.id)}
    else if (event.type === "battery") s.battery_pct=event.battery_pct
    m.completed=s.completed
    return {mission:m,vehicle:v,wind:w,state:s}
}
function constraintDeltas(m,v,path,est,missing) {
    var out=[],max=(m.limits||{}).max_altitude_m
    if (max === undefined) max=120
    if (est.margin_pct<0) out.push({violated:"reserve",short_pct:-est.margin_pct})
    path.forEach(function (p) {if ((p.alt||0)>max) out.push({violated:"altitude",point_id:p.id,over_m:p.alt-max})})
    var origin=[m.home.lat,m.home.lon]
    for (var i=0;i<path.length-1;++i) {
        var a=toXY(origin,[path[i].lat,path[i].lon]),b=toXY(origin,[path[i+1].lat,path[i+1].lon]),dx=b[0]-a[0],dy=b[1]-a[1]
        ;(m.no_fly||[]).forEach(function (z) {
            var c=toXY(origin,[z.lat,z.lon]),d=dx*dx+dy*dy
            var t=d?Math.max(0,Math.min(1,((c[0]-a[0])*dx+(c[1]-a[1])*dy)/d)):0
            var short=z.radius_m-Math.hypot(a[0]+t*dx-c[0],a[1]+t*dy-c[1])
            if (short>0) out.push({violated:"no_fly",zone_id:z.id,from:path[i].id,to:path[i+1].id,short_m:short})
        })
    }
    if (missing.length) out.push({violated:"required_targets",missing_count:missing.length,target_ids:missing.slice()})
    return out
}
function splitSorties(m,v,w,sequences,speeds) {
    if (m.targets.length<2) return null
    var best=null,seen={},ids=m.targets.map(function(t){return t.id}).sort().join("\u0000")
    sequences.forEach(function(seq) {
        for (var k=1;k<seq.length;++k) {
            var groups=[seq.slice(0,k),seq.slice(k)],key=JSON.stringify(groups.map(function(g){return g.map(function(t){return t.id})}))
            if (seen[key]) continue
            seen[key]=true
            speeds.filter(function(s,i,a){return a.indexOf(s)===i}).forEach(function(speed) {
                var sorties=groups.map(function(g,i) {
                    var sub=clone(m);sub.targets=g;sub.completed=[]
                    return evaluate("S1-"+(i+1),"分兩趟第 "+(i+1)+" 趟","獨立滿電、返航",sub,v,w,[home(m)].concat(g,[home(m)]),speed,100)
                })
                var order=sorties[0].order.concat(sorties[1].order)
                if (!sorties.every(function(s){return s.feasible}) || order.slice().sort().join("\u0000")!==ids) return
                var energy=rnd(sorties[0].energy_wh+sorties[1].energy_wh,1)
                if (best && energy>=best.energy_wh) return
                var must=m.targets.filter(function(t){return (t.priority||1)===1}).map(function(t){return t.id}),rank=0
                order.forEach(function(t,i){if(must.indexOf(t)>=0)rank+=i})
                best={id:"S1",label:"分兩趟完成全部目標",how:"兩個獨立返航架次，中間更換滿電電池",
                    note:"須分別檢視兩趟；尚無自動跨架次執行器；分割搜尋非窮舉最佳化",order:order,speed_mps:speed,calib:v.calib,
                    dist_km:rnd(sorties[0].dist_km+sorties[1].dist_km,2),time_min:rnd(sorties[0].time_min+sorties[1].time_min,1),
                    energy_wh:energy,end_pct:Math.min(sorties[0].end_pct,sorties[1].end_pct),margin_pct:Math.min(sorties[0].margin_pct,sorties[1].margin_pct),
                    feasible:true,must_rank:rank,violations:[],missing_must:[],constraint_deltas:[],sorties:sorties,requires_battery_swap:true,path:[],legs:[]}
            })
        }
    })
    return best
}

// T5b1 straight-flight only. Complete typed route/cmd3000/turn integration stays gated.
function routeNumber(x, name, low, high) {
    if (low === undefined) low = -1e100
    if (high === undefined) high = 1e100
    if (typeof x !== "number" || !isFinite(x) || x < low || x > high) throw new Error(name + ": finite number in range required")
    return x
}
function flightMode(v, mode, defaultMode) {
    var expected = airframeType(v) === "fixed_wing" ? "fw" : "mc"
    if (airframeType(v) === "vtol_hybrid") {
        if (mode === undefined || mode === null) mode = defaultMode
        if (mode !== "mc" && mode !== "fw") throw new Error("hybrid straight leg requires explicit mode='mc' or 'fw'")
        return mode
    }
    if (mode !== undefined && mode !== null && mode !== expected) throw new Error("mode is incompatible with airframe type")
    return expected
}
function routePosition(p) {
    if (!Array.isArray(p) || p.length !== 2) throw new Error("position: [lat, lon] required")
    routeNumber(p[0], "lat", -90, 90); routeNumber(p[1], "lon", -180, 180)
}
function routeWind(w) {
    routeNumber(w.speed_mps, "wind.speed_mps", 0); routeNumber(w.from_deg, "wind.from_deg")
    return windVector(w)
}
function airframeLegEstimate(v, a, b, altA, altB, groundMps, w, mode) {
    mode = flightMode(v, mode)
    routePosition(a); routePosition(b)
    routeNumber(altA,"alt_a"); routeNumber(altB,"alt_b"); routeNumber(groundMps,"ground_mps",1e-9)
    var windV = routeWind(w), we = windV[0], wn = windV[1]
    var dist = haversineM(a,b), dh = altB-altA, air, head, duration
    if (mode === "fw" && dist < 0.5) throw new Error("fixed-wing near-zero horizontal leg: loiter/takeoff/landing not modeled")
    if (dist >= 0.5) {
        var brg = bearingRad(a,b)
        air = Math.hypot(groundMps*Math.sin(brg)-we,groundMps*Math.cos(brg)-wn)
        head = -(we*Math.sin(brg)+wn*Math.cos(brg)); duration = dist/groundMps
    } else { air=w.speed_mps; head=0; duration=0 }
    var wh, watts
    if (mode === "fw") {
        watts=powerW(v,air,"fw",0,Math.max(0,dh)/duration)
        wh=watts*duration/3600*v.calib
    } else {
        if (air > v.max_mps) throw new Error("v_air: outside mc airspeed envelope")
        watts=powerW(v,air,"mc")
        var verticalS=dh>0?Math.max(0,dh)/3:Math.max(0,-dh)/2
        if (w.speed_mps > v.max_mps) throw new Error("wind exceeds mc airspeed envelope during vertical flight")
        var joules=watts*duration+powerW(v,w.speed_mps,"mc")*verticalS
        var eta=airframeType(v)==="vtol_hybrid"?v.airframe_profile.power.mc.eta:v.eta
        joules+=v.mass_kg*G*Math.max(0,dh)/eta; duration+=verticalS
        wh=joules/3600*v.calib
    }
    return {dist_m:dist,time_s:duration,energy_wh:wh,v_air:air,headwind_mps:head,mode:mode,scope:"straight_leg_only"}
}
function transitionEstimate(v, fromMode, toMode) {
    if (airframeType(v)!=="vtol_hybrid") throw new Error("transition requires vtol_hybrid")
    if (["mc","fw"].indexOf(fromMode)<0 || ["mc","fw"].indexOf(toMode)<0) throw new Error("transition modes must be mc or fw")
    var t=v.airframe_profile.transition, changed=fromMode!==toMode, prefix="to_"+toMode
    return {from_mode:fromMode,to_mode:toMode,energy_wh:changed?t[prefix+"_wh"]*v.calib:0,
            time_s:changed?t[prefix+"_s"]:0,dist_m:changed&&toMode==="fw"?t.to_fw_dist_m:0,
            scope:"transition_allowance_only"}
}
function airframeRtlEnergy(pos, home, v, w, groundMps, mode) {
    mode=flightMode(v,mode,"fw")
    var a=[pos.lat,pos.lon], b=[home.lat,home.lon]
    routePosition(a); routePosition(b)
    var alt=routeNumber(pos.alt===undefined?0:pos.alt,"rtl.alt",0)
    if (routeNumber(home.alt===undefined?0:home.alt,"home.alt")!==0) throw new Error("RTL expects altitude relative to home ground; home.alt must be zero")
    var speed=groundMps===undefined||groundMps===null?v.cruise_mps:groundMps
    routeNumber(speed,"ground_mps",1e-9); routeWind(w)
    var legs=[]
    if (airframeType(v)==="fixed_wing") legs.push(airframeLegEstimate(v,a,b,alt,alt,speed,w,"fw"))
    else if (mode==="fw") {
        if (haversineM(a,b)>=0.5) legs.push(airframeLegEstimate(v,a,b,alt,alt,speed,w,"fw"))
        legs.push(transitionEstimate(v,"fw","mc"))
        legs.push(airframeLegEstimate(v,b,b,alt,0,speed,w,"mc"))
    } else legs.push(airframeLegEstimate(v,a,b,alt,0,speed,w,"mc"))
    var wh=0,ts=0,dm=0
    legs.forEach(function(x){wh+=x.energy_wh;ts+=x.time_s;dm+=x.dist_m})
    var cap=routeNumber(v.battery_wh*v.usable_frac,"usable capacity",1e-9)
    return {dist_m:dm,time_s:ts,energy_wh:wh,used_pct:wh/cap*100,legs:legs,
            arrival_mode:airframeType(v)==="fixed_wing"?"fw":"mc",landing_modeled:airframeType(v)!=="fixed_wing",
            scope:"rtl_energy_only_not_executable_route"}
}
function airframeBestSpeed(v,w,headingDeg,lo,hi,mode) {
    mode=flightMode(v,mode,"fw")
    if (headingDeg===undefined) headingDeg=0
    if (lo===undefined) lo=4
    routeNumber(headingDeg,"heading_deg");routeNumber(lo,"lo",0)
    var range=mode==="fw"?speedRange(v):[0,v.max_mps]
    var upper=hi===undefined||hi===null?range[1]:Math.min(range[1],routeNumber(hi,"hi",0))
    var lower=Math.max(range[0],lo),wv=routeWind(w),theta=rad(headingDeg)
    var tail=wv[0]*Math.sin(theta)+wv[1]*Math.cos(theta),cross=wv[0]*Math.cos(theta)-wv[1]*Math.sin(theta)
    var best=null,count=Math.max(0,Math.floor((upper-lower)/.5+1e-9)+1)
    for (var k=0;k<count;k++) {
        var air=lower+k*.5
        if (air<=Math.abs(cross)) continue
        var ground=tail+Math.sqrt(Math.max(0,air*air-cross*cross))
        if (ground<=1e-9) continue
        var perKm=powerW(v,air,mode)*v.calib/ground/3.6
        if (best===null || perKm<best.wh_per_km) best={speed_mps:ground,airspeed_mps:air,wh_per_km:perKm}
    }
    if (best===null) throw new Error("no feasible forward airspeed in configured search interval/wind")
    best.wh_per_km=rnd(best.wh_per_km,2)
    return best
}

function estimateRouteEnergy(points,v,w,groundMps,startPct,mode) {
    if (groundMps===undefined||groundMps===null) groundMps=v.cruise_mps
    var pts=points.map(function(p,i){var q=clone(p);if(q.id===undefined)q.id="P"+i;return q})
    return routeEstimate(v,pts,groundMps,w,startPct,0,mode)
}
function rtlEnergy(pos,home,v,w,groundMps,mode) {
    if (airframeType(v)!=="multirotor") return airframeRtlEnergy(pos,home,v,w,groundMps,mode)
    flightMode(v,mode)
    var p=clone(pos),h=clone(home);p.id="here";h.id="home";h.alt=0
    return estimateRouteEnergy([p,h],v,w,groundMps)
}

// T5b2a: normalized local energy events, never raw MAVLink or a flown path.
function turnEstimate(v, vAir, angleDeg, w, bankDeg, radiusM) {
    routeNumber(angleDeg,"angle_deg",0,360); routeWind(w)
    if(w.speed_mps!==0) throw new Error("FW arc requires calm wind; ground-track turn model pending")
    var g=turnGeometry(v,vAir,bankDeg,radiusM)
    if(g.radius_m===null && angleDeg!==0) throw new Error("nonzero turn requires nonzero bank")
    var distance=(g.radius_m||0)*rad(angleDeg), seconds=distance/routeNumber(vAir,"v_air",1e-9)
    g.angle_deg=angleDeg;g.dist_m=distance;g.time_s=seconds
    g.energy_wh=powerW(v,vAir,"fw",g.bank_deg)*seconds/3600*v.calib
    g.mode="fw";g.scope="additive_air_relative_arc_allowance"
    return g
}
function loiterEstimate(v,vAir,durationS,w,radiusM,mode) {
    mode=flightMode(v,mode)
    routeNumber(durationS,"duration_s",0,86400);routeNumber(vAir,"v_air",1e-9);routeWind(w)
    if(mode==="mc") {
        if(radiusM!==undefined && radiusM!==null) throw new Error("MC hold does not accept an orbit radius")
        if(w.speed_mps>v.max_mps) throw new Error("wind exceeds mc airspeed envelope during hold")
        return {dist_m:0,time_s:durationS,energy_wh:powerW(v,w.speed_mps,"mc")*durationS/3600*v.calib,mode:"mc",scope:"stationary_mc_hold"}
    }
    if(w.speed_mps!==0) throw new Error("FW loiter requires calm wind; ground-track orbit model pending")
    var g=turnGeometry(v,vAir,undefined,radiusM)
    g.dist_m=vAir*durationS;g.time_s=durationS
    g.energy_wh=powerW(v,vAir,"fw",g.bank_deg)*durationS/3600*v.calib
    g.mode="fw";g.scope="air_relative_loiter_allowance"
    return g
}
function airframeRouteEstimate(v,points,groundMps,w,startPct,hoverS,mode) {
    if(airframeType(v)==="multirotor") throw new Error("typed_route is reserved for FW/hybrid; legacy MC route unchanged")
    if(!Array.isArray(points)||points.length<2||points.length>1000) throw new Error("route requires 2..1000 normalized events")
    if(startPct===undefined)startPct=100
    if(hoverS===undefined)hoverS=5
    routeNumber(groundMps,"ground_mps",1e-9);routeNumber(startPct,"start_pct",0,100)
    routeNumber(hoverS,"hover_s_per_wp",0,86400);routeWind(w)
    var cap=routeNumber(v.battery_wh*v.usable_frac,"usable capacity",1e-9)
    var has=function(o,k){return Object.prototype.hasOwnProperty.call(o,k)}
    var get=function(o,k,d){return has(o,k)?o[k]:d}
    var pose=function(p){if(!p||typeof p!=="object"||Array.isArray(p))throw new Error("point must be an object");routePosition([p.lat,p.lon]);routeNumber(get(p,"alt",0),"alt",0)}
    var first=points[0];pose(first)
    if(has(first,"cmd")||first.kind==="landing"||first.kind==="loiter")throw new Error("first event must be a pose, not a command/landing/loiter")
    if(mode!==undefined&&mode!==null&&get(first,"mode",mode)!==mode)throw new Error("initial mode contradicts first.mode")
    var initial=mode===undefined||mode===null?first.mode:mode
    if((initial===undefined||initial===null)&&first.kind==="takeoff")initial="mc"
    var active=flightMode(v,initial)
    if(first.kind==="takeoff"&&(airframeType(v)!=="vtol_hybrid"||active!=="mc"||get(first,"alt",0)!==0))throw new Error("takeoff start requires hybrid mc on ground")
    var current=clone(first);current.id=get(first,"id","P0")
    var legs=[],heading=null,landed=false,afterFwLoiter=false,pct=startPct
    var add=function(part,eventId){pct-=part.energy_wh/cap*100;part.from=current.id;part.to=eventId;part.pct_after=pct;legs.push(part)}
    var addTransition=function(t,eventId){t.transition_allowance_dist_m=t.dist_m;t.dist_m=0;add(t,eventId)}
    for(var i=1;i<points.length;i++) {
        var raw=points[i]
        if(!raw||typeof raw!=="object"||Array.isArray(raw))throw new Error("event must be an object")
        var eventId=get(raw,"id","P"+i)
        if(landed)throw new Error("events after landing are unsupported")
        if(has(raw,"cmd")) {
            if(raw.cmd!==3000||airframeType(v)!=="vtol_hybrid")throw new Error("only normalized hybrid cmd3000 is supported")
            Object.keys(raw).forEach(function(k){if(["id","cmd","to_mode","lat","lon","alt"].indexOf(k)<0)throw new Error("unsupported cmd3000 fields; normalize before estimating")})
            ;["lat","lon","alt"].forEach(function(k){if(has(raw,k)){routeNumber(raw[k],k);if(raw[k]!==get(current,k,0))throw new Error("cmd3000 cannot change pose")}})
            var t=transitionEstimate(v,active,raw.to_mode),changed=active!==t.to_mode
            addTransition(t,eventId);active=t.to_mode;if(changed){heading=null;afterFwLoiter=false}
            continue
        }
        pose(raw)
        var kind=get(raw,"kind","waypoint")
        if(["waypoint","target","home","takeoff","landing","loiter"].indexOf(kind)<0)throw new Error("unsupported normalized point kind")
        if(kind==="takeoff"||kind==="landing") {
            if(airframeType(v)!=="vtol_hybrid")throw new Error("FW takeoff/landing geometry is not modeled")
            if(kind==="takeoff"&&(get(current,"alt",0)!==0||get(raw,"alt",0)<=0))throw new Error("takeoff must leave ground for positive altitude")
            if(kind==="landing"&&(get(raw,"alt",0)!==0||get(current,"alt",0)<=0))throw new Error("landing must descend to relative ground altitude zero")
            if(active!=="mc"){addTransition(transitionEstimate(v,active,"mc"),eventId);active="mc";heading=null;afterFwLoiter=false}
        }
        if(get(raw,"mode",active)!==active)throw new Error("mode changes require cmd3000 or a takeoff/landing event")
        var a=[current.lat,current.lon],b=[raw.lat,raw.lon],distance=haversineM(a,b)
        var outbound=distance>=.5?bearingRad(a,b):null
        if(active==="fw"&&afterFwLoiter&&outbound!==null)throw new Error("FW departure after loiter requires an exit-heading model")
        if(active==="fw"&&heading!==null&&outbound!==null) {
            var angle=Math.abs((( (outbound-heading)*180/Math.PI+180)%360+360)%360-180)
            if(angle>1e-9)add(turnEstimate(v,groundMps,angle,w),current.id)
        }
        var dwell=get(raw,"loiter_s",kind==="target"?hoverS:0)
        routeNumber(dwell,"loiter_s",0,86400)
        if(kind==="loiter"&&dwell<=0)throw new Error("loiter event requires positive loiter_s")
        var samePoseHold=active==="fw"&&distance<.5&&get(raw,"alt",0)===get(current,"alt",0)&&dwell>0
        if(!samePoseHold)add(airframeLegEstimate(v,a,b,get(current,"alt",0),get(raw,"alt",0),groundMps,w,active),eventId)
        if(dwell>0)add(loiterEstimate(v,groundMps,dwell,w,raw.radius_m,active),eventId)
        else if(has(raw,"radius_m"))throw new Error("radius_m requires a positive loiter duration")
        heading=active==="fw"&&dwell===0?outbound:null
        afterFwLoiter=active==="fw"&&dwell>0
        current=clone(raw);current.id=eventId;landed=kind==="landing"
    }
    var wh=0,ts=0,dm=0,td=0
    legs.forEach(function(x){wh+=x.energy_wh;ts+=x.time_s;dm+=x.dist_m;td+=x.transition_allowance_dist_m||0})
    var energyOk=pct>=v.reserve_pct
    return {dist_m:dm,time_s:ts,energy_wh:wh,end_pct:pct,used_pct:startPct-pct,margin_pct:pct-v.reserve_pct,
            feasible:energyOk&&landed,energy_feasible:energyOk,arrival_mode:active,landing_modeled:landed,
            transition_allowance_dist_m:td,scope:"normalized_route_energy_only_not_executable_route",legs:legs}
}
