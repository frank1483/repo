// bind-m1-0.4.3：W2 右側標籤上下順序必須和線條一致（數值高的在上），空間不夠往上推時也不改順序（host02 run1 600／400 高顛倒）。
const { Tools, Claims, Bind, Layout } = require('./load.js')
let pass = 0, fail = 0; const log = []
function ok(n, c, i) { if (c) pass++; else { fail++; log.push('FAIL ' + n + ' :: ' + JSON.stringify(i)) } }
const R = (a, b) => { const s = []; for (let t = 0; t <= 60; ++t) s.push({ t, soc: a + b * t / 60 }); return s }
const res = [Tools.energyTrend(R(30, -15), { now: 60, reservePct: 20, vehicleType: "multirotor" })]
const a = Claims.answer(res, {}), p = Layout.plan("r1", a, res)
const d = Bind.resolve(p.nodes.find(n => n.component_id === "W2_SERIES"), res, a).data
const b = Bind.w2LabelBox(Bind.seriesLabels(d, 100, 0))
for (const H of [240, 160, Bind.w2MinH(d), 400]) {
  const ch = H - Bind.W2M.top - Bind.W2M.bottom, lab = Bind.seriesLabels(d, ch, 0), t = Bind.labelTops(lab, ch, b.hCur, b.hRes)
  ok('H' + H + ' reserve (20) above current (15)', t.reserve + b.hRes <= t.current + 1e-9, t)
  ok('H' + H + ' inside', t.reserve >= 0 && t.current + b.hCur <= ch + 1e-9, [t, ch])
}
// 一般性：隨機位置，順序不變、不重疊、在畫布內
let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647
for (let k = 0; k < 200; ++k) {
  const h = 60 + Math.floor(rnd() * 200), hc = 27 * (1 + Math.floor(rnd() * 2)), hr = 27
  if (hc + hr > h) continue
  const cy = rnd() * h, ry = rnd() * h, t = Bind.labelTops({ current: { y: cy }, reserve: { y: ry } }, h, hc, hr)
  const curUp = cy <= ry
  const order = curUp ? t.current + hc <= t.reserve + 1e-9 : t.reserve + hr <= t.current + 1e-9
  const inside = t.current >= -1e-9 && t.current + hc <= h + 1e-9 && t.reserve >= -1e-9 && t.reserve + hr <= h + 1e-9
  if (!order || !inside) { ok('random ' + k, false, { h, hc, hr, cy, ry, t }); break }
}
ok('random cases', true)
console.log(log.join('\n')); console.log(`test_bind_v6 (${Bind.BIND_VERSION}): pass ${pass} fail ${fail}`); process.exit(fail ? 1 : 0)
