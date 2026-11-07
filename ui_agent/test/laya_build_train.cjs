'use strict';
// Turns Codex's synthetic sentences into Laya fine-tuning files. No network, no model.
//   node laya_build_train.cjs OUT_DIR codex_file1.jsonl[,codex_file2.jsonl...]
// Input row (one per line): {id, lang:"zh"|"en"|"mix", style, template_group?, split?:"train"|"valid", named?, intent, ctx:{page,section,canUndo,canRedo,textScale}, expect:{decision, ids}}
// Output OUT_DIR/:
//   train.jsonl, val.jsonl   {state, questions, gold} rows for laya.train.finetune (one row per sentence,
//                            questions = the gold path's slots only, same wording as inference)
//   rejected.jsonl           every dropped row with the reason
//   report.json              counts by lang / decision / kind / page, leak check, sha256 of every file
// Checks: schema, id valid in ctx, preconditions, exact and near duplicates (char-bigram Jaccard >= 0.8)
// inside the batch, and the same against BOTH held-out files (sm_heldout_v1 dev, sm_heldout_v2 test).
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const S = require('./semantic_scoring'), C = require('./load_core'), L = require('./laya_slots.cjs');
const [out, list, lexPath] = process.argv.slice(2);
if (!out || !list) throw Error('usage: OUT_DIR codex1.jsonl[,codex2.jsonl] [lexicon_v2.json]');
if (fs.existsSync(out)) throw Error('OUT_DIR exists; one build per new directory');
fs.mkdirSync(out, {recursive: true});
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const readJsonl = f => fs.readFileSync(f, 'utf8').replace(/\r\n/g, '\n').split('\n').filter(s => s.trim());
const VAL_FRAC = 0.1, NEAR = 0.8;

