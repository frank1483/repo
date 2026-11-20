// bind-m1-0.3.1：labelTops 避讓測試（real02 long 情境重疊）。test_bind_v2 不動。
const { Bind } = require('./load.js')
let pass = 0, fail = 0; const log = []
function ok(n, c, i) { if (c) pass++; else { fail++; log.push('FAIL ' + n + ' :: ' + JSON.stringify(i)) } }
const noOv = (t, hc, hr) => t.current + hc <= t.reserve || t.reserve + hr <= t.current
const inside = (t, h, hc, hr) => t.current >= 0 && t.current + hc <= h && t.reserve >= 0 && t.reserve + hr <= h
const H = 200, hc = 40, hr = 20
for (const [cy, ry, name] of [[190, 120, 'long-like: current low, reserve above'], [10, 195, 'base-like far apart'], [100, 105, 'very close'], [199, 199, 'both bottom'], [0, 0, 'both top'], [150, 190, 'reserve bottom']]) {
  const t = Bind.labelTops({ current: { y: cy }, reserve: { y: ry } }, H, hc, hr)
  ok('no overlap ' + name, noOv(t, hc, hr), t); ok('inside ' + name, inside(t, H, hc, hr), t)
}
const t1 = Bind.labelTops({ current: { y: 190 }, reserve: { y: 120 } }, H, hc, hr)
ok('higher value on top (reserve above current)', t1.reserve < t1.current, t1)
const t2 = Bind.labelTops({ current: { y: 10 }, reserve: { y: 195 } }, H, hc, hr)
ok('far apart unchanged', t2.current === 0 && t2.reserve === 180, t2)
ok('no reserve', Bind.labelTops({ current: { y: 50 }, reserve: null }, H, hc, hr).reserve === null)
console.log(log.join('\n')); console.log(`test_bind_v3_labels (${Bind.BIND_VERSION}): pass ${pass} fail ${fail}`); process.exit(fail ? 1 : 0)
