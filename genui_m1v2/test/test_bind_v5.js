// bind-m1-0.4.2：使用者 11/20 21:02：W2 在 1280 寬完整顯示差距，可換行並讓元件增高。舊測試不動。
const { Tools, Claims, Bind, Layout } = require('./load.js')
let pass = 0, fail = 0; const log = []
function ok(n, c, i) { if (c) pass++; else { fail++; log.push('FAIL ' + n + ' :: ' + JSON.stringify(i)) } }
const R = (a, b) => { const s = []; for (let t = 0; t <= 60; ++t) s.push({ t, soc: a + b * t / 60 }); return s }
const al = [{ t: 10, level: "critical", predictor: "電池", text: "電壓過低" }]
const man = [{ chunk_id: "k1", doc: "PX4 使用手冊", heading: "返航（RTL）", version: "v1.15", text: "返航保留電量的設定方式：在電池故障保護頁設定低電量門檻，到達門檻時飛機會自動返航。" }]
const res = [Tools.energyTrend(R(30, -15), { now: 60, reservePct: 20, vehicleType: "multirotor" }), Tools.alertHistory(al, { t0: 0, t1: 70 }, []), Tools.manualSearch(man, "返航保留電量", {})]
const a = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] }), p = Layout.plan("r1", a, res), cm = (n, w) => Bind.contentMinH(n, res, a, w)
const w2 = p.nodes.find(n => n.component_id === "W2_SERIES"), d = Bind.resolve(w2, res, a).data
const lab = Bind.seriesLabels(d, 100, 0)
ok('diff text', lab.diff === "低於保留值 5 個百分點", lab.diff)
const b = Bind.w2LabelBox(lab)
ok('current label = value line + diff line(s)', b.curLines >= 2 && b.hCur === b.curLines * Bind.W2M.lineH, b)
ok('every segment fits its lines', [lab.current.text, lab.diff].every(t => Bind.textLines(t, Bind.W2M.px, Bind.W2M.rightW - 8) * (Bind.W2M.rightW - 8) * 0.95 >= Bind.textWidth(t, Bind.W2M.px)))
const lng = Object.assign({}, lab, { diff: "低於保留值 12.5 個百分點，請注意返航所需電量" })
ok('long diff wraps to more lines', Bind.w2LabelBox(lng).curLines > b.curLines, Bind.w2LabelBox(lng))
const mh = Bind.w2MinH(d)
ok('w2MinH = top + labels + bottom', mh === Bind.W2M.top + b.hCur + b.hRes + Bind.W2M.bottom, mh)
ok('contentMinH W2', Bind.contentMinH(w2, res, a, 632) === mh)
for (const H of [1080, 600, 400, 300]) {
  const L = Layout.layout(p, { width: 1280, height: H, revision: 1 }, res, { request_id: "r1", answer: a }, cm)
  const r = L.ok && L.layout.rects.find(x => x.node_id === w2.node_id)
  ok('1280x' + H + ' W2 not below content min', !r || r.height >= mh, r)
}
const t = Bind.labelTops(Bind.seriesLabels(d, mh - Bind.W2M.top - Bind.W2M.bottom, b.hCur), mh - Bind.W2M.top - Bind.W2M.bottom, b.hCur, b.hRes)
ok('labels inside canvas at min height', t.current >= 0 && t.current + b.hCur <= mh - 51 + 1e-9 && t.reserve >= 0 && t.reserve + b.hRes <= mh - 51 + 1e-9, t)
ok('labels do not overlap', t.current + b.hCur <= t.reserve || t.reserve + b.hRes <= t.current, t)
ok('version', Bind.BIND_VERSION === "bind-m1-0.4.2")
console.log(log.join('\n')); console.log(`test_bind_v5 (${Bind.BIND_VERSION}): pass ${pass} fail ${fail}`); process.exit(fail ? 1 : 0)
