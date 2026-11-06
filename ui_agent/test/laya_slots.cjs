'use strict';
// Shared slot-tree questions for Laya (inference nodes and fine-tuning rows use the SAME text).
// Byte-identical question wording to laya_nodes.cjs (checked by test_laya_train.cjs).
const S = require('./semantic_scoring'), C = require('./load_core');

const pageOf = p => C.PAGES.filter(x => x.page === p)[0];
const sectionsOf = p => C.SECTIONS.filter(s => s.page === p);
const KIND_OPTS = [['NAV', '換頁或查看某個畫面、設定'], ['LAYOUT', '移動、縮放、隱藏或顯示畫面上的模組'], ['TEXT', '調整全系統文字大小'],
  ['HISTORY', '復原、重做或全部還原介面變更'], ['NONE', '都不是：控制飛機、改參數數值、太模糊或與介面無關']];

function nodeOptions(row, prefix) {
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
// One Laya question, or {fixed: {code: 1}} when the program fills the slot itself.
function question(row, prefix) {
  const node = nodeOptions(row, prefix);
  if (prefix[0] === 'NAV' && prefix.length === 2 && !sectionsOf(+prefix[1].slice(1)).length) return {fixed: {WHOLE: 1}};
  if (node.opts.length === 1) return {fixed: {[node.opts[0][0]]: 1}};
  if (node.opts.length > 20) throw Error('more than 20 options at ' + (row.id || '') + '|' + prefix.join('/'));
  const k = known(prefix);
  return {q: {type: 'choice', instructions: (k.length ? '已知：' + k.join('；') + '。' : '') + '問題：' + node.need + '？',
    criteria: Object.fromEntries(node.opts)}};
}
const stateOf = row => ({'使用者對地面站介面說': row.intent, '目前畫面': C.pageName(row.ctx.page)});

// Gold slot path for a labelled row: SELECT one id -> that candidate's path; HOLD / CLARIFY -> NONE.
function goldPath(row) {
  const e = row.expect;
  if (e.decision !== 'SELECT') return ['NONE'];
  if (e.ids.length !== 1) throw Error('SELECT must have exactly one id');
  const c = S.inventory(row.ctx).filter(x => x.id === e.ids[0])[0];
  if (!c) throw Error('id ' + e.ids[0] + ' is not a candidate in this context');
  if (c.ok === false) throw Error('id ' + e.ids[0] + ' precondition false in this context');
  return c.path;
}

module.exports = {KIND_OPTS, nodeOptions, known, question, stateOf, goldPath, sectionsOf, pageOf};