const norm = s => String(s).toLowerCase().replace(/[\s，。、！？!?,.;；:："'「」『』（）()…~～-]+/g, '');
const bigrams = s => { const t = norm(s), o = new Set(); for (let i = 0; i + 1 < t.length; ++i) o.add(t.substr(i, 2)); if (t.length === 1) o.add(t); return o; };
const jac = (a, b) => { let i = 0; for (const x of a) if (b.has(x)) i++; return i / (a.size + b.size - i || 1); };
const held = ['sm_heldout_v1.jsonl', 'sm_heldout_v2.jsonl'].flatMap(f => readJsonl(path.join(__dirname, f)).map(JSON.parse))
  .map(r => ({id: r.id, n: norm(r.intent), b: bigrams(r.intent)}));

const rejected = [], kept = [], seen = new Map();
const reject = (raw, why) => rejected.push({why, row: raw});
for (const f of list.split(',')) {
  readJsonl(f).forEach((line, i) => {
    let r; try { r = JSON.parse(line); } catch (e) { return reject(line, 'bad json at ' + path.basename(f) + ':' + (i + 1)); }
    const c = r.ctx || {};
    if (typeof r.id !== 'string' || typeof r.intent !== 'string' || !r.intent.trim()) return reject(r, 'missing id/intent');
    if (['zh', 'en', 'mix'].indexOf(r.lang) < 0) return reject(r, 'lang must be zh|en|mix');
    if (!Number.isInteger(c.page) || !C.PAGES.some(p => p.page === c.page)) return reject(r, 'bad ctx.page');
    if (!Number.isInteger(c.section)) return reject(r, 'bad ctx.section');
    if (typeof c.canUndo !== 'boolean' || typeof c.canRedo !== 'boolean') return reject(r, 'ctx.canUndo/canRedo must be boolean');
    if (!r.expect || ['SELECT', 'HOLD', 'CLARIFY'].indexOf(r.expect.decision) < 0 || !Array.isArray(r.expect.ids)) return reject(r, 'bad expect');
    if (r.expect.decision !== 'SELECT' && r.expect.ids.length) return reject(r, 'HOLD/CLARIFY must have ids []');
    if (r.intent.length > 120) return reject(r, 'intent longer than 120 chars');
    let gp; try { gp = L.goldPath(r); } catch (e) { return reject(r, String(e.message)); }
    if (S.fixedStage(r).fixed) return reject(r, 'caught by the fixed safety stage (preGate); not a scoring example');
    const n = norm(r.intent), b = bigrams(r.intent);
    if (seen.has(n)) return reject(r, 'exact duplicate of ' + seen.get(n));
    const h = held.filter(x => x.n === n || jac(b, x.b) >= NEAR)[0];
    if (h) return reject(r, 'too close to held-out ' + h.id);
    seen.set(n, r.id);
    kept.push({r, gp, b});
  });
}
// Near duplicates inside the batch (keep the first). O(n^2) on bigram sets; fine for 10k.
const nearDrop = new Set();
for (let i = 0; i < kept.length; ++i) { if (nearDrop.has(i)) continue;
  for (let j = i + 1; j < kept.length; ++j) if (!nearDrop.has(j) && kept[i].r.lang === kept[j].r.lang && jac(kept[i].b, kept[j].b) >= 0.95 &&
    JSON.stringify(kept[i].r.expect) === JSON.stringify(kept[j].r.expect)) { nearDrop.add(j); reject(kept[j].r, 'near duplicate of ' + kept[i].r.id); } }
const rows = kept.filter((_, i) => !nearDrop.has(i));

function lavaRow(x) {
  const questions = {}, gold = {};
  for (let k = 0; k < x.gp.length; ++k) {
    const q = L.question(x.r, x.gp.slice(0, k));
    if (q.fixed) continue;
    const key = 'slot' + k;
    if (!(x.gp[k] in q.q.criteria)) throw Error('gold ' + x.gp[k] + ' not an option at ' + x.r.id);
    questions[key] = q.q; gold[key] = {probabilities: {[x.gp[k]]: 1}};
  }
  return {id: x.r.id, lang: x.r.lang, state: L.stateOf(x.r), questions, gold};
}
// Deterministic split: by template_group when Codex gives one (a template never sits on both sides),
// otherwise by id. Hash-based, so it does not depend on file order.
const groupOf = new Map(rows.map(x => [x.r.id, x.r.template_group ? 'g|' + x.r.template_group : 'id|' + x.r.id]));
// A row's own split ("train" | "valid", v2 data) wins over the hash, so valid-only descriptions stay in val.
const splitOf = new Map(rows.map(x => [x.r.id, x.r.split]));
const isVal = id => splitOf.get(id) === 'valid' ? true : splitOf.get(id) === 'train' ? false :
  parseInt(sha('val|' + groupOf.get(id)).slice(0, 8), 16) / 0xffffffff < VAL_FRAC;
const built = rows.map(lavaRow);
const write = (name, arr) => fs.writeFileSync(path.join(out, name), arr.map(x => JSON.stringify(x)).join('\n') + (arr.length ? '\n' : ''));
write('train.jsonl', built.filter(x => !isVal(x.id)));
write('val.jsonl', built.filter(x => isVal(x.id)));
write('rejected.jsonl', rejected);
// Literal-name check: does the sentence contain the target's catalog name or an alias (v2 asks >= 50% unnamed).
function targetNames(id) {
  let m = id.match(/^NAV_(\d+)(?:_(\d+))?$/);
  if (m) { const p = C.PAGES.filter(x => x.page === +m[1])[0], out = [p.name].concat(p.aliases || []);
    if (m[2] !== undefined) { const sct = C.SECTIONS.filter(x => x.page === +m[1] && x.section === +m[2])[0]; out.push(sct.name, ...(sct.aliases || [])); }
    return out; }
  m = id.match(/^LAY_([A-Za-z]+)_/);
  if (m) { const mo = C.MODULES.filter(x => x.id === m[1])[0]; return [mo.name].concat(mo.aliases || []); }
  return null;
}
const literal = r => { if (r.expect.decision !== 'SELECT') return null; const n = targetNames(r.expect.ids[0]); if (!n) return null;
  const t = r.intent.toLowerCase(); return n.some(a => a && t.indexOf(String(a).toLowerCase().replace(/（.*?）/g, '')) >= 0); };
const count = (arr, f) => arr.reduce((a, x) => (a[f(x)] = (a[f(x)] || 0) + 1, a), {});
const report = {version: 'laya-build-1', inputs: list.split(',').map(f => ({file: path.basename(f), sha256: sha(fs.readFileSync(f))})),
  kept: rows.length, rejected: rejected.length, rejected_by_reason: count(rejected, x => x.why.replace(/ [A-Z]{3}[0-9A-Z-]*$/, '').replace(/of .*$/, 'of …')),
  train: built.filter(x => !isVal(x.id)).length, val: built.filter(x => isVal(x.id)).length,
  by_lang: count(rows, x => x.r.lang), by_decision: count(rows, x => x.r.expect.decision), by_kind: count(rows, x => x.gp[0]),
  by_page: count(rows, x => x.r.ctx.page), slots_per_row: count(built, x => Object.keys(x.questions).length),
  near_threshold_vs_heldout: NEAR, files: {}};
// v2: no valid_only lexicon description may appear in a train row (NFKC, case-fold, no whitespace).
if (lexPath) {
  const nf = t => String(t).normalize('NFKC').toLowerCase().replace(/\s+/g, '');
  const lex = JSON.parse(fs.readFileSync(lexPath, 'utf8'));
  const vo = lex.entries.flatMap(e => e.descriptions.filter(d => d.split === 'valid_only').map(d => nf(d.text)));
  const trainRows = rows.filter(x => !isVal(x.r.id));
  const leaks = trainRows.filter(x => vo.some(v => nf(x.r.intent).indexOf(v) >= 0)).map(x => x.r.id);
  report.lexicon = {file: path.basename(lexPath), sha256: sha(fs.readFileSync(lexPath)), valid_only_descriptions: vo.length,
    valid_only_in_train: leaks.length, examples: leaks.slice(0, 10)};
}
const nameable = rows.filter(x => literal(x.r) !== null);
report.literal_named = {checked: nameable.length, named: nameable.filter(x => literal(x.r)).length,
  by_lang: count(nameable.filter(x => literal(x.r)), x => x.r.lang), checked_by_lang: count(nameable, x => x.r.lang),
  label_mismatch: nameable.filter(x => typeof x.r.named === 'boolean' && x.r.named !== literal(x.r)).length};
for (const f of ['train.jsonl', 'val.jsonl', 'rejected.jsonl']) report.files[f] = sha(fs.readFileSync(path.join(out, f)));
fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 1));
console.log(JSON.stringify({kept: report.kept, rejected: report.rejected, train: report.train, val: report.val, by_lang: report.by_lang, by_decision: report.by_decision}));
