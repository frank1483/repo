'use strict';
// Offline unit tests for the state-machine loop (sm-v0). Fake model only; no HTTP, Qt or devices.
const assert = require('assert'), C = require('./load_core'), SM = require('./load_sm');
const A = {page:0, section:-1, canUndo:true, canRedo:true, textScale:1};
const mods = {}; for (const m of C.MODULES.filter(m => m.page === 1)) mods[m.id] = {registered:true, visible:true};
const B = {page:1, section:-1, canUndo:true, canRedo:false, textScale:1, modules:mods};
const script = answers => { let i = 0; const seen = []; const f = call => { seen.push(call); return answers[i++]; }; f.seen = seen; return f; };
const v = x => JSON.stringify({value:x});
let n = 0; function test(name, fn) { fn(); n++; console.log('PASS ' + name); }

test('rule-certain sentence never calls the model', () => {
  const m = script([]); const r = SM.runSync(C, '去告警中心', A, '', m);
  assert.equal(r.decision.decision, 'SELECT'); assert.equal(r.decision.choice_id, 'NAV_4'); assert.equal(m.seen.length, 0); });
test('safety gate holds before any model call', () => {
  const m = script([]); const r = SM.runSync(C, '起飛', B, '', m);
  assert.equal(r.decision.decision, 'HOLD'); assert.equal(m.seen.length, 0); });
test('generic settings stays rule CLARIFY', () => {
  const m = script([]); const r = SM.runSync(C, '去設定', A, '', m);
  assert.equal(r.decision.decision, 'CLARIFY'); assert.equal(m.seen.length, 0); });
test('no-target nav: classify, page, section', () => {
  const m = script([v('NAV'), v('P3'), v('S5')]); const r = SM.runSync(C, '我想看看飛機能飛多高的上限', A, '', m);
  assert.equal(r.decision.choice_id, 'NAV_3_5'); assert.equal(r.model_calls, 3);
  assert.deepEqual(m.seen.map(c => c.state), ['S2_CLASSIFY', 'S3_PAGE', 'S3_SECTION']); });
test('every prompt carries only the current slot enum', () => {
  const m = script([v('NAV'), v('P3'), v('S5')]); SM.runSync(C, '我想看看飛機能飛多高的上限', A, '', m);
  assert.equal(m.seen[0].codes.length, 7); assert.equal(m.seen[1].codes.length, 15); assert.equal(m.seen[2].codes.length, 10);
  for (const c of m.seen) assert.deepEqual(c.schema.properties.value.enum, c.codes); });
test('out of scope holds after one call', () => {
  const m = script([v('OUT_OF_SCOPE')]); const r = SM.runSync(C, '今天午餐吃什麼', A, '', m);
  assert.equal(r.decision.decision, 'HOLD'); assert.equal(m.seen.length, 1); });
test('invalid value is repaired once with the error text', () => {
  const m = script([v('NAVIGATE'), v('OUT_OF_SCOPE')]); const r = SM.runSync(C, '今天午餐吃什麼', A, '', m);
  assert.equal(r.decision.decision, 'HOLD'); assert.equal(m.seen.length, 2);
  assert(m.seen[1].repair); assert(m.seen[1].messages[1].content.includes('上次錯誤')); assert(!m.seen[0].repair); });
test('second invalid answer falls back to the rule, never a third call', () => {
  const m = script(['not json', '{"value":"x","extra":1}', v('NAV')]); const r = SM.runSync(C, '今天午餐吃什麼', A, '', m);
  assert.equal(r.decision.source, 'rule_fallback'); assert.equal(r.decision.decision, 'HOLD'); assert.equal(m.seen.length, 2); });
test('repair is shared by the whole sentence (only one per sentence)', () => {
  const m = script([v('BAD'), v('NAV'), v('BAD'), v('P3')]); const r = SM.runSync(C, '我想看看飛機能飛多高的上限', A, '', m);
  assert.equal(r.decision.source, 'rule_fallback'); assert.equal(m.seen.length, 3); });
test('layout: module then action; locked module offers no HIDE', () => {
  const m = script([v('LAYOUT'), v('attitude'), v('HIDE')]); const r = SM.runSync(C, '今天午餐吃什麼', B, '', m);
  assert(!m.seen[2].codes.includes('HIDE')); assert.notEqual(r.decision.decision, 'SELECT'); });
