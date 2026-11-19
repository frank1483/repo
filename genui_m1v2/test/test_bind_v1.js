// GenuiBind 單元測試（W1～W5 說明 v1.2 §4 第 1 步）
const { Tools, Claims, Layout, Bind } = require('./load.js')
let pass = 0, fail = 0; const log = []
function ok(name, cond, info) { if (cond) pass++; else { fail++; log.push('FAIL ' + name + (info !== undefined ? ' :: ' + JSON.stringify(info) : '')) } }
const R = (a, b, n = 60) => { const s = []; for (let t = 0; t <= n; ++t) s.push({ t, soc: a + b * t / 60 }); return s }
const AL = [{ t: 10, level: 'critical', predictor: 'p', text: 'a' }, { t: 20, level: 'warning', predictor: 'p', text: 'b' }, { t: 30, level: 'info', predictor: 'p', text: 'c' }]
const MAN = [{ chunk_id: 'k1', doc: 'D', heading: 'RTL', version: 'v1', text: '返航保留電量的設定方式' }]
function setup(energy, opts) {
  const res = [energy, Tools.alertHistory(AL, { t0: 0, t1: 60 }, []), Tools.manualSearch(MAN, '返航保留電量', {})]
  const a = Claims.answer(res, opts || {}), p = Layout.plan('r1', a, res)
  return { res, a, p, node: c => p.nodes.find(n => n.component_id === c) }
}
const S = setup(Tools.energyTrend(R(80, -1), { now: 60, reservePct: 20, vehicleType: 'multirotor' }))
ok('validate', Layout.validatePlan(S.p, S.res, { request_id: 'r1', answer: S.a }).ok)
// W1
const w1 = Bind.resolve(S.node('W1_FACT'), S.res, S.a)
ok('W1 ok', w1.ok && w1.data.lines.length === S.a.lines.length, w1)
ok('W1 text same as answer', w1.data.lines.every(l => S.a.lines.some(x => x.text === l.text)))
const mand = [{ text: 'a', mandatory: false }, { text: 'M', mandatory: true }, { text: 'b', mandatory: false }]
const w1m = Bind.resolve({ node_id: 'n', component_id: 'W1_FACT', binding_ref: {} }, [], { lines: mand })
ok('W1 mandatory first', w1m.data.lines[0].text === 'M' && w1m.data.lines[1].text === 'a', w1m.data.lines)
ok('W1 no answer', !Bind.resolve(S.node('W1_FACT'), S.res, null).ok)
// W2
const w2 = Bind.resolve(S.node('W2_SERIES'), S.res, S.a)
ok('W2 ok', w2.ok && w2.data.points.length === 61 && w2.data.reserve_pct === 20, w2.ok && { n: w2.data.points.length, r: w2.data.reserve_pct })
ok('W2 axis covers reserve', w2.data.y.min < 20 && w2.data.y.max > 80, w2.data.y)
ok('W2 axis const', JSON.stringify(Bind.axisRange([5, 5, 5], null)) === '{"min":4,"max":6}')
ok('W2 axis pad', (() => { const y = Bind.axisRange([0, 100], null); return Math.abs(y.min + 5) < 1e-9 && Math.abs(y.max - 105) < 1e-9 })())
const fl = Tools.flightlogSeries('alt', 'm', [{ t: 0, value: 1 }, { t: 10, value: 2 }, { t: 40, value: 3 }, { t: 50, value: 4 }], 0, 50, [[15, 35]])
const w2f = Bind.resolve({ node_id: 'x', component_id: 'W2_SERIES', binding_ref: { ref: '0:F1' } }, [fl], null)
ok('W2 flightlog', w2f.ok && w2f.data.reserve_pct === null && w2f.data.unit === 'm', w2f)
const segs = Bind.seriesPaths(w2f.data, 500, 100)
ok('W2 gap splits line', segs.length === 2 && segs[0].length === 2 && segs[1].length === 2, segs.map(s => s.length))
ok('W2 path in box', segs.flat().every(p => p.x >= 0 && p.x <= 500 && p.y >= 0 && p.y <= 100))
const long = { tool: 'T_FLIGHTLOG', facts: [{ fact_id: 'F1', kind: 'series', subject: 'alt', unit: 'm', points: Array.from({ length: 151 }, (_, i) => ({ t: i, value: i })) }], coverage: { requested: [0, 151], gaps: [] } }
ok('W2 >150 rejected', Bind.resolve({ component_id: 'W2_SERIES', binding_ref: { ref: '0:F1' } }, [long], null).error === 'SERIES_TOO_LONG')
ok('W2 bad ref', Bind.resolve({ component_id: 'W2_SERIES', binding_ref: { ref: '9:F1' } }, S.res, null).error === 'BINDING_NOT_FOUND')
ok('W2 empty series no paths', Bind.seriesPaths({ points: [], y: null, gaps: [], t0: 0, t1: 1 }, 10, 10).length === 0)
// W3
const w3 = Bind.resolve(S.node('W3_TABLE'), S.res, S.a)
ok('W3 ok order', w3.ok && w3.data.rows.map(r => r.text).join('') === 'cba' && w3.data.has_critical, w3.data)
ok('W3 tones', w3.data.rows.map(r => r.tone).join(',') === 'textPrimary,statusWarning,statusCritical')
ok('W3 wrong tool', !Bind.resolve({ component_id: 'W3_TABLE', binding_ref: { ref: '0:F3' } }, S.res, null).ok)
// W4
const w4 = Bind.resolve(S.node('W4_DIAG'), S.res, S.a)
ok('W4 ok', w4.ok && w4.data.cards.length >= 1 && w4.data.cards.length <= 3, w4)
const both = Bind.resolve({ component_id: 'W4_DIAG', binding_ref: { ref: ['0:F1', '0:F2'] } }, S.res, null)
ok('W4 3 cards', both.ok && both.data.cards.map(c => c.key).join() === 'soc,slope,eta', both.data && both.data.cards)
const soc = both.data.cards.find(c => c.key === 'soc'), eta = both.data.cards.find(c => c.key === 'eta')
ok('W4 soc text = claims', soc.value === '79' && soc.accent === 'telemetryMetricGreen', soc)
ok('W4 eta = claims', eta.value === '59' && eta.unit === '分鐘' && S.a.lines.some(l => l.text.indexOf('約 59 分鐘') >= 0), { eta, lines: S.a.lines.map(l => l.text) })
const low = setup(Tools.energyTrend(R(30, -15), { now: 60, reservePct: 20, vehicleType: 'multirotor' }))
const lowB = Bind.resolve({ component_id: 'W4_DIAG', binding_ref: { ref: ['0:F1', '0:F2'] } }, low.res, null)
const lsoc = lowB.data.cards.find(c => c.key === 'soc'), leta = lowB.data.cards.find(c => c.key === 'eta')
ok('W4 below reserve -> orange', lsoc.value === '15' && lsoc.accent === 'telemetryMetricOrange', lsoc)
ok('W4 eta NA text = claims', leta.value === '無法估計' && leta.accent === 'telemetryMetricOrange' && low.a.lines.some(l => l.text === '無法估計剩餘時間' + leta.unit), { leta, lines: low.a.lines.map(l => l.text) })
const up = setup(Tools.energyTrend(R(50, 5), { now: 60, reservePct: 20, vehicleType: 'multirotor' }))
const upB = Bind.resolve({ component_id: 'W4_DIAG', binding_ref: { ref: ['0:F1'] } }, up.res, null)
ok('W4 rising not orange', upB.ok && upB.data.cards.every(c => c.accent !== 'telemetryMetricOrange'), upB.data)
ok('W4 non-energy rejected', !Bind.resolve({ component_id: 'W4_DIAG', binding_ref: { ref: ['1:F1'] } }, S.res, null).ok)
ok('W4 3 refs rejected', !Bind.resolve({ component_id: 'W4_DIAG', binding_ref: { ref: ['0:F1', '0:F2', '0:F1'] } }, S.res, null).ok)
// W5
const w5 = Bind.resolve(S.node('W5_DOC'), S.res, S.a)
ok('W5 ok verbatim', w5.ok && w5.data.citations[0].text === '返航保留電量的設定方式' && w5.data.citations[0].doc_version === 'v1', w5)
ok('W5 missing chunk', !Bind.resolve({ component_id: 'W5_DOC', binding_ref: { ref: ['zz'] } }, S.res, null).ok)
ok('W5 6 refs rejected', !Bind.resolve({ component_id: 'W5_DOC', binding_ref: { ref: ['k1', 'k1', 'k1', 'k1', 'k1', 'k1'] } }, S.res, null).ok)
ok('unknown component', Bind.resolve({ component_id: 'toString', binding_ref: {} }, S.res, null).error === 'UNKNOWN_COMPONENT')
// fit
const L = n => Array.from({ length: n }, (_, i) => ({ text: 'x' + i, mandatory: i < 2 }))
ok('fitLines fits', JSON.stringify(Bind.fitLines(L(3), 100, 24)) === '{"shown":3,"hidden":0}')
ok('fitLines collapse', JSON.stringify(Bind.fitLines(L(10), 100, 24)) === '{"shown":3,"hidden":7}')
ok('fitLines keeps mandatory', Bind.fitLines(L(10), 10, 24).shown === 2)
ok('fitCount fits', JSON.stringify(Bind.fitCount(3, 100, 25)) === '{"shown":3,"hidden":0}')
ok('fitCount more', JSON.stringify(Bind.fitCount(40, 100, 25)) === '{"shown":3,"hidden":37}')
ok('fitCount zero room', JSON.stringify(Bind.fitCount(2, 0, 25)) === '{"shown":0,"hidden":2}')
// ETA reason map same as claims (every reason has the same sentence)
for (const k of Object.keys(Bind.ETA_NA_REASON)) ok('eta reason ' + k, typeof Bind.ETA_NA_REASON[k] === 'string')
ok('num same', [0.04, -0.04, 1.25, 79, 58.99999].every(x => Bind.num(x) === String(Math.round(x * 10) / 10 === 0 ? 0 : Math.round(x * 10) / 10)))
console.log(log.join('\n')); console.log(`test_bind_v1 (${Bind.BIND_VERSION}): pass ${pass} fail ${fail}`); process.exit(fail ? 1 : 0)
