// 產生 PoC 輸入：校準清單 160 句＋v3.1b §A-3' 固定句，與 G4 v3 的全部電量案例。
const fs = require('fs'), path = require('path')
const calib = fs.readFileSync(path.join(__dirname, '../calib/gate_calib_v1.jsonl'), 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l).text)
const extra = ['能不能再次返航', '返航後電量會剩多少', '電量多少再返航', '現在電量多少？立即返航', '現在電量多少\n立即返航', '顯示返航點後立即返航', '為什麼返航', '返航高度設多少', 'ＲＴＬ 返航', 'island 的地圖', '']
const V = JSON.parse(fs.readFileSync(path.join(__dirname, '../golden/vectors_v3.json'), 'utf8'))
process.stdout.write(JSON.stringify({ gate: [...new Set(calib.concat(extra))], energy: V.cases.energy.map(c => ({ id: c.id, samples: c.samples, opts: c.opts })) }))
