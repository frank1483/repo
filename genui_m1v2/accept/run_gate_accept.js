// Gate 驗收：用目前的 m1v2 Gate（不改任何常數）跑驗收清單一次。用法：node run_gate_accept.js gate_accept_v1.jsonl
const fs = require('fs'), path = require('path'), crypto = require('crypto'), { Gate } = require('../test/load.js')
const buf = fs.readFileSync(path.join(__dirname, process.argv[2]))
const rows = buf.toString('utf8').split('\n').filter(Boolean).map(l => JSON.parse(l))
console.log('list sha256 ' + crypto.createHash('sha256').update(buf).digest('hex') + ' policy ' + Gate.POLICY_VERSION + ' lexicon ' + Gate.LEXICON_VERSION)
let ok = 0, cmdLeak = 0, oodLeak = 0, overBlock = 0; const conf = {}, miss = []
for (const r of rows) {
  const g = Gate.gate(r.text), got = g['class']
  if (got === r.expect) ok++
  else miss.push(r.id + '\t' + JSON.stringify(r.text) + '\texpect=' + r.expect + '\tgot=' + got + '\trule=' + g.rule_no + '\tscores=' + JSON.stringify(g.scores))
  if (r.expect === 'FLIGHT_CMD' && got !== 'FLIGHT_CMD') cmdLeak++
  if (r.expect === 'OUT_OF_DOMAIN' && !['OUT_OF_DOMAIN', 'INVALID_INPUT'].includes(got)) oodLeak++
  if (r.expect !== 'FLIGHT_CMD' && got === 'FLIGHT_CMD') overBlock++
  conf[r.expect] = conf[r.expect] || {}; conf[r.expect][got] = (conf[r.expect][got] || 0) + 1
}
console.log(`total ${rows.length} / match ${ok} / mismatch ${miss.length}`)
console.log(`飛控指令漏放 ${cmdLeak} / 領域外被當領域內 ${oodLeak} / 非指令被擋 ${overBlock}`)
for (const e of Object.keys(conf)) console.log(e + '\t' + JSON.stringify(conf[e]))
console.log('--- mismatches'); for (const m of miss) console.log(m)
