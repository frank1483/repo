'use strict';
// Writes the label catalog Codex uses to write training sentences (no held-out sentences inside).
//   node laya_catalog.cjs OUT.json
const fs = require('fs');
const S = require('./semantic_scoring'), C = require('./load_core');
const out = process.argv[2]; if (!out) throw Error('usage: OUT.json');
if (fs.existsSync(out)) throw Error('OUT exists');
const ctxOf = page => ({page, section: -1, canUndo: true, canRedo: true, textScale: 1});
const pages = C.PAGES.map(p => ({page: p.page, name: p.name, aliases: p.aliases || [],
  nav_id: 'NAV_' + p.page,
  sections: C.SECTIONS.filter(s => s.page === p.page).map(s => ({section: s.section, id: 'NAV_' + p.page + '_' + s.section, name: s.name, aliases: s.aliases || []})),
  modules: S.visibleModules(ctxOf(p.page)).map(m => ({module: m.id, name: m.name, aliases: m.aliases || [], locked: !!m.locked,
    actions: S.inventory(ctxOf(p.page)).filter(c => c.kind === 'layout' && c.module === m.id).map(c => ({id: c.id, desc: c.desc}))}))}));
const inv0 = S.inventory(ctxOf(0));
const catalog = {
  version: 'laya-train-catalog-1',
  note: 'Every label id a training row may use. Layout ids exist only on the page that shows the module (ctx.page).',
  pages,
  text_scale: inv0.filter(c => c.kind === 'text_scale').map(c => ({id: c.id, desc: c.desc})),
  history: inv0.filter(c => ['undo', 'redo', 'reset_all'].indexOf(c.kind) >= 0).map(c => ({id: c.id, desc: c.desc,
    precondition: c.kind === 'undo' ? 'ctx.canUndo must be true' : c.kind === 'redo' ? 'ctx.canRedo must be true' : 'none'})),
  decisions: {SELECT: 'exactly one id from this catalog', HOLD: 'not a UI request: flight/gimbal control, parameter values, chit-chat, other apps; ids []',
    CLARIFY: 'a UI request that is too vague to pick one id (which module? which page?); ids []'}
};
fs.writeFileSync(out, JSON.stringify(catalog, null, 1));
console.log(JSON.stringify({pages: pages.length, sections: pages.reduce((a, p) => a + p.sections.length, 0),
  layout_ids: pages.reduce((a, p) => a + p.modules.reduce((b, m) => b + m.actions.length, 0), 0)}));
