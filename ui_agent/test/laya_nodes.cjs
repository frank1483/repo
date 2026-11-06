'use strict';
// Laya part of the semantic-scoring experiment (user OK 2026-11-06 23:11 TW): write every slot-tree
// question for the 85 scored held-out rows to a JSONL file. No network, no model.
//   node laya_nodes.cjs OUT_FILE
// Same slots and option texts as live_semantic.cjs (logprob part), but EVERY node is listed (Laya is
// cheap), so the analysis can score the full tree and also re-apply the logprob part's pruning rule.
// One line per row: {id, state, questions: {nodeKey: {type:'choice', instructions, criteria}}, fixed: {nodeKey: {code: 1}}}
const fs = require('fs');
const S = require('./semantic_scoring'), C = require('./load_core');
const out = process.argv[2]; if (!out) throw Error('usage: OUT_FILE');
if (fs.existsSync(out)) throw Error('OUT_FILE exists');
const read = f => fs.readFileSync(require('path').join(__dirname, f), 'utf8').replace(/\r\n/g, '\n').split('\n').filter(s => s.trim()).map(JSON.parse);
const rows = read('sm_heldout_v1.jsonl').concat(read('sm_heldout_v2.jsonl')).filter(r => !S.fixedStage(r).fixed);

const pageOf = p => C.PAGES.filter(x => x.page === p)[0];
const sectionsOf = p => C.SECTIONS.filter(s => s.page === p);
const KIND_OPTS = [['NAV', '換頁或查看某個畫面、設定'], ['LAYOUT', '移動、縮放、隱藏或顯示畫面上的模組'], ['TEXT', '調整全系統文字大小'],
  ['HISTORY', '復原、重做或全部還原介面變更'], ['NONE', '都不是：控制飛機、改參數數值、太模糊或與介面無關']];
function nodeOptions(row, prefix) {  // identical to live_semantic.cjs nodeOptions
  const inv = S.inventory(row.ctx);
  if (prefix.length === 0) return {need: '這句話要做哪一類事', opts: KIND_OPTS};
  const k = prefix[0];
  if (k === 'NAV' && prefix.length === 1) return {need: '要去的畫面', opts: C.PAGES.map(p => ['P' + p.page, p.name])};
  if (k === 'NAV' && prefix.length === 2) { const p = +prefix[1].slice(1);
    return {need: '「' + pageOf(p).name + '」裡的哪個子頁', opts: [['WHOLE', '整個畫面，不指定子頁']].concat(sectionsOf(p).map(s => ['S' + s.section, s.name]))}; }
  if (k === 'LAYOUT' && prefix.length === 1) return {need: '要調整的模組', opts: S.visibleModules(row.ctx).map(m => [m.id, m.name])};
  if (k === 'LAYOUT' && prefix.length === 2) return {need: '要怎麼調整', opts: inv.filter(c => c.kind === 'layout' && c.module === prefix[1])
    .map(c => [c.path[2], c.desc.replace(/（.*）$/, '')])};
  if (k === 'TEXT') return {need: '全系統文字比例', opts: inv.filter(c => c.kind === 'text_scale').map(c => [c.path[1], c.desc])};
  if (k === 'HISTORY') return {need: '要復原還是重做', opts: [['UNDO', '復原上一步'], ['REDO', '重做剛剛復原的變更'], ['RESET_ALL', '全部回到 agent 介入前']]};
  return null;
}
function known(prefix) {
  const k = [];
  if (prefix[0]) k.push('類別=' + prefix[0]);
  if (prefix[0] === 'NAV' && prefix[1]) k.push('畫面=' + pageOf(+prefix[1].slice(1)).name);
  if (prefix[0] === 'LAYOUT' && prefix[1]) k.push('模組=' + C.MODULES.filter(m => m.id === prefix[1])[0].name);
  return k;
}
const lines = [];
for (const row of rows) {
  const prefixes = [[], ['NAV'], ['TEXT'], ['HISTORY']];
  for (const p of C.PAGES) prefixes.push(['NAV', 'P' + p.page]);
  if (S.visibleModules(row.ctx).length) { prefixes.push(['LAYOUT']); for (const m of S.visibleModules(row.ctx)) prefixes.push(['LAYOUT', m.id]); }
  const questions = {}, fixed = {};
  for (const prefix of prefixes) {
    const key = prefix.join('/'), node = nodeOptions(row, prefix);
    if (prefix[0] === 'NAV' && prefix.length === 2 && !sectionsOf(+prefix[1].slice(1)).length) { fixed[key] = {WHOLE: 1}; continue; }
    if (node.opts.length === 1) { fixed[key] = {[node.opts[0][0]]: 1}; continue; }
    if (node.opts.length > 20) throw Error('more than 20 options at ' + row.id + '|' + key);
    const k = known(prefix);
    questions[key] = {type: 'choice', instructions: (k.length ? '已知：' + k.join('；') + '。' : '') + '問題：' + node.need + '？',
      criteria: Object.fromEntries(node.opts)};
  }
  lines.push(JSON.stringify({id: row.id, state: {'使用者對地面站介面說': row.intent, '目前畫面': C.pageName(row.ctx.page)}, questions, fixed}));
}
fs.writeFileSync(out, lines.join('\n') + '\n');
const sha = require('crypto').createHash('sha256').update(fs.readFileSync(out)).digest('hex');
console.log(JSON.stringify({rows: rows.length, questions: lines.reduce((a, l) => a + Object.keys(JSON.parse(l).questions).length, 0), sha256: sha}));
