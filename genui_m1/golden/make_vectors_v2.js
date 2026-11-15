// G4 對照輸入第二版：只補第一版沒涵蓋到的電量分支（剩餘時間、缺口、亂序過多、上升）。
// 第一版 vectors.json 不動。執行：node genui_m1/golden/make_vectors_v2.js > genui_m1/golden/vectors_v2.json
let seed = 20261116
function rnd() { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
const r3 = x => Math.round(x * 1000) / 1000
const energy = []
function series(n, dt, slope, soc0, noise) { const s = []; for (let k = 0; k < n; ++k) s.push({ t: r3(k * dt), soc: r3(soc0 + slope * (k * dt) / 60 + (rnd() - 0.5) * 2 * noise) }); return s }
function add(id, samples, opts) { energy.push({ id, samples, opts: Object.assign({ reservePct: 20, reserveAssumed: false, checkStale: false, vehicleType: 'multirotor', now: samples.length ? Math.max(...samples.map(s => s.t)) : 0 }, opts || {}) }) }
// 剩餘時間：下降、電量高於保留值，各種斜率與保留值（含 ETA 剛好超過 600 分鐘的邊界附近）
let i = 0
for (const slope of [-6, -3, -1, -0.5, -0.2, -0.1]) for (const soc0 of [95, 60, 30]) for (const reserve of [20, 25, 0])
  add('V2_ETA' + (i++), series(61, 1, slope, soc0, i % 3 === 0 ? 0.02 : 0), { reservePct: reserve, reserveAssumed: i % 2 === 0 })
// 電量低於或等於保留值：不算 ETA
for (const soc0 of [20.5, 20, 15]) add('V2_LOW' + (i++), series(61, 1, -0.3, soc0, 0), { reservePct: 20 })
// 缺口：最大間隔 9.5、10、10.5、11 秒
for (const gap of [9.5, 10, 10.5, 11]) { const s = series(61, 1, -1, 80, 0).filter(p => p.t <= 20 || p.t >= 20 + gap); add('V2_GAP' + (i++), s) }
// 亂序：比例 0.18～0.24 附近
for (const k of [18, 19, 20, 21, 22, 24]) { const s = series(100, 0.6, -1, 80, 0); for (let j = 0; j < k; ++j) { const a = 4 * j + 1; const tmp = s[a]; s[a] = s[a + 1]; s[a + 1] = tmp } add('V2_DIS' + (i++), s) }
// 上升與持平邊界：斜率在死區 0.05 附近
for (const slope of [0.5, 0.2, 0.06, 0.05, 0.04, -0.04, -0.05, -0.06]) add('V2_DIR' + (i++), series(61, 1, slope, 50, 0))
// 覆蓋率與樣本數邊界
for (const [n, dt] of [[10, 5.4], [10, 5.3], [13, 4], [13, 3.9], [9, 7], [11, 6]]) add('V2_SUF' + (i++), series(n, dt, -1, 80, 0))
// 視窗：資料比 60 秒長，前段斜率不同，只有最後 60 秒該被用到
{ const a = series(120, 1, 2, 40, 0), last = a[a.length - 1]; for (let k = 1; k <= 60; ++k) a.push({ t: r3(last.t + k), soc: r3(last.soc - k / 60 * 3) }); add('V2_WIN' + (i++), a) }
process.stdout.write(JSON.stringify({ seed: 20261116, chunks: [], glossary: {}, cases: { energy, telemetry: [], flightlog: [], alerts: [], manual: [] } }))
