'use strict';
// Live recorder for the semantic-scoring experiment. Records raw model outputs once; all scoring and
// threshold work is done afterwards by eval_semantic_offline.js from the record (no extra calls).
//   node live_semantic.cjs --mode prepare                    -> hash8 per part, no network
//   node live_semantic.cjs --mode run --part logprob|embed --out DIR --confirm <hash8>
// Network: only http://127.0.0.1:11434 (GET /api/tags, POST /api/chat, POST /api/embed). Never pulls models.
// A model missing from /api/tags is recorded as "not installed" and skipped (no download).
const fs = require('fs'), path = require('path'), http = require('http'), crypto = require('crypto');
const args = process.argv.slice(2), arg = k => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
const S = require('./semantic_scoring'), C = require('./load_core');
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const norm = f => fs.readFileSync(path.join(__dirname, f), 'utf8').replace(/\r\n/g, '\n');
const FILES = ['../qml/GcpAgentCore.js', 'load_core.js', 'semantic_scoring.js', 'eval_semantic_offline.js', 'live_semantic.cjs',
  'sm_heldout_v1.jsonl', 'sm_heldout_v2.jsonl'];
// Non-Chinese models only (user 2026-11-06). Both logprob models are already installed on the PC.
const PARTS = {
  logprob: {models: [{name: 'Gemma 4 E2B', tag: 'gemma4:e2b', origin: 'Google'},
                     {name: 'LFM3 1.7B', tag: 'hf.co/LiquidAI/LFM3-1.7B-GGUF:QAD-Q4_0', origin: 'Liquid AI'}],
            settings: {stream: false, think: false, logprobs: true, top_logprobs: 20, options: {temperature: 0, num_predict: 1}, timeout_ms: 60000,
                       expand_kinds: 2, expand_children: 2, min_p: 0.05}},
  embed: {models: [{name: 'EmbeddingGemma 300M', tag: 'embeddinggemma:300m', origin: 'Google',
                    query: 'task: search result | query: ', doc: 'title: none | text: '},
                   {name: 'Granite Embedding 278M', tag: 'granite-embedding:278m', origin: 'IBM', query: '', doc: ''}],
          settings: {batch: 32, timeout_ms: 120000}}
};
const read = f => norm(f).split('\n').filter(s => s.trim()).map(JSON.parse);
const rows = read('sm_heldout_v1.jsonl').concat(read('sm_heldout_v2.jsonl')).filter(r => !S.fixedStage(r).fixed);
const files = FILES.map(f => ({file: f, sha256: sha(norm(f))}));
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
const MAX_CALLS = {logprob: PARTS.logprob.models.length * (1 + rows.length * 7), embed: PARTS.embed.models.length * (2 + Math.ceil((rows.length + 500) / 32))};
const sourceOf = part => ({experiment: 'ui-semantic-scoring-1', part, files, models: PARTS[part].models, settings: PARTS[part].settings,
  rows: rows.map(r => r.id), max_calls: MAX_CALLS[part]});
const hashOf = part => sha(JSON.stringify(sourceOf(part)));
const mode = arg('--mode');
if (mode === 'prepare') {
  console.log(JSON.stringify({rows: rows.length, parts: Object.fromEntries(Object.keys(PARTS).map(p => [p, {hash8: hashOf(p).slice(0, 8),
    source_sha256: hashOf(p), max_calls: MAX_CALLS[p], models: PARTS[p].models.map(m => m.tag)}])), files}, null, 2));
  process.exit(0);
}

// ---------- slot tree for the logprob part (same slots as the state machine, options as letters)
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
function nodePrompt(row, prefix, node) {
  const known = [];
  if (prefix[0]) known.push('類別=' + prefix[0]);
  if (prefix[0] === 'NAV' && prefix[1]) known.push('畫面=' + pageOf(+prefix[1].slice(1)).name);
  if (prefix[0] === 'LAYOUT' && prefix[1]) known.push('模組=' + C.MODULES.filter(m => m.id === prefix[1])[0].name);
  const lines = ['使用者對地面站介面說：「' + row.intent + '」', '目前畫面：' + C.pageName(row.ctx.page)];
  if (known.length) lines.push('已知：' + known.join('；'));
  lines.push('問題：' + node.need, '選項：');
  node.opts.forEach((o, i) => lines.push(LETTERS[i] + '. ' + o[1]));
  lines.push('只回答一個英文字母。');
  return [{role: 'system', content: '你是無人機地面站介面助理流程中的一個步驟。只回答一個選項字母，不要解釋。'}, {role: 'user', content: lines.join('\n')}];
}

