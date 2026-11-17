// ADR-0002 D-13：QML preGate 對共用向量 gate_l1_vectors_v1.json。只跑規則，不開 HTTP、Qt 或裝置。
const fs = require('fs'), path = require('path'), C = require('./load_core')
const v = JSON.parse(fs.readFileSync(path.join(__dirname, '../../gcs_demo/gate_l1_vectors_v1.json'), 'utf8'))
let fail = 0
for (const c of v.cases) {
    const r = C.preGate(c.text)
    const hold = !!(r && r.safety_hold)
    const ok = hold === c.hold
    if (!ok) fail++
    console.log(`${ok ? 'PASS' : 'FAIL'} ${c.id} ${c.group} hold=${hold} expect=${c.hold} ${c.text}`)
}
console.log(`total ${v.cases.length} fail ${fail}`)
process.exit(fail ? 1 : 0)