test('layout move builds the v6 candidate ID and passes the gate', () => {
  const m = script([v('LAYOUT'), v('windGauge'), v('MOVE_TR')]); const r = SM.runSync(C, '今天午餐吃什麼', B, '', m);
  assert.equal(r.decision.choice_id, 'LAY_windGauge_MOVE_TR'); assert.equal(r.decision.candidates[0].region, 'TR'); });
test('module list only holds visible modules of the current page', () => {
  const ctx = JSON.parse(JSON.stringify(B)); ctx.modules.compass.visible = false;
  const m = script([v('LAYOUT'), v('UNKNOWN')]); SM.runSync(C, '今天午餐吃什麼', ctx, '', m);
  assert(!m.seen[1].codes.includes('compass')); assert(!m.seen[1].codes.includes('homeStatus')); });
test('uncertain rule candidates: pick one', () => {
  const m = script([v('LAY_miniView_SCALE_125')]); const r = SM.runSync(C, '左下那個小的地圖弄大一點', B, '', m);
  assert.equal(m.seen[0].state, 'S4_PICK'); assert.equal(r.decision.choice_id, 'LAY_miniView_SCALE_125'); });
test('pick CLARIFY keeps rule candidates for the user', () => {
  const m = script([v('CLARIFY')]); const r = SM.runSync(C, '把那個放大', B, '', m);
  assert.equal(r.decision.decision, 'CLARIFY'); assert(r.decision.candidates.length > 0); });
test('already-on-page nav is a HOLD, not an action', () => {
  const m = script([v('NAV'), v('P0')]); const r = SM.runSync(C, '今天午餐吃什麼', A, '', m);
  assert.equal(r.decision.decision, 'HOLD'); });
test('undo without history is invalid and repaired once', () => {
  const ctx = Object.assign({}, A, {canUndo:false});
  const m = script([v('HISTORY'), v('UNDO'), v('REDO')]); const r = SM.runSync(C, '今天午餐吃什麼', ctx, '', m);
  assert.equal(r.decision.choice_id, 'REDO'); assert(m.seen[2].repair); });
test('transport failure counts as one invalid answer', () => {
  const m = call => { throw new Error('timeout'); }; const r = SM.runSync(C, '今天午餐吃什麼', A, '', m);
  assert.equal(r.decision.source, 'rule_fallback'); assert.equal(r.model_calls, 2); });
test('model disabled = v6 rule decision, zero calls', () => {
  const r = SM.runSync(C, '今天午餐吃什麼', A, '', null, {modelEnabled:false});
  assert.equal(r.decision.decision, 'HOLD'); assert.equal(r.model_calls, 0); });
test('call budget caps a sentence at four model calls', () => {
  const m = script([v('BAD'), v('NAV'), v('P3'), v('S5')]); const r = SM.runSync(C, '我想看看飛機能飛多高的上限', A, '', m);
  assert(r.model_calls <= 4); assert.equal(r.decision.choice_id, 'NAV_3_5'); });
test('prompt carries no earlier model replies (state rebuilt each step)', () => {
  const m = script([v('NAV'), v('P3'), v('S5')]); SM.runSync(C, '我想看看飛機能飛多高的上限', A, '', m);
  assert(!m.seen[2].messages[1].content.includes('"value"') || m.seen[2].messages[1].content.endsWith('{"value":"代碼"}'));
  assert(m.seen[2].messages[1].content.includes('頁面=安全設定')); assert.equal(m.seen[2].messages.length, 2); });
test('v1: OTHER in pick re-enters classification once', () => {
  const m = script([v('OTHER'), v('LAYOUT'), v('windGauge'), v('MOVE_TR')]); const r = SM.runSync(C, '風的那個儀表放到右上', B, '', m);
  assert.deepEqual(m.seen.map(c => c.state), ['S4_PICK', 'S2_CLASSIFY', 'S3_MODULE', 'S3_ACTION']); assert.equal(r.decision.choice_id, 'LAY_windGauge_MOVE_TR'); });
test('v1: AMBIGUOUS classify asks the user', () => {
  const m = script([v('AMBIGUOUS')]); const r = SM.runSync(C, '今天午餐吃什麼', A, '', m); assert.equal(r.decision.decision, 'CLARIFY'); });
test('v1: model errors are recorded on the decision', () => {
  const m = script(['bad', 'bad']); const r = SM.runSync(C, '今天午餐吃什麼', A, '', m); assert.equal(r.decision.model_errors.length, 2); });
console.log('state machine: ' + n + ' cases PASS');
