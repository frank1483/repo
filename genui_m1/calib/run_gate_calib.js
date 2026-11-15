// 用目前的 Gate 跑校準句子清單，輸出每句結果與混淆表。用法：node run_gate_calib.js gate_calib_v1.jsonl
const fs = require('fs'), path = require('path'), { Gate } = require('../test/load.js')
const rows = fs.readFileSync(path.join(__dirname, process.argv[2]), 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l))
let ok = 0; const conf = {}, miss = []
for (const r of rows) {
  const g = Gate.gate(r.text), got = g['class']
  if (got === r.expect) ok++; else miss.push(r.id + '\t' + JSON.stringify(r.text) + '\texpect=' + r.expect + '\tgot=' + got + '\trule=' + g.rule_no + '\tscores=' + JSON.stringify(g.scores) + (g.clarify.length ? '\tclarify=' + g.clarify.join('/') : ''))
  conf[r.expect] = conf[r.expect] || {}; conf[r.expect][got] = (conf[r.expect][got] || 0) + 1
}
console.log('policy ' + Gate.POLICY_VERSION + ' lexicon ' + Gate.LEXICON_VERSION)
console.log('total ' + rows.length + ' / match ' + ok + ' / mismatch ' + miss.length)
for (const e of Object.keys(conf)) console.log(e + '\t' + JSON.stringify(conf[e]))
console.log('--- mismatches'); for (const m of miss) console.log(m)
