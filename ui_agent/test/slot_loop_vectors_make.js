// Builds gcs_demo/agent_loop_vectors.json from the JS engine. Expected outputs are frozen once;
// test_slot_loop.js (JS) and gcs_demo/test_agent_loop.py (Python) must both reproduce them exactly.
//   node slot_loop_vectors_make.js OUT.json      (refuses to overwrite)
const fs = require('fs'), path = require('path')
const {SlotLoop} = require('./load_sm')
const specLib = require('./slot_loop_spec_lib')
const PIZZA = {
  goal: '幫我把地圖放大', header: ['句子：幫我把地圖放大'], rule: {decision: 'HOLD', choice_id: '', reason_zh: '規則：不確定'},
  start: {go: 'A', obs: '規則找不到'},
  states: {
    A: {need: '哪一類', allowed: [['NAV', '換頁'], ['LAYOUT', '版面'], ['UNKNOWN', '不知道']],
        on: {NAV: {go: 'B', obs: '分類為 NAV', set: {kind: 'NAV'}}, LAYOUT: {go: 'C', set: {kind: 'LAYOUT'}}, UNKNOWN: {rule: '分類：不知道'}}},
    B: {need: '哪個畫面', allowed: [['P1', '地圖'], ['P2', '設定'], ['UNKNOWN', '不知道']],
        on: {P1: {finish: {decision: 'SELECT', choice_id: 'NAV_1'}, source: 'state_machine', why: 'nav'}, P2: {problem: '已經在設定頁'}, UNKNOWN: {escalate: '請說明要去哪個畫面'}}},
    C: {need: '哪個模組', allowed: [['MAP', '地圖'], ['CAM', '相機']],
        on: {MAP: {go: 'D'}, CAM: {rule: '退回', source: 'state_machine'}}},
    D: {need: '做什麼', allowed: [['UP', '放大'], ['DOWN', '縮小']],
        on: {UP: {finish: {decision: 'SELECT', choice_id: 'LAY_MAP_UP'}, source: 'state_machine', why: 'layout'}, DOWN: {problem: '倍率不允許'}}}
  }
}
const ok = v => JSON.stringify({value: v})
const CASES = [
  ['two_slots_ok', {}, [ok('NAV'), ok('P1')]],
  ['bad_json_then_repair', {}, ['我覺得是換頁', ok('NAV'), ok('P1')]],
  ['repair_twice_falls_back', {}, ['nope', '{"value":"X"}']],
  ['extra_key_invalid', {}, ['{"value":"NAV","why":"x"}', ok('NAV'), ok('P1')]],
  ['non_string_value', {}, ['{"value":3}', ok('UNKNOWN')]],
  ['precondition_problem_then_ok', {}, [ok('NAV'), ok('P2'), ok('P1')]],
  ['precondition_twice', {}, [ok('NAV'), ok('P2'), ok('P2')]],
  ['transport_fail_then_ok', {}, [null, ok('NAV'), ok('P1')]],
  ['transport_fail_twice', {}, [null, null]],
  ['escalate', {}, [ok('NAV'), ok('UNKNOWN')]],
  ['rule_with_source', {}, [ok('LAYOUT'), ok('CAM')]],
  ['call_cap_reached', {maxCalls: 3}, [ok('LAYOUT'), 'bad', ok('MAP'), ok('UP')]],
  ['cap_after_chain', {maxCalls: 2}, [ok('LAYOUT'), ok('MAP'), ok('UP')]],
  ['model_disabled', {modelEnabled: false}, []],
  ['begin_finishes', {spec: {start: {finish: {decision: 'HOLD', choice_id: '', reason_zh: '安全閘'}, source: 'rule', why: '安全閘擋下'}}}, []],
  ['json_in_prose', {}, ['好的 {"value":"NAV"} 謝謝', ok('P1')]]
]
const out = process.argv[2]; if (!out) throw Error('usage: OUT.json')
if (fs.existsSync(out)) throw Error('exists; vectors are frozen')
const vectors = CASES.map(([name, o, replies]) => {
  const spec = Object.assign({}, PIZZA, o.spec || {})
  const s = SlotLoop.session(specLib.build(spec), {version: 'vec-1', systemPrompt: '只填一格', maxCalls: o.maxCalls, goal: spec.goal, modelEnabled: o.modelEnabled})
  let i = 0
  const r = SlotLoop.run(s, () => { const x = replies[i++]; if (x === undefined) throw Error('script exhausted'); return x })
  return {name, spec, config: {maxCalls: o.maxCalls || null, modelEnabled: o.modelEnabled === undefined ? null : o.modelEnabled},
    replies, expect: {decision: r.decision, model_calls: r.model_calls, trace: r.trace, prompts: r.calls.map(c => c.messages[1].content),
    codes: r.calls.map(c => c.codes), repair_flags: r.calls.map(c => c.repair)}}
})
fs.writeFileSync(out, JSON.stringify({engine: SlotLoop.ENGINE_VERSION, note: 'frozen expected outputs; do not regenerate in place', vectors}, null, 1) + '\n')
console.log('wrote', vectors.length, 'vectors')
