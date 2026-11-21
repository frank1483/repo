// F2 DEVIATION（tools-m1-0.5、claims-m1-0.5）：手算案例＋回答句；並輸出 JSON 給 Python 參考實作逐位比對。
const { Tools, Claims } = require('./load.js'), cases = require('./f2_cases.js'), fs = require('fs')
let pass = 0, fail = 0; const log = [], out = []
function ok(n, c, i) { if (c) pass++; else { fail++; log.push('FAIL ' + n + ' :: ' + JSON.stringify(i)) } }
const near = (a, b) => Math.abs(a - b) < 1e-6 * Math.max(1, Math.abs(b))
for (const c of cases) {
  const r = Tools.flightlogDeviation(c.wp, c.s, c.t0, c.t1, c.gaps), e = c.expect
  const mx = r.facts.find(f => f.subject === 'deviation.max'), mn = r.facts.find(f => f.subject === 'deviation.mean'), se = r.facts.find(f => f.subject === 'deviation')
  out.push({ name: c.name, status: r.status, max: mx ? mx.value : null, mean: mn ? mn.value : null, n_series: se ? se.points.length : null, reason: r.detail ? r.detail.reason || null : null })
  ok(c.name + ' status', r.status === e.status, [r.status, r.detail])
  if (e.max !== undefined) ok(c.name + ' max', mx && near(mx.value, e.max), mx && mx.value)
  if (e.mean !== undefined) ok(c.name + ' mean', mn && near(mn.value, e.mean), mn && mn.value)
  if (e.reason) ok(c.name + ' reason', r.detail && r.detail.reason === e.reason, r.detail)
  if (e.breaks !== undefined) ok(c.name + ' breaks', r.detail.breaks.length === e.breaks && r.detail.valid_segments === e.segs, r.detail)
  if (e.down) ok(c.name + ' downsampled ≤300', se.downsampled && se.points.length <= 300, se.points.length)
}
// 斷段不接：樣本離 B–C 直線 40 m，但到最近端點（B 或 C）要 sqrt(100²+40²)
const ib = Tools.flightlogDeviation(cases[3].wp, cases[3].s, 0, 10)
ok('break not joined', near(ib.facts.find(f => f.subject === 'deviation.max').value, Math.sqrt(100 * 100 + 40 * 40)), ib.facts)
// 回答句：原始精度存入、顯示一位小數；最大值附時間
const r1 = Tools.flightlogDeviation(cases[0].wp, [{ t: 3, lat: cases[0].s[0].lat, lon: cases[0].s[0].lon }], 0, 10)
const a = Claims.answer([r1], {}), txt = a.lines.map(l => l.text)
ok('max sentence with time', txt.some(t => t === '該趟紀錄中偏離航線距離最大值是 11公尺（t=3 秒）'), txt)
ok('mean sentence', txt.some(t => t === '該趟紀錄中偏離航線距離平均值是 11公尺'), txt)
const r2 = Tools.flightlogDeviation(cases[0].wp, [{ t: 0, lat: 0.000113, lon: cases[0].s[0].lon }], 0, 10)
ok('raw precision kept', r2.facts[1].value !== Math.round(r2.facts[1].value * 10) / 10, r2.facts[1].value)
ok('INSUFFICIENT → T-CANNOT', Claims.answer([Tools.flightlogDeviation(cases[4].wp, cases[4].s, 0, 10)], {}).lines.some(l => l.template_id === 'T-CANNOT' && l.text === '飛行紀錄樣本不足，無法估計'))
ok('versions', /^tools-m1-0\.[5-9]/.test(Tools.TOOLS_VERSION) && /^claims-m1-0\.[5-9]/.test(Claims.CLAIMS_VERSION), [Tools.TOOLS_VERSION, Claims.CLAIMS_VERSION])
fs.writeFileSync(process.argv[2] || '/dev/null', JSON.stringify(out, (k, v) => typeof v === 'number' ? v.toPrecision(17) : v))
console.log(log.join('\n')); console.log(`test_f2_v1: pass ${pass} fail ${fail}`); process.exit(fail ? 1 : 0)
