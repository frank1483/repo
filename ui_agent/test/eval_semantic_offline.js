'use strict';
// Offline part of the semantic-scoring experiment. No network.
//   node eval_semantic_offline.js OUT_DIR [LIVE_DIR[,LIVE_DIR...]]   (one dir per recorded part)
// Without LIVE_RECORD_DIR: group 1 (rule) only, plus a fake-semantic smoke test of groups 2-4.
// With it: groups 2-4 from the recorded live outputs (distributions / embeddings), no model calls here.
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const S = require('./semantic_scoring'), C = require('./load_core');
const out = process.argv[2]; if (!out) throw Error('usage: OUT_DIR [LIVE_RECORD_DIR]');
if (fs.existsSync(out)) throw Error('OUT_DIR exists; one run per new directory');
fs.mkdirSync(out, {recursive: true});
const rec = process.argv[3] || null;
const read = f => fs.readFileSync(path.isAbsolute(f) ? f : path.join(__dirname, f), 'utf8').replace(/\r\n/g, '\n').split('\n').filter(s => s.trim()).map(JSON.parse);
const DEV = read('sm_heldout_v1.jsonl'), TEST = read('sm_heldout_v2.jsonl');
const prep = rows => rows.map(row => Object.assign({row, inv: S.inventory(row.ctx)}, S.fixedStage(row)));
const dev = prep(DEV), test = prep(TEST);
const report = {version: 'semantic-eval-1', dev_file: 'sm_heldout_v1.jsonl', test_file: 'sm_heldout_v2.jsonl',
  dev_scored: dev.filter(x => !x.fixed).length, dev_fixed: dev.filter(x => x.fixed).length,
  test_scored: test.filter(x => !x.fixed).length, test_fixed: test.filter(x => x.fixed).length, groups: {}};

// Windows forbids ':' in file names (run1 on the PC failed there); group names keep it, file names do not.
const safe = n => n.replace(/[^A-Za-z0-9._-]+/g, '_');
function runGroup(name, scorer) {
  const sr = set => set.filter(x => !x.fixed).map(x => ({row: x.row, inv: x.inv, scores: scorer(x, set === dev ? 'dev' : 'test'),
    forced: name === 'rule' ? S.ruleForced(x.result) : null}));
  const d = sr(dev), t = sr(test);
  const sw = S.sweep(DEV, d);
  const g = {chosen_on_dev: {tau: sw.best.tau, gap: sw.best.gap}, dev: S.evaluate(d, sw.best.tau, sw.best.gap).summary,
    test: S.evaluate(t, sw.best.tau, sw.best.gap).summary};
  if (name === 'rule') g.native = {tau: 0.75, gap: 0.15, dev: S.evaluate(d, 0.75, 0.15).summary, test: S.evaluate(t, 0.75, 0.15).summary};
  fs.writeFileSync(path.join(out, 'sweep_dev_' + safe(name) + '.json'), JSON.stringify(sw.table));
  fs.writeFileSync(path.join(out, 'rows_' + safe(name) + '.jsonl'), ['dev', 'test'].flatMap(k => S.evaluate(k === 'dev' ? d : t,
    name === 'rule' ? 0.75 : sw.best.tau, name === 'rule' ? 0.15 : sw.best.gap).rows.map(r => JSON.stringify(Object.assign({set: k}, r)))).join('\n') + '\n');
  report.groups[name] = g;
  return {d, t};
}

// Check: group 1 at native thresholds must equal ruleDecide's SELECT/not-SELECT on every scored row.
const ruleRows = runGroup('rule', x => S.ruleScores(x.result));
let mismatch = 0;
for (const x of dev.concat(test).filter(x => !x.fixed && !S.ruleForced(x.result))) {
  const d = S.decide(S.ruleScores(x.result), x.inv, x.row.ctx, 0.75, 0.15);
  const sel = x.result.rule.decision === 'SELECT';
  if ((d.decision === 'SELECT') !== sel || (sel && d.ids[0] !== x.result.rule.choice_id)) mismatch++;
}
report.rule_native_matches_ruleDecide = mismatch === 0 ? 'yes' : mismatch + ' rows differ';
// Fixed rows (stage A/B) are the same for every group; their accuracy is reported once.
const fixedAcc = set => { const f = set.filter(x => x.fixed); return f.filter(x => { const g = x.row.expect, d = x.decision;
  const ids = d.decision === 'SELECT' ? (d.steps ? d.steps.map(s => s.choice_id) : [d.choice_id]) : [];
  return g.decision === 'SELECT' ? d.decision === 'SELECT' && JSON.stringify(ids) === JSON.stringify(g.ids) : d.decision !== 'SELECT'; }).length + '/' + f.length; };
report.fixed_rows_correct = {dev: fixedAcc(dev), test: fixedAcc(test)};

