// 用 JS 版工具跑 vectors.json，輸出精簡結果（stdout，JSON）。
const fs = require('fs'), path = require('path'), { Tools } = require('../test/load.js')
const V = JSON.parse(fs.readFileSync(path.join(__dirname, 'vectors.json'), 'utf8')), out = {}
const fv = r => r.facts.map(f => [f.fact_id, f.kind, f.subject, f.value === undefined ? null : f.value, f.time === undefined ? null : f.time])
for (const c of V.cases.energy) { const r = Tools.energyTrend(c.samples, c.opts); out[c.id] = { status: r.status, detail: r.detail, covered: r.coverage.covered } }
for (const c of V.cases.telemetry) { const r = Tools.telemetryLatest(c.field, c.unit, c.samples, c.now); out[c.id] = { status: r.status, facts: fv(r) } }
for (const c of V.cases.flightlog) { const r = Tools.flightlogSeries(c.field, c.unit, c.samples, c.t0, c.t1, c.gaps)
  out[c.id] = { status: r.status, facts: fv(r).filter(f => f[1] === 'value'), points: r.facts.length ? r.facts[0].points.map(p => [p.t, p.value]) : [] } }
for (const c of V.cases.alerts) { const r = Tools.alertHistory(c.events, c.filter, c.gaps)
  out[c.id] = { status: r.status, count: r.facts.length ? r.facts[0].value : null, by_level: r.facts.length ? r.facts[0].by_level : null, rows: r.facts[1] ? r.facts[1].rows.map(e => [e.t, e.text]) : [], has_critical: r.facts[1] ? r.facts[1].has_critical : false } }
for (const c of V.cases.manual) { const r = Tools.manualSearch(V.chunks, c.query, c.use_glossary ? V.glossary : {})
  out[c.id] = { status: r.status, hits: r.facts.filter(f => f.kind === 'doc_quote').map(f => [f.chunk_id, f.score]) } }
process.stdout.write(JSON.stringify(out))
