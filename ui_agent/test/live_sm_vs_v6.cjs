'use strict';
// E4 live comparison: sm-v0 state machine vs v6 one-shot, same sentences, real local Ollama.
// One run only. No retries. Writes every call as it happens (first results are kept as-is).
//   node live_sm_vs_v6.cjs --mode prepare              -> prints source hash, no network
//   node live_sm_vs_v6.cjs --mode run --out DIR --confirm <hash8>
// Network: only http://127.0.0.1:11434 (GET /api/tags once, POST /api/chat). Nothing else.
const fs = require('fs'), path = require('path'), http = require('http'), crypto = require('crypto');
const args = process.argv.slice(2), arg = k => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
const mode = arg('--mode');
const C = require('./load_core'), SM = require('./load_sm');
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const FILES = ['../qml/GcpAgentCore.js', '../qml/GcpAgentStateMachine.js', 'load_core.js', 'load_sm.js',
  'sm_heldout_v1.jsonl', 'regression_ui_agent.jsonl', 'live_sm_vs_v6.cjs'];
// Hash over LF-normalised text so a Windows CRLF checkout gives the same value.
const norm = f => fs.readFileSync(path.join(__dirname, f), 'utf8').replace(/\r\n/g, '\n');
const files = FILES.map(f => ({file: f, sha256: sha(norm(f))}));
const MODELS = [
  {name: 'Gemma 4 E2B', tag: 'gemma4:e2b'},
  {name: 'LFM3 1.7B', tag: 'hf.co/LiquidAI/LFM3-1.7B-GGUF:QAD-Q4_0'}
];
const WARMUP_TEXT = '幫我講個笑話';
const SETTINGS = {stream: false, options: {temperature: 0}, think: false, timeout_ms: 60000};
const read = f => norm(f).split('\n').filter(s => s.trim()).map(JSON.parse);
const heldout = read('sm_heldout_v1.jsonl');
const corpus3 = read('regression_ui_agent.jsonl').filter(r => ['UIV3-0001', 'UIV3-0244', 'UIV3-0246'].includes(r.id) && !r.turns);
const rows = heldout.concat(corpus3);
const route = r => { if (C.preGate(r.intent)) return 'rule'; const x = C.analyzeTurn(r.intent, r.ctx, '');
  return (x.rule.final || x.generic_settings || x.rule.decision === 'SELECT') ? 'rule' : (x.candidates.length ? 'uncertain' : 'no_target'); };
const modelRows = rows.filter(r => route(r) !== 'rule');
const MAX_CALLS = MODELS.length * (1 + modelRows.length * (1 + SM.MAX_MODEL_CALLS));
const source = {version: SM.VERSION, files, warmup: WARMUP_TEXT, models: MODELS, settings: SETTINGS, rows: rows.length,
  model_path_rows: modelRows.map(r => r.id), max_calls: MAX_CALLS};
const sourceHash = sha(JSON.stringify(source));
if (mode === 'prepare') {
  console.log(JSON.stringify({source_sha256: sourceHash, hash8: sourceHash.slice(0, 8), rows: rows.length,
    model_path_rows: modelRows.length, max_calls: MAX_CALLS, files}, null, 2));
  process.exit(0);
}
if (mode !== 'run') throw Error('--mode prepare|run');
if (arg('--confirm') !== sourceHash.slice(0, 8)) throw Error('confirm hash8 mismatch; expected ' + sourceHash.slice(0, 8));
const out = arg('--out'); if (!out) throw Error('--out DIR required');
if (fs.existsSync(out)) throw Error('OUT exists; one run per new directory');
fs.mkdirSync(out, {recursive: true});
fs.writeFileSync(path.join(out, 'source.json'), JSON.stringify(Object.assign({source_sha256: sourceHash}, source), null, 2));
const rawLog = path.join(out, 'raw_calls.jsonl'), rowLog = path.join(out, 'rows.jsonl');
let callCount = 0;