if (!rec) {
  // Smoke only: a deterministic fake "semantic" score (character-bigram overlap with desc) to prove groups 3/4 plumbing.
  const bg = s => { const t = s.replace(/\s+/g, ''), o = new Set(); for (let i = 0; i + 1 < t.length; ++i) o.add(t.substr(i, 2)); return o; };
  const fake = x => { const q = bg(x.row.intent), s = {}; for (const c of x.inv) { const b = bg(c.desc); let h = 0; for (const k of q) if (b.has(k)) h++; s[c.id] = q.size ? h / q.size : 0; } return s; };
  runGroup('SMOKE_fake_embed', fake);
  runGroup('SMOKE_fake_combo_w05', x => S.comboScores(S.ruleScores(x.result), fake(x), 0.5));
  report.note = 'SMOKE_* groups use a fake bigram scorer only to test the plumbing; they are not results.';
} else {
  const dirs = rec.split(','), R = {embed_models: [], logprob_models: []};
  report.live_record = [];
  for (const dir of dirs) {
    const r = JSON.parse(fs.readFileSync(path.join(dir, 'record.json'), 'utf8'));
    report.live_record.push({dir, part: r.part, source_sha256: r.source_sha256, calls: r.calls});
    R.embed_models.push(...(r.embed_models || [])); R.logprob_models.push(...(r.logprob_models || []));
    // Latency from the raw call log: logprob = per-sentence total of its calls; embed = per embedded text.
    const raw = fs.existsSync(path.join(dir, 'raw_calls.jsonl')) ? read(path.relative(__dirname, path.join(dir, 'raw_calls.jsonl'))) : [];
    const med = a => { const b = a.slice().sort((x, y) => x - y); return b.length ? b[Math.floor((b.length - 1) / 2)] : null; };
    const lat = report.latency = report.latency || {};
    for (const tag of new Set(raw.map(c => c.model))) {
      const mine = raw.filter(c => c.model === tag);
      if (r.part === 'logprob') { const per = {}; for (const c of mine) per[c.id] = (per[c.id] || 0) + c.latency_ms;
        lat['logprob:' + tag] = {median_ms_per_sentence: med(Object.values(per)), median_calls_per_sentence: med(Object.keys(per).map(id => mine.filter(c => c.id === id).length))}; }
      else { const items = mine.reduce((a, c) => a + ((c.body && c.body.count) || 0), 0);
        lat['embed:' + tag] = {total_ms: mine.reduce((a, c) => a + c.latency_ms, 0), texts: items, ms_per_text: items ? Math.round(mine.reduce((a, c) => a + c.latency_ms, 0) / items * 10) / 10 : null}; }
    }
  }
  for (const m of R.embed_models || []) {
    if (!m.ok) { report.groups['embed:' + m.tag] = {invalid: m.error}; continue; }
    const vec = t => m.vectors[t]; const sem = x => S.embedScores(m.vectors['Q:' + x.row.id], x.inv, vec);
    runGroup('embed:' + m.tag, sem);
    runGroup('cascade:rule>embed:' + m.tag, x => { const r = S.ruleScores(x.result), d = S.decide(r, x.inv, x.row.ctx, 0.75, 0.15); return d.confident ? Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v + 10])) : sem(x); });
    for (const w of [0.25, 0.5, 0.75]) runGroup('combo' + w + ':rule+embed:' + m.tag, x => S.comboScores(S.ruleScores(x.result), sem(x), w));
  }
  for (const m of R.logprob_models || []) {
    if (!m.ok) { report.groups['logprob:' + m.tag] = {invalid: m.error}; continue; }
    const sem = x => S.logprobScores(x.inv, prefix => m.dists[x.row.id + '|' + prefix.join('/')] || null);
    runGroup('logprob:' + m.tag, sem);
    for (const w of [0.25, 0.5, 0.75]) runGroup('combo' + w + ':rule+logprob:' + m.tag, x => S.comboScores(S.ruleScores(x.result), sem(x), w));
  }
}
const files = ['semantic_scoring.js', 'eval_semantic_offline.js', '../qml/GcpAgentCore.js', 'sm_heldout_v1.jsonl', 'sm_heldout_v2.jsonl'];
report.code_sha256 = Object.fromEntries(files.map(f => [f, crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname, f), 'utf8').replace(/\r\n/g, '\n')).digest('hex')]));
report.ran_at_utc = new Date().toISOString();
fs.writeFileSync(path.join(out, 'summary.json'), JSON.stringify(report, null, 1));
for (const [k, g] of Object.entries(report.groups)) if (g.dev) console.log(k.padEnd(34), 'chosen', JSON.stringify(g.chosen_on_dev), '| dev', g.dev.correct + '/' + g.dev.n, 'wrong', g.dev.confident_wrong, '| test', g.test.correct + '/' + g.test.n, 'wrong', g.test.confident_wrong, 'cov', g.test.coverage, 'top1', g.test.top1, 'top6', g.test.top6);
console.log('rule native:', JSON.stringify(report.groups.rule.native.dev), JSON.stringify(report.groups.rule.native.test));
console.log('native matches ruleDecide:', report.rule_native_matches_ruleDecide, '| fixed rows', JSON.stringify(report.fixed_rows_correct), '| scored dev/test', report.dev_scored, report.test_scored);
