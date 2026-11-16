// G4 第 3 版向量：Codex run2b §4-1、4-2、4-3、4-6 的確切輸入，加上由條文手算的預期值（expect）。
// 預期值寫在這裡、先於任何實作輸出提交；check_expect.py 讓 JS 與 Python 各自和它比，不互相當標準答案。
// 執行：node genui_m1v2/golden/make_vectors_v3.js > genui_m1v2/golden/vectors_v3.json
const R = (a, b) => Array.from({ length: 61 }, (_, t) => ({ t, soc: a + b * t / 60 }))
const O = (x) => Object.assign({ now: 60, reservePct: 20, vehicleType: 'multirotor' }, x || {})
const without = (s, lo, hi) => s.filter(p => p.t < lo || p.t > hi)
const energy = [], E = (id, samples, opts, expect) => energy.push({ id, samples, opts, expect })

const e01 = { status: 'OK', detail: { slope_pct_per_min: -1, r2: 1, direction: '下降', eta_min: 59, eta_reason: '', reserve_valid: true, reserve_invalid: false, n_valid: 61, disorder_ratio: 0 }, requested: [0, 60], covered: [0, 60] }
E('E01', R(80, -1), O(), e01)
E('E02', R(80, -1), O({ reserveAssumed: true }), { status: 'OK', detail: { eta_min: 59, reserve_assumed: true } })
E('E03', R(80, -1), O({ reservePct: 100 }), { status: 'OK', detail: { slope_pct_per_min: -1, direction: '下降', reserve_valid: true, reserve_invalid: false, eta_min: null, eta_reason: 'at_or_below_reserve' } })
E('E04', R(80, -1), O({ reservePct: 0 }), { status: 'OK', detail: { reserve_valid: true, eta_min: 79 } })
for (const [k, v] of [['a', -1], ['b', 100.1], ['c', null]]) {
  E('E05' + k, R(80, -1), O({ reservePct: v }), { status: 'OK', detail: { slope_pct_per_min: -1, direction: '下降', reserve_invalid: true, eta_min: null, eta_reason: 'reserve_invalid' } })
  E('E06' + k, R(80, 0), O({ reservePct: v }), { status: 'OK', detail: { slope_pct_per_min: 0, direction: '持平', r2: null, reserve_invalid: true, eta_min: null, eta_reason: 'not_falling' } })
}
E('E08', without(R(80, -1), 21, 30), O(), { status: 'INSUFFICIENT', detail: { reason: 'gap', insufficient_reason: 'gap', n_valid: 51, eta_min: null } })
E('E09', without(R(80, -1), 21, 29), O(), { status: 'OK', detail: { slope_pct_per_min: -1, direction: '下降', eta_min: 59, n_valid: 52 } })
E('E10', R(50, 0.5), O(), { status: 'OK', detail: { slope_pct_per_min: 0.5, r2: 1, direction: '上升', eta_min: null, eta_reason: 'not_falling' } })
const e11 = R(80, -1); e11[60] = { t: 60, soc: 78 }; e11.push({ t: 60, soc: 79 })
E('E11', e11, O(), { status: 'OK', detail: { n_valid: 61, slope_pct_per_min: -1, r2: 1, eta_min: 59, disorder_ratio: 0 } })
E('E12_W30_ignored', R(80, -1), O({ W: 30 }), e01)
E('E12_Wneg_ignored', R(80, -1), O({ W: -1 }), e01)
const eta600 = Array.from({ length: 17 }, (_, i) => ({ t: 3.75 * i, soc: 57.5625 - i / 256 }))
E('E13_eta600', eta600, O(), { status: 'OK', detail: { slope_pct_per_min: -0.0625, direction: '下降', eta_min: 600, n_valid: 17 } })
E('E13_eta601', eta600.map(p => ({ t: p.t, soc: p.soc + 0.0625 })), O(), { status: 'OK', detail: { slope_pct_per_min: -0.0625, eta_min: null, eta_reason: 'over_limit' } })
E('E14_stale_and_few', [{ t: 0, soc: 80 }], { now: 10, checkStale: true, reservePct: 20 }, { status: 'STALE', detail: { stale: true, insufficient_reason: 'n_valid', reason: 'stale' } })
E('E15_same_t', Array.from({ length: 20 }, () => ({ t: 0, soc: 80 })), O({ now: 0 }), { status: 'INSUFFICIENT', detail: { reason: 'n_valid', n_valid: 1 } })
E('E16_flat_boundary', R(80, -0.05), O(), { status: 'OK', detail: { direction: '持平', eta_min: null, eta_reason: 'not_falling' } })
E('E17_just_falling', R(80, -0.0501), O(), { status: 'OK', detail: { direction: '下降', eta_min: null, eta_reason: 'over_limit' } })
E('E18_noise', R(80, -1).map(p => ({ t: p.t, soc: p.soc + 0.3 * Math.sin(p.t * 1.7) })), O(), { status: 'OK', detail: { direction: '下降' } })

