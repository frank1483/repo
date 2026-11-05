'use strict';
// Offline comparison: state-machine loop (sm-v0) vs v6 one-shot pipeline. No HTTP, Qt or devices.
// Models here are PROGRAMS (oracle / fault injection / seeded random), not real LLMs.
// Usage: node eval_sm_vs_v6.js OUT_DIR [HELDOUT_FILE]   (eval v2: held-out file argument, oracle knows OTHER/AMBIGUOUS)
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const C = require('./load_core'), SM = require('./load_sm');
const out = process.argv[2]; if (!out) throw Error('usage: eval_sm_vs_v6.js OUT_DIR');
if (fs.existsSync(out)) throw Error('OUT_DIR exists; every run uses a new directory');
fs.mkdirSync(out, {recursive: true});
const read = f => fs.readFileSync(path.join(__dirname, f), 'utf8').split(/\r?\n/).filter(s => s.trim()).map(JSON.parse);
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname, f))).digest('hex');

// ---------------------------------------------------------------- token estimate (not a real tokenizer)
function estTokens(messages) {
  let cjk = 0, other = 0;
  for (const m of messages) for (const ch of m.content) {
    if (/[　-〿㐀-鿿＀-￯]/.test(ch)) cjk++; else if (!/\s/.test(ch)) other++;
  }
  return cjk + Math.ceil(other / 4);
}

// ---------------------------------------------------------------- v6 driver (mirrors GcpAgentOverlay.handle/finish)
function v6Run(intent, ctx, model) {
  const screened = C.preGate(intent);
  if (screened) return {decision: screened.rule, calls: [], source: 'rule', scope: []};
  const result = C.analyzeTurn(intent, ctx, '');
  const ask = !!model && !result.rule.final && (C.needsModel(result, false) || result.candidates.length === 0);
  if (ask && result.candidates.length === 0) result.candidates = C.catalogCandidates(ctx);
  let mv = null; const calls = [];
  if (ask && result.candidates.length) {
    const call = {state: 'V6_ONE_SHOT', messages: [{role: 'system', content: C.SYSTEM_PROMPT}, {role: 'user', content: C.buildUserMessage(result, ctx)}],
      schema: C.decisionSchema(result), codes: result.candidates.map(c => c.id), result};
    calls.push(call);
    let raw; try { raw = model(call); } catch (e) { raw = null; }
    mv = raw == null ? {ok: false, error: 'no reply'} : C.validateModelDecision(C.extractJson(raw), result);
  }
  let decision = result.rule, source = 'rule';
  if (mv && mv.ok) { decision = mv; source = 'model'; } else if (mv) source = 'rule_fallback';
  if (result.generic_settings) { decision = result.rule; source = 'rule'; }
  const scope = JSON.parse(JSON.stringify(result.candidates || []));
  if (!C.gateSelection(decision, scope, ctx).ok) {
    if (decision === mv && C.gateSelection(result.rule, scope, ctx).ok) { decision = result.rule; source = 'rule_gate_fallback'; }
    else decision = {decision: 'HOLD'};
  }
  return {decision, calls, source, scope};
}
function smRun(intent, ctx, model) {
  const r = SM.runSync(C, intent, ctx, '', model, model ? {} : {modelEnabled: false});
  return {decision: r.decision, calls: r.calls, source: r.decision.source, scope: r.decision.candidates || []};
}
const idsOf = d => d.decision === 'SELECT' ? (d.steps ? d.steps.map(s => s.choice_id) : [d.choice_id]) : [];
const correct = (d, ex) => d.decision === ex.decision && JSON.stringify(idsOf(d)) === JSON.stringify(ex.ids);
function unsafe(run, ctx) {
  // Any executed ID must exist exactly once in a program-built scope and pass the second-layer gate.
  if (run.decision.decision !== 'SELECT') return false;
  const ids = idsOf(run.decision);
  if (!ids.every(id => run.scope.filter(c => c.id === id).length === 1)) return true;
  return !C.gateSelection({decision: 'SELECT', steps: ids.map(id => ({choice_id: id}))}, run.scope, ctx).ok;
}

