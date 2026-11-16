// 校準 A2：用 x500 SITL 紀錄（抽出檔 x500_soc_v1.csv，sha256 330d59de…c273）逐秒重放 T_ENERGY。
// 資料不放進 repo（使用者資料不對外傳送），只放 /mnt/project-files。用法：node a2_replay.js <csv> <reservePct>
// 每一秒 now，送入 t ≤ now 的全部樣本（照到達順序），記狀態、斜率、R²、方向、ETA、原因。
const fs = require('fs'), crypto = require('crypto'), { Tools } = require('../test/load.js')
const buf = fs.readFileSync(process.argv[2]), reserve = Number(process.argv[3] || 20)
const rows = buf.toString('utf8').trim().split('\n').slice(1).map(l => { const [row, t, soc, v] = l.split(','); return { row: +row, t: +t, soc: +soc, v: +v } })
console.log('input sha256 ' + crypto.createHash('sha256').update(buf).digest('hex') + ' rows ' + rows.length + ' reserve ' + reserve + ' tools ' + Tools.TOOLS_VERSION)
console.log('now\tstatus\treason\tn\tslope\tr2\tdir\teta\teta_reason')
const tMax = Math.floor(rows[rows.length - 1].t)
const tally = {}
for (let now = 0; now <= tMax; ++now) {
  const s = rows.filter(r => r.t <= now).map(r => ({ t: r.t, soc: r.soc }))
  const d = Tools.energyTrend(s, { now, reservePct: reserve, vehicleType: 'multirotor', checkStale: true })
  const x = d.detail, f = v => v === null || v === undefined ? '' : (typeof v === 'number' ? v.toFixed(4) : v)
  console.log([now, d.status, x.reason, x.n_valid, f(x.slope_pct_per_min), f(x.r2), f(x.direction), f(x.eta_min), x.eta_reason].join('\t'))
  const seg = now <= 678 ? 'discharge' : (now <= 690 ? 'reset' : 'after')
  const k = seg + ':' + d.status + ':' + (x.direction || x.reason); tally[k] = (tally[k] || 0) + 1
}
console.log('--- tally'); for (const k of Object.keys(tally).sort()) console.log(k + '\t' + tally[k])