if (mode !== 'run') throw Error('--mode prepare|run');
const part = arg('--part'); if (!PARTS[part]) throw Error('--part logprob|embed');
const sourceHash = hashOf(part);
if (arg('--confirm') !== sourceHash.slice(0, 8)) throw Error('confirm hash8 mismatch; expected ' + sourceHash.slice(0, 8));
const out = arg('--out'); if (!out) throw Error('--out DIR required');
if (fs.existsSync(out)) throw Error('OUT exists; one run per new directory');
fs.mkdirSync(out, {recursive: true});
fs.writeFileSync(path.join(out, 'source.json'), JSON.stringify(Object.assign({source_sha256: sourceHash}, sourceOf(part)), null, 2));
const rawLog = path.join(out, 'raw_calls.jsonl');
let calls = 0;
function request(method, p, body, timeout) {
  return new Promise(resolve => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null, t0 = Date.now();
    const req = http.request({hostname: '127.0.0.1', port: 11434, path: p, method, agent: false,
      headers: data ? {'Content-Type': 'application/json', 'Content-Length': data.length} : {}}, res => {
      const ch = []; res.on('data', c => ch.push(c)); res.on('end', () => resolve({status: res.statusCode, body: Buffer.concat(ch).toString('utf8'), ms: Date.now() - t0}));
    });
    req.setTimeout(timeout || 60000, () => { req.destroy(); resolve({timeout: true, ms: Date.now() - t0}); });
    req.on('error', e => resolve({error: String(e), ms: Date.now() - t0}));
    req.end(data || undefined);
  });
}
async function call(p, body, meta, timeout) {
  if (++calls > MAX_CALLS[part]) throw Error('call budget exceeded');
  const r = await request('POST', p, body, timeout);
  let env = null; try { env = r.body ? JSON.parse(r.body) : null; } catch (_) {}
  fs.appendFileSync(rawLog, JSON.stringify(Object.assign({n: calls, path: p, http: r.status || null, timeout: !!r.timeout, error: r.error || (env && env.error) || null,
    latency_ms: r.ms, body: p === '/api/embed' ? {count: env && env.embeddings && env.embeddings.length} : (r.body || '').slice(0, 4000)}, meta)) + '\n');
  if (!env || env.error || r.status !== 200) throw Error(r.timeout ? 'timeout' : String(r.error || (env && env.error) || 'http ' + r.status));
  return env;
}
function letterDist(env, n) {
  const lp = env.logprobs;
  if (!Array.isArray(lp) || !lp.length || !Array.isArray(lp[0].top_logprobs)) return null;
  const d = {}; let z = 0;
  for (const t of lp[0].top_logprobs) {
    const k = String(t.token).trim().toUpperCase().replace(/[^A-Z]/g, '');
    const i = LETTERS.indexOf(k);
    if (k.length === 1 && i >= 0 && i < n) { const p = Math.exp(t.logprob); d[i] = (d[i] || 0) + p; z += p; }
  }
  return z > 0 ? {d, z} : {d: {}, z: 0};
}
(async () => {
  const tags = (await request('GET', '/api/tags')).body || '{}';
  fs.writeFileSync(path.join(out, 'ollama_tags.json'), tags);
  let installed = []; try { installed = JSON.parse(tags).models.map(m => m.name); } catch (_) {}
  const record = {source_sha256: sourceHash, part, started_utc: new Date().toISOString()};
  if (part === 'embed') {
    record.embed_models = [];
    const descs = [...new Set(rows.flatMap(r => S.inventory(r.ctx).map(c => c.desc)))];
    for (const m of PARTS.embed.models) {
      const rec = {tag: m.tag, ok: false, vectors: {}};
      record.embed_models.push(rec);
      if (installed.indexOf(m.tag) < 0) { rec.error = 'not installed (no download by this script)'; continue; }
      try {
        const items = rows.map(r => ['Q:' + r.id, m.query + r.intent]).concat(descs.map(d => [d, m.doc + d]));
        for (let i = 0; i < items.length; i += PARTS.embed.settings.batch) {
          const chunk = items.slice(i, i + PARTS.embed.settings.batch);
          const env = await call('/api/embed', {model: m.tag, input: chunk.map(x => x[1])}, {model: m.tag, chunk: i}, PARTS.embed.settings.timeout_ms);
          if (!Array.isArray(env.embeddings) || env.embeddings.length !== chunk.length) throw Error('embedding count mismatch');
          chunk.forEach((x, j) => { rec.vectors[x[0]] = env.embeddings[j]; });
        }
        rec.ok = true;
      } catch (e) { rec.error = String(e.message || e); }
    }
  } else {
    record.logprob_models = [];
    const st = PARTS.logprob.settings;
    for (const m of PARTS.logprob.models) {
      const rec = {tag: m.tag, ok: false, dists: {}, calls: 0};
      record.logprob_models.push(rec);
      if (installed.indexOf(m.tag) < 0) { rec.error = 'not installed (no download by this script)'; continue; }
      try {
        async function dist(row, prefix) {
          const node = nodeOptions(row, prefix), key = row.id + '|' + prefix.join('/');
          if (node.opts.length === 1) { rec.dists[key] = {[node.opts[0][0]]: 1}; return rec.dists[key]; }  // program-filled, no call
          let env;
          try {
            env = await call('/api/chat', {model: m.tag, messages: nodePrompt(row, prefix, node), stream: st.stream, think: st.think,
              logprobs: st.logprobs, top_logprobs: st.top_logprobs, options: st.options}, {model: m.tag, id: row.id, node: prefix.join('/')}, st.timeout_ms);
          } catch (e) {
            if (String(e.message || e) === 'call budget exceeded') throw e;
            // One failed node is recorded and scores 0 for its subtree; no retry, the run continues.
            (rec.node_errors = rec.node_errors || []).push({key, error: String(e.message || e)}); rec.dists[key] = {}; return {};
          }
          rec.calls++;
          const ld = letterDist(env, node.opts.length);
          if (ld === null) throw Error('response has no logprobs (Ollama did not return top_logprobs)');
          const d = {}; for (const [i, p] of Object.entries(ld.d)) d[node.opts[i][0]] = p / ld.z;
          rec.dists[key] = d; return d;
        }
        const top = (d, n) => Object.entries(d).filter(([, p]) => p >= st.min_p).sort((a, b) => b[1] - a[1]).slice(0, n).map(x => x[0]);
        for (const row of rows) {
          const root = await dist(row, []);
          for (const k of top(root, st.expand_kinds)) {
            if (k === 'NONE') continue;
            if (k === 'LAYOUT' && !S.visibleModules(row.ctx).length) continue;
            const d1 = await dist(row, [k]);
            if (k === 'NAV') for (const p of top(d1, st.expand_children)) {
              if (sectionsOf(+p.slice(1)).length) await dist(row, ['NAV', p]); else rec.dists[row.id + '|NAV/' + p] = {WHOLE: 1};
            }
            if (k === 'LAYOUT') for (const mod of top(d1, st.expand_children)) await dist(row, ['LAYOUT', mod]);
          }
        }
        rec.ok = true;
      } catch (e) { rec.error = String(e.message || e); }
    }
  }
  record.finished_utc = new Date().toISOString(); record.calls = calls;
  fs.writeFileSync(path.join(out, 'record.json'), JSON.stringify(record));
  console.log(JSON.stringify({part, calls, models: (record.embed_models || record.logprob_models).map(m => ({tag: m.tag, ok: m.ok, error: m.error || ''}))}));
})().catch(e => { fs.writeFileSync(path.join(out, 'aborted.txt'), String(e && e.stack || e)); console.error(e); process.exit(2); });
