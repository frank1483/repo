// Conformance: the JS engine must reproduce gcs_demo/agent_loop_vectors.json exactly (Python does the same).
const fs = require('fs'), path = require('path'), assert = require('assert')
const {SlotLoop} = require('./load_sm'), specLib = require('./slot_loop_spec_lib')
const V = JSON.parse(fs.readFileSync(path.join(__dirname, '../../gcs_demo/agent_loop_vectors.json'), 'utf8'))
let n = 0
for (const v of V.vectors) {
  const s = SlotLoop.session(specLib.build(v.spec), {version: 'vec-1', systemPrompt: '只填一格', maxCalls: v.config.maxCalls || undefined,
    goal: v.spec.goal, modelEnabled: v.config.modelEnabled === null ? undefined : v.config.modelEnabled})
  let i = 0
  const r = SlotLoop.run(s, () => { const x = v.replies[i++]; if (x === undefined) throw Error('script exhausted'); return x })
  assert.deepStrictEqual({decision: r.decision, model_calls: r.model_calls, trace: r.trace, prompts: r.calls.map(c => c.messages[1].content),
    codes: r.calls.map(c => c.codes), repair_flags: r.calls.map(c => c.repair)}, v.expect, v.name)
  console.log('PASS', v.name); n++
}
console.log('slot loop vectors: ' + n + '/' + V.vectors.length + ' PASS')
