// 0.4.1b 的 Qt 原生 qml 驗證情境（node 與 Qt 共用，逐字比對）。沿用 qt_poc/scenarios.js 的能力檢查，改用 0.4 起的新簽名（trusted）。
function runAll(Gate, Tools, Claims, Layout, input) {
    var out = { caps: {}, gate: {}, energy: {}, flightlog: {}, manual: {}, k6: {}, claims: {} }
    out.caps.capabilityOk = Gate.capabilityOk()
    out.caps.nfkc = Gate.normalize("Ａ　Ｂ")
    out.caps.len200 = Gate.gate("電量" + new Array(199).join("𠀀"))["class"]
    out.caps.len201 = Gate.gate("電量" + new Array(200).join("𠀀"))["class"]
    out.caps.ext_a = Gate.gate("㐀")["class"]
    out.caps.sort_stable = (function () { var a = []; for (var i = 0; i < 50; ++i) a.push({ k: i % 3, i: i }); a.sort(function (x, y) { return x.k - y.k }); for (i = 1; i < a.length; ++i) if (a[i].k === a[i - 1].k && a[i].i < a[i - 1].i) return false; return true })()
    var g, i
    for (g = 0; g < input.gate.length; ++g) out.gate[input.gate[g]] = Gate.gate(input.gate[g])
    for (i = 0; i < input.energy.length; ++i) { var c = input.energy[i]; out.energy[c.id] = Tools.energyTrend(c.samples, c.opts) }
    for (i = 0; i < input.flightlog.length; ++i) { var f = input.flightlog[i]; out.flightlog[f.id] = Tools.flightlogSeries(f.field, f.unit, f.samples, f.t0, f.t1, f.gaps) }
    for (i = 0; i < input.manual.length; ++i) { var m = input.manual[i]; out.manual[m.id] = Tools.manualSearch(m.chunks, m.query, m.glossary) }
    var R = function (a, b) { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, soc: a + b * t / 60 }); return s }
    var res = [Tools.energyTrend(R(80, -1), { now: 60, reservePct: 20, vehicleType: "multirotor" }),
               Tools.alertHistory([{ t: 10, level: "critical", predictor: "p", text: "a" }, { t: 20, level: "warning", predictor: "p", text: "b" }, { t: 30, level: "info", predictor: "p", text: "c" }], { t0: 0, t1: 60 }, []),
               Tools.manualSearch([{ chunk_id: "k1", doc: "D", heading: "RTL", version: "v1", text: "返航保留電量的設定方式" }], "返航保留電量", {})]
    var a = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] }), p = Layout.plan("r1", a, res), tr = { request_id: "r1", answer: a }
    out.k6.answer = a; out.k6.plan = p; out.k6.validate = Layout.validatePlan(p, res, tr)
    var hs = [1080, 600, 500, 400, 200, 120]
    for (var h = 0; h < hs.length; ++h) out.k6["layout_" + hs[h]] = Layout.layout(p, { width: 1920, height: hs[h], revision: 1 }, res, tr)
    out.k6.no_trusted = Layout.validatePlan(p, res, null)
    out.k6.wrong_req = Layout.validatePlan(p, res, { request_id: "r2", answer: a })
    out.claims.extra_field = Claims.answer(res, {}, '{"schema":"qa.claims/1","selected_claim_ids":["C1"],"text":"電量999%"}')
    out.claims.json_tail = Claims.answer(res, {}, '{"schema":"qa.claims/1","selected_claim_ids":["C1"]} x')
    var same = []; for (var k = 0; k < 40; ++k) same.push({ t: 10 * (k % 3), level: "warning", predictor: "p", text: "e" + k })
    out.alerts_same_t = Tools.alertHistory(same, { t0: 0, t1: 60 }, []).facts[1].rows.map(function (x) { return x.text })
    out.tamper = Layout.validatePlan(JSON.parse(JSON.stringify(p).replace('"component_id":"W5_DOC"', '"component_id":"toString"')), res, tr)
    out.content_terms = input.terms.map(function (q) { return Tools.contentTerms(q) })
    out.check_apply = [Layout.checkApply("tx1", "tx1"), Layout.checkApply("tx2", "tx1"), Layout.checkApply("", "")]
    return out
}
