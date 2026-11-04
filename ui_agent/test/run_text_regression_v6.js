// New 0400 fixtures only. Actual Core + Loop + Overlay.submit, simulated host ports.
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm'), crypto = require('crypto');
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const root = path.resolve(__dirname, '..');
const evidence = process.argv[2];
if (!evidence) throw Error('usage: node ui_agent/test/run_text_regression_v6.js <NEW evidence directory>');
// mkdir without recursive deliberately refuses reuse, preserving first execution.
fs.mkdirSync(evidence);
const sourceFiles = ['qml/GcpAgentCore.js', 'qml/GcpAgentLoop.js', 'qml/GcpAgentOverlay.qml',
    'test/text_regression_v6_0400.jsonl', 'test/run_text_regression_v6.js'];
const inputHashes = Object.fromEntries(sourceFiles.map(p => [p, sha(fs.readFileSync(path.join(root, p)))]));
function load(name) {
    const c = {};
    vm.createContext(c);
    vm.runInContext(fs.readFileSync(path.join(root, 'qml', name), 'utf8').replace(/^\.pragma[^\n]*\n/, ''), c);
    return c;
}
const Core = load('GcpAgentCore.js'), Loop = load('GcpAgentLoop.js');
const overlay = fs.readFileSync(path.join(root, 'qml/GcpAgentOverlay.qml'), 'utf8');
const start = overlay.indexOf('    function submit('), end = overlay.indexOf('\n    }', start);
if (start < 0 || end < 0) throw Error('Overlay.submit source boundary missing');
const submitSource = overlay.slice(start, end + 6).trim();
const rows = fs.readFileSync(path.join(root, 'test/text_regression_v6_0400.jsonl'), 'utf8')
    .split(/\r?\n/).filter(s => s.trim()).map(JSON.parse);
const seen = new Set(), results = [];
const copy = x => JSON.parse(JSON.stringify(x));
function fixture(row) {
    const events = [], calls = [];
    let current;
    const ctx = Object.assign({ page: 1, section: -1, textScale: 1,
        modules: { miniView: { registered: true, visible: true }, windGauge: { registered: true, visible: true } } }, copy(row.ctx || {}));
    const o = { Core, ReadableLoop: Loop, Date, JSON, busy: false, pendingText: row.pending || '',
        modelEnabled: false, modelAlways: false, themeEditor: { cancel() { calls.push('theme_cancel'); } },
        clearConfirmation() { calls.push('clear_card'); }, context() { return copy(ctx); },
        recordGate(e) { events.push(copy(e)); },
        cancelWaiting() { o.pendingText = ''; current = { route: 'cancel' }; },
        requestReadableConfirmation(text, candidates) {
            current = { route: 'goal', ids: candidates.map(c => c.id), confirmation_requested: true };
        },
        finish(r, model) {
            if (model !== null) throw Error('model unexpectedly used');
            const d = r.rule;
            const ids = d.decision === 'SELECT' ? (d.steps ? d.steps.map(s => s.choice_id) : [d.choice_id]) : [];
            const gate = Core.gateSelection(d, r.candidates, ctx);
            current = { route: 'analysis', decision: d.decision, ids,
                candidate_ids: r.candidates.map(c => c.id), pending: r.pending_text || '',
                pending_original: r.pending_intent || '', gate_ok: gate.ok,
                safety_hold: r.safety_hold === true };
        },
        callModel() { throw Error('model backend forbidden'); }
    };
    vm.createContext(o);
    vm.runInContext(submitSource, o);
    return {
        run(text) {
            current = null;
            o.messageText = '';
            o.submit(text);
            if (!current) current = events.length && events[events.length - 1].ok === false ?
                { route: 'blocked' } : { route: 'clarify_goal', message: o.messageText };
            // Explicit pending handoff simulation; finish/executor/Qt are outside scope.
            if (current.route === 'analysis') o.pendingText = current.pending;
            return { ...copy(current), events: copy(events), calls: calls.slice() };
        }
    };
}
function compare(ex, actual) {
    const errors = [];
    for (const [key, value] of Object.entries(ex)) {
        if (key === 'contains') {
            for (const id of value) if (!(actual.candidate_ids || []).includes(id)) errors.push('missing candidate ' + id);
        } else if (key === 'message_contains') {
            for (const s of value) if (!(actual.message || '').includes(s)) errors.push('missing message ' + s);
        } else if (JSON.stringify(actual[key]) !== JSON.stringify(value)) errors.push(key + ' expected ' + JSON.stringify(value) + ' got ' + JSON.stringify(actual[key]));
    }
    if (actual.route === 'analysis' && actual.decision === 'SELECT' && actual.gate_ok !== true) errors.push('selected rule action failed shared post gate');
    return errors;
}
for (const row of rows) {
    if (!/^UITEXT0400-\d{3}$/.test(row.id) || seen.has(row.id)) throw Error('invalid/duplicate fixture ID');
    seen.add(row.id);
    let steps = [], errors = [];
    try {
        const f = fixture(row), turns = row.turns || [{ text: row.text, expect: row.expect }];
        for (const [i, turn] of turns.entries()) {
            const actual = f.run(turn.text), failures = compare(turn.expect, actual);
            steps.push({ turn: i + 1, text: turn.text, actual, failures });
            errors.push(...failures.map(s => 'turn ' + (i + 1) + ': ' + s));
        }
    } catch (e) { errors.push(String(e.stack || e)); }
    results.push({ id: row.id, group: row.group, passed: errors.length === 0, errors, steps });
}
const report = { scope: 'new engineering text fixtures; actual Core/Loop/Overlay.submit, simulated host and pending handoff; no Qt/executor/model/API/device/quality estimate',
    node: process.version, source_sha256: inputHashes, old_corpus_executed: false,
    total: results.length, passed: results.filter(r => r.passed).length, results };
fs.writeFileSync(path.join(evidence, 'result.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
console.log(JSON.stringify({ scope: report.scope, total: report.total, passed: report.passed,
    failures: results.filter(r => !r.passed).map(r => ({ id: r.id, errors: r.errors })) }));
process.exitCode = report.passed === report.total ? 0 : 1;