// ---------------------------------------------------------------- programmatic models
// Oracle answers from the gold label: the best a perfect model could do inside each pipeline's options.
function parseGold(id) {
  let m;
  if ((m = /^NAV_(\d+)(?:_(\d+))?$/.exec(id))) return {kind: 'NAV', page: +m[1], section: m[2] === undefined ? -1 : +m[2]};
  if ((m = /^LAY_([A-Za-z]+)_(MOVE|NUDGE|SCALE|HIDE|SHOW|RESET)(?:_(\w+))?$/.exec(id))) {
    const action = m[2] === 'MOVE' ? 'MOVE_' + m[3] : m[2] === 'NUDGE' ? 'NUDGE_' + m[3]
      : m[2] === 'SCALE' ? {125: 'SCALE_UP', 80: 'SCALE_DOWN', 200: 'SCALE_MAX', 50: 'SCALE_MIN'}[m[3]] : m[2];
    return {kind: 'LAYOUT', module: m[1], action};
  }
  if ((m = /^SYS_TEXT_SCALE_(\d+)$/.exec(id))) return {kind: 'TEXT', code: 'T' + String(m[1]).padStart(3, '0')};
  if (['UNDO', 'REDO', 'RESET_ALL'].includes(id)) return {kind: 'HISTORY', code: id};
  return null;
}
function oracleFor(row) {
  const ex = row.expect, gid = ex.decision === 'SELECT' ? ex.ids[0] : '', g = gid ? parseGold(gid) : null;
  const pick = (codes, want, fallback) => JSON.stringify({value: codes.includes(want) ? want : fallback});
  return function (call) {
    if (call.state === 'V6_ONE_SHOT') {
      if (ex.decision === 'SELECT' && call.codes.includes(gid)) return JSON.stringify({decision: 'SELECT', choice_id: gid, reason_zh: 'oracle', evidence_ids: []});
      return JSON.stringify({decision: ex.decision === 'HOLD' ? 'HOLD' : 'CLARIFY', choice_id: '', reason_zh: 'oracle', evidence_ids: []});
    }
    const c = call.codes;
    switch (call.state) {
      case 'S4_PICK': return pick(c, gid, ex.decision === 'HOLD' ? 'NONE' : (ex.decision === 'SELECT' && c.includes('OTHER') ? 'OTHER' : 'CLARIFY'));
      case 'S2_CLASSIFY': return pick(c, g ? g.kind : (ex.decision === 'HOLD' ? 'OUT_OF_SCOPE' : 'AMBIGUOUS'), 'UNKNOWN');
      case 'S3_PAGE': return pick(c, g ? 'P' + g.page : '', 'UNKNOWN');
      case 'S3_SECTION': return pick(c, g && g.section >= 0 ? 'S' + g.section : 'WHOLE', 'UNKNOWN');
      case 'S3_MODULE': return pick(c, g ? g.module : '', 'UNKNOWN');
      case 'S3_ACTION': return pick(c, g ? g.action : '', 'UNKNOWN');
      case 'S3_TEXT': case 'S3_HISTORY': return pick(c, g ? g.code : '', 'UNKNOWN');
    }
    return JSON.stringify({value: 'UNKNOWN'});
  };
}
const garbageFirst = row => { const o = oracleFor(row); let n = 0; return call => (n++ === 0 ? '好的，我建議切到安全設定頁面。' : o(call)); };
const alwaysGarbage = () => () => '{"decision":"SELECT","choice_id":"TAKEOFF_NOW","value":"ARM"}';
function seeded(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
// Seeded uniform choice inside each call's own allowed options: a crude stand-in for a weak model.
const randomValid = seed => { const rnd = seeded(seed); return call => {
  if (call.state === 'V6_ONE_SHOT') {
    const opts = call.codes.map(id => ({decision: 'SELECT', choice_id: id})).concat([{decision: 'CLARIFY', choice_id: ''}, {decision: 'HOLD', choice_id: ''}]);
    const o = opts[Math.floor(rnd() * opts.length)]; return JSON.stringify(Object.assign({reason_zh: 'r', evidence_ids: []}, o));
  }
  return JSON.stringify({value: call.codes[Math.floor(rnd() * call.codes.length)]});
}; };

// ---------------------------------------------------------------- data
const corpus = read('regression_ui_agent.jsonl').filter(r => typeof r.intent === 'string' && !r.turns);
const textRows = read('text_regression_v6_0400.jsonl').filter(r => typeof r.text === 'string' && r.expect && r.expect.decision)
  .map(r => ({id: r.id, intent: r.text, ctx: r.ctx || {page: 0, section: -1}, expect: r.expect}));
const HELDOUT = process.argv[3] || 'sm_heldout_v1.jsonl';
const heldout = read(HELDOUT);
const uncertainCorpus = corpus.filter(r => ['UIV3-0001', 'UIV3-0244', 'UIV3-0246'].includes(r.id));
const modelSet = heldout.concat(uncertainCorpus);
const manifest = {version: SM.VERSION, ran_at_utc: new Date().toISOString(),
  inputs: {regression_ui_agent: sha('regression_ui_agent.jsonl'), text_regression_v6_0400: sha('text_regression_v6_0400.jsonl'),
    heldout_file: HELDOUT, heldout: sha(HELDOUT)},
  code: {core: sha('../qml/GcpAgentCore.js'), sm: sha('../qml/GcpAgentStateMachine.js'), eval: sha('eval_sm_vs_v6.js')}};

// ---------------------------------------------------------------- E1 rule path, model disabled
const e1 = {rows: 0, identical: 0, diffs: []};
for (const r of corpus.concat(textRows)) {
  const a = v6Run(r.intent, r.ctx, null).decision, b = smRun(r.intent, r.ctx, null).decision;
  e1.rows++;
  if (a.decision === b.decision && JSON.stringify(idsOf(a)) === JSON.stringify(idsOf(b))) e1.identical++;
  else e1.diffs.push({id: r.id, intent: r.intent, v6: [a.decision, idsOf(a)], sm: [b.decision, idsOf(b)]});
}

// ---------------------------------------------------------------- E2/E3 on the model-path set
function route(r) {
  if (C.preGate(r.intent)) return 'rule';
  const res = C.analyzeTurn(r.intent, r.ctx, '');
  if (res.rule.final || res.generic_settings || res.rule.decision === 'SELECT') return 'rule';
  return res.candidates.length ? 'uncertain' : 'no_target';
}
const models = {
  oracle: r => oracleFor(r), garbage_first: r => garbageFirst(r), always_garbage: () => alwaysGarbage(),
  random_valid_s1: r => randomValid(1000 + modelSet.indexOf(r)), random_valid_s2: r => randomValid(2000 + modelSet.indexOf(r)),
  random_valid_s3: r => randomValid(3000 + modelSet.indexOf(r))
};
const perRow = [], summary = {};
for (const [mname, mk] of Object.entries(models)) {
  for (const pipe of ['v6', 'sm']) {
    const key = mname + '/' + pipe, s = summary[key] = {all: {n: 0, ok: 0}, model_path: {n: 0, ok: 0}, rule_path: {n: 0, ok: 0},
      calls: 0, est_prompt_tokens: 0, max_calls_one_sentence: 0, max_prompt_tokens_one_call: 0, repaired_ok: 0, fallback: 0, unsafe: 0};
    for (const r of modelSet) {
      const rt = route(r), run = (pipe === 'v6' ? v6Run : smRun)(r.intent, r.ctx, mk(r));
      const ok = correct(run.decision, r.expect), toks = run.calls.map(c => estTokens(c.messages));
      const bucket = rt === 'rule' ? s.rule_path : s.model_path;
      s.all.n++; bucket.n++; if (ok) { s.all.ok++; bucket.ok++; }
      s.calls += run.calls.length; s.est_prompt_tokens += toks.reduce((a, b) => a + b, 0);
      s.max_calls_one_sentence = Math.max(s.max_calls_one_sentence, run.calls.length);
      s.max_prompt_tokens_one_call = Math.max(s.max_prompt_tokens_one_call, ...toks, 0);
      if (/fallback/.test(run.source || '')) s.fallback++;
      if (run.calls.some(c => c.repair) && ok && !/fallback/.test(run.source || '')) s.repaired_ok++;
      if (unsafe(run, r.ctx)) s.unsafe++;
      perRow.push({model: mname, pipe, id: r.id, group: r.group || 'corpus', route: rt, expect: r.expect,
        got: {decision: run.decision.decision, ids: idsOf(run.decision)}, ok, source: run.source,
        calls: run.calls.map((c, i) => ({state: c.state, repair: !!c.repair, options: c.codes.length, est_tokens: toks[i]}))});
    }
  }
}
// Example prompts for the report (first model-path row of each kind).
const examples = {};
for (const r of modelSet) {
  const rt = route(r); if (rt === 'rule' || examples[rt]) continue;
  examples[rt] = {id: r.id, intent: r.intent, v6: v6Run(r.intent, r.ctx, oracleFor(r)).calls.map(c => c.messages),
    sm: smRun(r.intent, r.ctx, oracleFor(r)).calls.map(c => c.messages)};
}
const routes = {}; for (const r of modelSet) { const k = route(r); routes[k] = (routes[k] || 0) + 1; }
const report = {manifest, e1: {rows: e1.rows, identical: e1.identical, diffs: e1.diffs},
  model_set: {rows: modelSet.length, routes}, summary};
fs.writeFileSync(path.join(out, 'summary.json'), JSON.stringify(report, null, 2));
fs.writeFileSync(path.join(out, 'per_row.jsonl'), perRow.map(x => JSON.stringify(x)).join('\n') + '\n');
fs.writeFileSync(path.join(out, 'example_prompts.json'), JSON.stringify(examples, null, 2));
console.log(JSON.stringify({e1: {rows: e1.rows, identical: e1.identical, diffs: e1.diffs.length}, routes}, null, 0));
for (const [k, s] of Object.entries(summary))
  console.log(k.padEnd(24), 'all', s.all.ok + '/' + s.all.n, 'model_path', s.model_path.ok + '/' + s.model_path.n,
    'calls', s.calls, 'estTok', s.est_prompt_tokens, 'maxCalls', s.max_calls_one_sentence, 'maxTokCall', s.max_prompt_tokens_one_call,
    'repairedOK', s.repaired_ok, 'fallback', s.fallback, 'unsafe', s.unsafe);