function post(body) {
  return new Promise(resolve => {
    const data = Buffer.from(JSON.stringify(body)), t0 = Date.now();
    const req = http.request({hostname: '127.0.0.1', port: 11434, path: '/api/chat', method: 'POST', agent: false,
      headers: {'Content-Type': 'application/json', 'Content-Length': data.length}}, res => {
      const chunks = []; res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({status: res.statusCode, body: Buffer.concat(chunks).toString('utf8'), ms: Date.now() - t0}));
    });
    req.setTimeout(SETTINGS.timeout_ms, () => { req.destroy(); resolve({timeout: true, ms: Date.now() - t0}); });
    req.on('error', e => resolve({error: String(e), ms: Date.now() - t0}));
    req.end(data);
  });
}
function getTags() {
  return new Promise(resolve => {
    http.get({hostname: '127.0.0.1', port: 11434, path: '/api/tags', agent: false}, res => {
      const chunks = []; res.on('data', c => chunks.push(c)); res.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    }).on('error', e => resolve(JSON.stringify({error: String(e)})));
  });
}
async function callModel(model, meta, call) {
  if (++callCount > MAX_CALLS) throw Error('call budget exceeded');
  const body = {model: model.tag, messages: call.messages, format: call.schema, stream: SETTINGS.stream,
    options: SETTINGS.options, think: SETTINGS.think};
  const r = await post(body);
  let env = null; try { env = r.body ? JSON.parse(r.body) : null; } catch (_) {}
  const content = env && env.message && typeof env.message.content === 'string' ? env.message.content : null;
  const rec = Object.assign({n: callCount, model: model.tag, state: call.state, repair: !!call.repair, options: call.codes.length,
    http: r.status || null, timeout: !!r.timeout, error: r.error || (env && env.error) || null, latency_ms: r.ms,
    prompt_eval_count: env && env.prompt_eval_count, eval_count: env && env.eval_count,
    total_duration_ns: env && env.total_duration, thinking_nonempty: !!(env && env.message && env.message.thinking),
    content: content === null ? null : content.slice(0, 600)}, meta);
  fs.appendFileSync(rawLog, JSON.stringify(rec) + '\n');
  if (content === null) throw Error(r.timeout ? 'timeout' : (rec.error || 'http ' + r.status));
  return content;
}
async function v6(model, r) {
  const result = C.analyzeTurn(r.intent, r.ctx, '');
  if (result.candidates.length === 0) result.candidates = C.catalogCandidates(r.ctx);
  const call = {state: 'V6_ONE_SHOT', messages: [{role: 'system', content: C.SYSTEM_PROMPT}, {role: 'user', content: C.buildUserMessage(result, r.ctx)}],
    schema: C.decisionSchema(result), codes: result.candidates.map(c => c.id)};
  let mv;
  try { mv = C.validateModelDecision(C.extractJson(await callModel(model, {pipe: 'v6', id: r.id}, call)), result); }
  catch (e) { mv = {ok: false, error: String(e.message || e)}; }
  let decision = result.rule, src = 'rule_fallback';
  if (mv.ok) { decision = mv; src = 'model'; }
  const scope = result.candidates;
  if (!C.gateSelection(decision, scope, r.ctx).ok) { decision = C.gateSelection(result.rule, scope, r.ctx).ok ? result.rule : {decision: 'HOLD'}; src = 'rule_gate_fallback'; }
  return {decision, source: src, model_error: mv.ok ? '' : mv.error, calls: 1};
}
async function sm(model, r) {
  const s = SM.create(C).start(r.intent, r.ctx, '');
  for (let guard = 0; guard < 16; ++guard) {
    const step = s.next();
    if (step.type === 'done') return {decision: step.decision, source: step.decision.source, calls: step.model_calls, trace: step.trace};
    try { s.answer(await callModel(model, {pipe: 'sm', id: r.id}, step.call)); } catch (e) { s.fail(String(e.message || e)); }
  }
  throw Error('no termination');
}
const idsOf = d => d.decision === 'SELECT' ? (d.steps ? d.steps.map(s => s.choice_id) : [d.choice_id]) : [];
const ok = (d, ex) => d.decision === ex.decision && JSON.stringify(idsOf(d)) === JSON.stringify(ex.ids);
(async () => {
  fs.writeFileSync(path.join(out, 'ollama_tags.json'), await getTags());
  const started = new Date().toISOString();
  for (const model of MODELS) {
    // One unscored warm-up per model (a classify prompt from an out-of-set sentence).
    const warm = SM.create(C).start(WARMUP_TEXT, {page: 0, section: -1}, '').next();
    if (warm.type !== 'ask') throw Error('warm-up sentence must reach a model state');
    try { await callModel(model, {pipe: 'warmup', id: 'WARMUP'}, warm.call); } catch (_) {}
    for (const r of modelRows) for (const [pipe, fn] of [['v6', v6], ['sm', sm]]) {
      const t0 = Date.now(), res = await fn(model, r);
      fs.appendFileSync(rowLog, JSON.stringify({model: model.tag, pipe, id: r.id, group: r.group || 'corpus', route: route(r),
        expect: r.expect, got: {decision: res.decision.decision, ids: idsOf(res.decision)}, ok: ok(res.decision, r.expect),
        source: res.source, model_error: res.model_error || '', calls: res.calls, wall_ms: Date.now() - t0,
        trace: res.trace || null}) + '\n');
    }
  }
  const done = {started_utc: started, finished_utc: new Date().toISOString(), calls: callCount};
  fs.writeFileSync(path.join(out, 'done.json'), JSON.stringify(done, null, 2));
  console.log(JSON.stringify(done));
})().catch(e => { fs.writeFileSync(path.join(out, 'aborted.txt'), String(e && e.stack || e)); console.error(e); process.exit(2); });
