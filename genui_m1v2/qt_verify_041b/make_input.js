// 產生 input_data.js（給 Qt）與 input.json（給 node）：校準 160 句＋固定句，vectors v3～v6 的電量、飛行紀錄、手冊案例。
const fs = require('fs'), path = require('path'), G = p => path.join(__dirname, '..', p)
const calib = fs.readFileSync(G('calib/gate_calib_v1.jsonl'), 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l).text)
const extra = ['能不能再次返航', '返航後電量會剩多少', '電量多少再返航', '現在電量多少？立即返航', '現在電量多少\n立即返航', '顯示返航點後立即返航', '為什麼返航', '返航高度設多少', 'ＲＴＬ 返航', 'island 的地圖', '', '電量原因是什麼', '之後電量會剩多少？', '請立即顯示電量']
const inp = { gate: [], energy: [], flightlog: [], manual: [], terms: ['返航保留電量', '馬達 溫度 過高', 'motor', '低電量 返航 設定', '的'] }
inp.gate = [...new Set(calib.concat(extra))]
for (const v of ['v3', 'v4', 'v5', 'v6']) {
  const V = JSON.parse(fs.readFileSync(G(`golden/vectors_${v}.json`), 'utf8')), C = V.cases
  for (const c of C.energy || []) inp.energy.push({ id: v + ':' + c.id, samples: c.samples, opts: c.opts })
  for (const c of C.flightlog || []) inp.flightlog.push({ id: v + ':' + c.id, field: c.field, unit: c.unit, samples: c.samples, t0: c.t0, t1: c.t1, gaps: c.gaps })
  for (const c of C.manual || []) inp.manual.push({ id: v + ':' + c.id, query: c.query, chunks: c.set ? V.chunks.filter(k => k.set === c.set) : V.chunks, glossary: c.use_glossary ? V.glossary : {} })
}
const j = JSON.stringify(inp)
fs.writeFileSync(path.join(__dirname, 'input.json'), j)
fs.writeFileSync(path.join(__dirname, 'input_data.js'), '.pragma library\nvar INPUT = ' + j + '\n')
console.log(`gate ${inp.gate.length}, energy ${inp.energy.length}, flightlog ${inp.flightlog.length}, manual ${inp.manual.length}`)