// 亂序（§4-2）
const B = Array.from({ length: 100 }, (_, t) => ({ t, soc: 80 - t / 60 }))
const S = k => { const a = B.map(p => ({ ...p })); for (let j = 0; j < k; ++j) { const x = a[4 * j + 1]; a[4 * j + 1] = a[4 * j + 2]; a[4 * j + 2] = x } return a }
const oo = O({ now: 99 })
E('O01', S(20), oo, { status: 'OK', detail: { disorder_ratio: 0.2, n_valid: 61 } })
E('O02', S(21), oo, { status: 'INSUFFICIENT', detail: { disorder_ratio: 0.21, reason: 'disorder' } })
E('O03', S(20).concat([{ t: 101, soc: 50 }]), oo, { status: 'OK', detail: { disorder_ratio: 0.2, n_dropped: 1 } })
E('O04', S(20).concat([{ t: 50, soc: 80 - 50 / 60 }]), oo, { status: 'INSUFFICIENT', detail: { disorder_ratio: 21 / 101, reason: 'disorder' } })
E('O05', S(20).concat([{ t: 99, soc: 80 - 99 / 60 }]), oo, { status: 'OK', detail: { disorder_ratio: 20 / 101, n_valid: 61 } })
E('O06', Array.from({ length: 20 }, (_, i) => ({ t: -981 - i, soc: 80 })).concat(R(80, -1)), O(), { status: 'INSUFFICIENT', detail: { disorder_ratio: 19 / 81, reason: 'disorder' } })

// 飛行紀錄同時戳（§4-6）
const fl = [{ t: 0, value: 0 }, { t: 0, value: 10 }].concat(Array.from({ length: 299 }, (_, i) => ({ t: i + 1, value: 5 })))
const flightlog = [{ id: 'FL01_same_t', field: 'alt', unit: 'm', samples: fl, t0: 0, t1: 299, gaps: [],
  expect: { status: 'OK', points_head: [[0, 0], [0, 10]], facts: { 'alt.min': 0, 'alt.max': 10, 'alt.mean': (10 + 5 * 299) / 301 } } }]

// 手冊去重（§4-6）：c01 重複、c02 與 c01 同文件同文字
const chunks = [{ chunk_id: 'c01', doc: 'D1', heading: 'h', version: 'v1', text: 'battery' }, { chunk_id: 'c01', doc: 'D1', heading: 'h', version: 'v1', text: 'battery' },
                { chunk_id: 'c02', doc: 'D1', heading: 'h', version: 'v1', text: 'battery' }, { chunk_id: 'c03', doc: 'D2', heading: 'h', version: 'v1', text: 'battery' }]
const manual = [{ id: 'M01_dedup', query: 'battery', use_glossary: false, expect: { status: 'OK', hit_ids: ['c01', 'c03'] } }]

process.stdout.write(JSON.stringify({ version: 'g4-v3', note: 'Codex run2b §4 的確切輸入；expect 由條文手算', chunks, glossary: {},
  cases: { energy, telemetry: [], flightlog, alerts: [], manual } }, null, 1))
