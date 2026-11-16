// 校準 A1：用 m1v2 的 Gate，對同一份校準句子清單掃 T ∈ {1,2,3}、M ∈ {1,2}。只改這兩個常數，其他照原檔。
// 這是校準資料，不能當驗收證據。用法：node sweep_gate_TM.js gate_calib_v1.jsonl
const fs = require('fs'), path = require('path')
const src = fs.readFileSync(path.join(__dirname, '../qml/GenuiGate.js'), 'utf8').replace(/^\.pragma library/m, '')
const rows = fs.readFileSync(path.join(__dirname, process.argv[2]), 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l))
const SAFE = ['FLIGHT_CMD', 'OUT_OF_DOMAIN']
for (const T of [1, 2, 3]) for (const M of [1, 2]) {
  const s = src.replace(/var T_SCORE = \d+/, 'var T_SCORE = ' + T).replace(/var M_MARGIN = \d+/, 'var M_MARGIN = ' + M)
  const G = new Function(s + '\nreturn { gate, POLICY_VERSION, LEXICON_VERSION }')()
  let ok = 0, unsafe = 0, wrongDirect = 0, askOne = 0, ask = 0; const miss = []
  for (const r of rows) {
    const g = G.gate(r.text), got = g['class']
    if (got === r.expect) { ok++; continue }
    if (SAFE.includes(r.expect) && !SAFE.includes(got) || (r.expect !== 'FLIGHT_CMD' && got === 'FLIGHT_CMD' && false)) unsafe++
    if (got === 'CLARIFY_ONE') askOne++; else if (got === 'CLARIFY') ask++; else wrongDirect++
    miss.push(r.id + '\t' + JSON.stringify(r.text) + '\texpect=' + r.expect + '\tgot=' + got + '\trule=' + g.rule_no + '\tscores=' + JSON.stringify(g.scores))
  }
  console.log(`=== T=${T} M=${M} policy ${G.POLICY_VERSION} lexicon ${G.LEXICON_VERSION}`)
  console.log(`total ${rows.length} / match ${ok} / mismatch ${miss.length} (CLARIFY_ONE ${askOne}, CLARIFY ${ask}, 直接歸錯類 ${wrongDirect}, 安全類別漏掉 ${unsafe})`)
  for (const m of miss) console.log('  ' + m)
}
