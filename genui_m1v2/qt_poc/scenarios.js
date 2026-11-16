// QJSEngine 載入 PoC 與 node 共用的情境。不含 .pragma；QML 端用 import 載入，node 端用 new Function 載入。
// 回傳純 JSON 可序列化的結果，兩邊逐字比對。
function runAll(Gate, Tools, Claims, Layout, input) {
    var out = { caps: {}, gate: {}, energy: {}, k6: {}, claims: {} }
    out.caps.capabilityOk = Gate.capabilityOk()
    out.caps.nfkc = Gate.normalize("Ａ　Ｂ")
    out.caps.len200 = Gate.gate("電量" + new Array(199).join("𠀀"))["class"]
    out.caps.len201 = Gate.gate("電量" + new Array(200).join("𠀀"))["class"]
    out.caps.ext_a = Gate.gate("㐀")["class"]
    out.caps.sort_stable = (function () { var a = []; for (var i = 0; i < 50; ++i) a.push({ k: i % 3, i: i }); a.sort(function (x, y) { return x.k - y.k }); for (i = 1; i < a.length; ++i) if (a[i].k === a[i - 1].k && a[i].i < a[i - 1].i) return false; return true })()
    for (var g = 0; g < input.gate.length; ++g) out.gate[input.gate[g]] = Gate.gate(input.gate[g])
    for (var e = 0; e < input.energy.length; ++e) {
        var c = input.energy[e], r = Tools.energyTrend(c.samples, c.opts)
        out.energy[c.id] = { status: r.status, detail: r.detail, coverage: r.coverage, facts: r.facts }
    }
    // K-6
    var R = function (a, b) { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, soc: a + b * t / 60 }); return s }
    var res = [Tools.energyTrend(R(80, -1), { now: 60, reservePct: 20, vehicleType: "multirotor" }),
               Tools.alertHistory([{ t: 10, level: "critical", predictor: "p", text: "a" }, { t: 20, level: "warning", predictor: "p", text: "b" }, { t: 30, level: "info", predictor: "p", text: "c" }], { t0: 0, t1: 60 }, []),
               Tools.manualSearch([{ chunk_id: "k1", doc: "D", heading: "RTL", version: "v1", text: "返航保留電量的設定方式" }], "返航保留電量", {})]
    var a = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] }), p = Layout.plan("r1", a, res)
    out.k6.answer = a; out.k6.plan = p
    var hs = [1080, 600, 500, 400, 200, 120]
    for (var h = 0; h < hs.length; ++h) out.k6["layout_" + hs[h]] = Layout.layout(p, { width: 1920, height: hs[h], revision: 1 }, res)
    out.claims.extra_field = Claims.answer(res, {}, '{"schema":"qa.claims/1","selected_claim_ids":["C1"],"text":"電量999%"}')
    out.claims.json_tail = Claims.answer(res, {}, '{"schema":"qa.claims/1","selected_claim_ids":["C1"]} x')
    out.tamper = Layout.validatePlan(JSON.parse(JSON.stringify(p).replace('"component_id":"W5_DOC"', '"component_id":"toString"')), res)
    return out
}
