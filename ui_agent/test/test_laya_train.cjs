'use strict';
// Tests for the Laya fine-tuning data path. No network, no model.
const fs = require('fs'), os = require('os'), path = require('path'), cp = require('child_process');
const S = require('./semantic_scoring'), C = require('./load_core'), L = require('./laya_slots.cjs');
let n = 0, bad = 0;
const ok = (c, m) => { n++; if (!c) { bad++; console.log('FAIL', m); } };
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'laya-'));
const read = f => fs.readFileSync(path.join(__dirname, f), 'utf8').replace(/\r\n/g, '\n').split('\n').filter(s => s.trim()).map(JSON.parse);
const held = read('sm_heldout_v1.jsonl').concat(read('sm_heldout_v2.jsonl'));

// 1. laya_slots builds byte-identical questions to the frozen laya_nodes.cjs (inference == training wording).
cp.execFileSync('node', [path.join(__dirname, 'laya_nodes.cjs'), path.join(tmp, 'nodes.jsonl')]);
const nodes = fs.readFileSync(path.join(tmp, 'nodes.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
let same = 0;
for (const nd of nodes) {
  const row = held.filter(r => r.id === nd.id)[0];
  const qs = {}, fixed = {};
  for (const key of Object.keys(nd.questions).concat(Object.keys(nd.fixed))) {
    const q = L.question(row, key === '' ? [] : key.split('/'));
    if (q.fixed) fixed[key] = q.fixed; else qs[key] = q.q;
  }
  if (JSON.stringify(qs) === JSON.stringify(nd.questions) && JSON.stringify(fixed) === JSON.stringify(nd.fixed) &&
      JSON.stringify(L.stateOf(row)) === JSON.stringify(nd.state)) same++;
}
ok(same === nodes.length && nodes.length === 85, 'laya_slots matches laya_nodes on all 85 rows (' + same + ')');

// 2. goldPath: every held-out label maps onto the slot tree, and every gold slot is one of its options.
let pathsOk = 0;
for (const r of held.filter(r => !S.fixedStage(r).fixed)) {
  const gp = L.goldPath(r);
  let fine = true;
  for (let k = 0; k < gp.length; ++k) { const q = L.question(r, gp.slice(0, k)); const opts = q.fixed || q.q.criteria; if (!(gp[k] in opts)) fine = false; }
  if (fine) pathsOk++;
}
ok(pathsOk === 85, 'gold paths valid for all scored held-out rows (' + pathsOk + ')');

// 3. Builder: accepts good rows, rejects bad ones and held-out copies, writes laya rows.
const ctx = page => ({page, section: -1, canUndo: true, canRedo: false, textScale: 1});
const rows = [
  {id: 'T1', lang: 'zh', style: 'indirect', intent: '電池快沒電時飛機會怎樣，帶我去看那邊的設定好嗎', ctx: ctx(0), expect: {decision: 'SELECT', ids: ['NAV_3_1']}},
  {id: 'T2', lang: 'en', style: 'direct', intent: 'move the compass to the bottom left please', ctx: ctx(1), expect: {decision: 'SELECT', ids: ['LAY_compass_MOVE_BL']}},
  {id: 'T3', lang: 'mix', style: 'direct', intent: '把 text 調大一點 like 115%', ctx: ctx(0), expect: {decision: 'SELECT', ids: ['SYS_TEXT_SCALE_115']}},
  {id: 'T4', lang: 'zh', style: 'scope', intent: '幫我寫一首詩給女朋友', ctx: ctx(0), expect: {decision: 'HOLD', ids: []}},
  {id: 'T5', lang: 'zh', style: 'vague', intent: '那塊東西弄一下', ctx: ctx(1), expect: {decision: 'CLARIFY', ids: []}},
  {id: 'B1', lang: 'zh', style: 'x', intent: '重做一下剛才的', ctx: ctx(0), expect: {decision: 'SELECT', ids: ['REDO']}},          // canRedo false
  {id: 'B2', lang: 'zh', style: 'x', intent: '指南針移到左下', ctx: ctx(0), expect: {decision: 'SELECT', ids: ['LAY_compass_MOVE_BL']}}, // not on page 0
  {id: 'B3', lang: 'zh', style: 'x', intent: held[0].intent, ctx: ctx(0), expect: held[0].expect},                                  // held-out copy
  {id: 'B4', lang: 'fr', style: 'x', intent: 'bonjour', ctx: ctx(0), expect: {decision: 'HOLD', ids: []}},
  {id: 'B5', lang: 'zh', style: 'x', intent: '電池快沒電時飛機會怎樣，帶我去看那邊的設定好嗎', ctx: ctx(0), expect: {decision: 'SELECT', ids: ['NAV_3_1']}}  // dup of T1
];
const inp = path.join(tmp, 'codex.jsonl');
fs.writeFileSync(inp, rows.map(r => JSON.stringify(r)).join('\n') + '\n');
const outDir = path.join(tmp, 'build');
cp.execFileSync('node', [path.join(__dirname, 'laya_build_train.cjs'), outDir, inp]);
const rep = JSON.parse(fs.readFileSync(path.join(outDir, 'report.json'), 'utf8'));
const tr = fs.readFileSync(path.join(outDir, 'train.jsonl'), 'utf8').trim().split('\n').concat(
  fs.readFileSync(path.join(outDir, 'val.jsonl'), 'utf8').trim().split('\n')).filter(Boolean).map(JSON.parse);
const rej = fs.readFileSync(path.join(outDir, 'rejected.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
ok(rep.kept === 5 && rep.rejected === 5, 'kept 5 / rejected 5 (' + rep.kept + '/' + rep.rejected + ')');
ok(rej.map(x => x.row.id).sort().join() === 'B1,B2,B3,B4,B5', 'rejected exactly the bad rows');
ok(rej.filter(x => x.row.id === 'B3')[0].why.indexOf('held-out') >= 0, 'held-out copy rejected as leak');
const t2 = tr.filter(x => x.id === 'T2')[0];
ok(t2 && JSON.stringify(Object.values(t2.gold).map(g => Object.keys(g.probabilities)[0])) === '["LAYOUT","compass","MOVE_BL"]', 'T2 gold path LAYOUT/compass/MOVE_BL');
const t4 = tr.filter(x => x.id === 'T4')[0];
ok(t4 && Object.keys(t4.questions).length === 1 && t4.gold.slot0.probabilities.NONE === 1, 'HOLD row trains root=NONE only');
const t1 = tr.filter(x => x.id === 'T1')[0];
ok(t1 && t1.questions.slot0.instructions === '問題：這句話要做哪一類事？' && Object.keys(t1.questions).length === 3, 'T1 has root/page/section slots with inference wording');
console.log((bad ? 'FAILED ' : 'ok ') + (n - bad) + '/' + n);
process.exit(bad ? 1 : 0);
