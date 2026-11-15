// 產生 G4 對照用的固定輸入（決定性亂數，種子固定）。輸出 vectors.json。
// 執行：node genui_m1/golden/make_vectors.js > genui_m1/golden/vectors.json
let seed = 20261115
function rnd() { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
const r3 = x => Math.round(x * 1000) / 1000
const cases = { energy: [], telemetry: [], flightlog: [], alerts: [], manual: [] }

// 電量：60 案。斜率、雜訊、樣本數、間隔、亂序、壞值、重複時間戳、保留值各種組合
for (let i = 0; i < 60; ++i) {
  const n = [5, 9, 10, 11, 30, 61, 120][i % 7], dt = [0.5, 1, 2, 5, 6.5, 11][i % 6]
  const slope = [-3, -1, -0.2, -0.05, 0, 0.04, 0.5][(i * 3) % 7], noise = [0, 0, 0.05, 0.5, 3][(i * 5) % 5], soc0 = [80, 55, 22, 15][i % 4]
  const s = []
  for (let k = 0; k < n; ++k) s.push({ t: r3(k * dt), soc: r3(soc0 + slope * (k * dt) / 60 + (rnd() - 0.5) * 2 * noise) })
  const swaps = Math.floor(n * [0, 0, 0.05, 0.1, 0.15][i % 5])
  for (let k = 0; k < swaps; ++k) { const j = 1 + Math.floor(rnd() * (n - 2)); const tmp = s[j]; s[j] = s[j + 1]; s[j + 1] = tmp }
  if (i % 8 === 3) s.push({ t: null, soc: 50 }, { t: r3(n * dt + 500), soc: 40 }, { t: r3(dt), soc: 140 }, { t: r3(dt * 2), soc: -1 })
  if (i % 9 === 4) s.push({ t: s[s.length - 1].t, soc: r3(s[s.length - 1].soc - 0.5) })
  const lastT = r3((n - 1) * dt)
  cases.energy.push({ id: 'E' + i, samples: s, opts: { now: i % 4 === 1 ? r3(lastT + 3) : lastT, reservePct: [20, 20, 25, null, 100, -5][i % 6],
    reserveAssumed: i % 2 === 0, checkStale: i % 4 === 1 && i % 8 === 1, vehicleType: i % 13 === 7 ? 'fixedwing' : 'multirotor' } })
}
cases.energy.push({ id: 'E_null', samples: null, opts: { reservePct: 20 } }, { id: 'E_empty', samples: [], opts: { reservePct: 20 } })

// 遙測：20 案
for (let i = 0; i < 20; ++i) {
  const n = i % 5 === 0 ? 0 : 1 + Math.floor(rnd() * 8), s = []
  for (let k = 0; k < n; ++k) s.push({ t: r3(rnd() * 20), value: i % 7 === 3 && k === 0 ? null : r3(rnd() * 100) })
  cases.telemetry.push({ id: 'T' + i, field: 'alt', unit: 'm', samples: i === 19 ? null : s, now: r3(15 + rnd() * 10) })
}
// 飛行紀錄：12 案
for (let i = 0; i < 12; ++i) {
  const n = [0, 1, 50, 300, 301, 1000][i % 6], s = []
  for (let k = 0; k < n; ++k) s.push({ t: k, value: r3(Math.sin(k / 17) * 30 + rnd() * 5) })
  cases.flightlog.push({ id: 'L' + i, field: 'alt', unit: 'm', samples: s, t0: i % 2 ? 10 : 0, t1: i % 2 ? 400 : 2000, gaps: i % 4 === 3 ? [{ t0: 20, t1: 30 }] : [] })
}
// 告警：16 案
const levels = ['info', 'warning', 'critical'], preds = ['P1', 'P2', 'P4']
for (let i = 0; i < 16; ++i) {
  const n = i % 4 === 0 ? 0 : Math.floor(rnd() * 12), ev = []
  for (let k = 0; k < n; ++k) ev.push({ t: r3(rnd() * 100), level: levels[Math.floor(rnd() * 3)], predictor: preds[Math.floor(rnd() * 3)], text: 'e' + k })
  cases.alerts.push({ id: 'A' + i, events: i === 15 ? null : ev, filter: { t0: i % 3 ? 20 : 0, t1: 80, level: i % 5 === 2 ? 'critical' : null, predictor: i % 6 === 4 ? 'P1' : null }, gaps: i % 7 === 5 ? [{ t0: 30, t1: 35 }] : [] })
}
// 手冊：固定語料＋10 個查詢
const chunks = [
  ['c01', 'Return mode causes the vehicle to fly a clear path to a safe location. RTL_RETURN_ALT sets the return altitude.'],
  ['c02', 'The Fly View is used to command and monitor the vehicle when flying.'],
  ['c03', 'Battery failsafe triggers when the battery level falls below the low threshold BAT_LOW_THR.'],
  ['c04', 'Geofence failsafe can be configured to return or land when the vehicle breaches the fence.'],
  ['c05', 'The Plan View is used to plan autonomous missions and upload them to the vehicle.'],
  ['c06', 'Battery estimation uses voltage and current to compute the remaining capacity of the battery.'],
  ['c07', 'Parameters can be changed in the Vehicle Setup view under the Parameters section.'],
  ['c08', 'Land mode causes the vehicle to land at the current position.'],
  ['c09', '返航高度由參數 RTL_RETURN_ALT 設定，預設為 60 公尺。'],
  ['c10', 'battery battery battery level level threshold']
].map(([id, text], i) => ({ chunk_id: id, doc: i % 2 ? 'QGC' : 'PX4', heading: 'H' + i, version: 'v', text }))
const glossary = { '返航': ['return', 'rtl'], '高度': ['altitude'], '電池': ['battery'], '電量': ['battery', 'level'], '降落': ['land'], '參數': ['parameters'], '圍欄': ['geofence'] }
for (const q of ['返航高度怎麼設定', 'battery low threshold', '電池電量', '降落', '圍欄', '參數在哪裡改', 'zzz qqq', '', 'RTL_RETURN_ALT', 'plan mission upload'])
  cases.manual.push({ id: 'M' + cases.manual.length, query: q, use_glossary: cases.manual.length % 3 !== 1 })
process.stdout.write(JSON.stringify({ seed: 20261115, chunks, glossary, cases }))
