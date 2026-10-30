'use strict';
// New focused engineering controls. No backend, device, Qt or existing suite execution.
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
function load(file) {
    const context = {}; vm.createContext(context);
    vm.runInContext(fs.readFileSync(file, 'utf8').replace(/^\.pragma[^\n]*\n/, ''), context, {filename: file});
    return context;
}
const Core = load(path.join(root, 'qml/GcpAgentCore.js'));
const Loop = load(path.join(root, 'qml/GcpAgentLoop.js'));
const Verify = load(path.join(root, 'qml/GcpAgentVerifier.js'));
const Catalog = load(path.join(__dirname, '../qml/GcpAgentCatalog.js'));
const clone = x => JSON.parse(JSON.stringify(x));
const choice = 'GOAL_MINIVIEW_READABLE';
function host() {
    const goal = Loop.goalTemplate('讓小地圖看得清楚一點', {page: 1, modules: {miniView: {registered: true, visible: true}}});
    return {revision: 4, candidates: clone(goal.candidates),
        goal: {kind: 'readable', minWidth: 160, minHeight: 80, allowMove: true, allowShrink: true, allowNavigate: true},
        snapshot: {page: 1, section: -1, viewport: {x: 0, y: 0, w: 800, h: 600}, modules: {
            miniView: {page: 1, visible: true, opacity: 1, locked: false, scale: 1, paintOrder: 1,
                rect: {x: 100, y: 100, w: 200, h: 120}}}},
        frame: {mapping: 'translation-only', base: {x: 100, y: 100, w: 200, h: 120},
            area: {w: 800, h: 600}, origin: {x: 0, y: 0},
            override: {dx: 0, dy: 0, scale: 1, hidden: false}, others: []}};
}
const spec = h => Catalog.buildReadableSpec(choice, h, Core);
let count = 0;
function test(name, fn) { fn(); ++count; console.log('PASS ' + name); }
function rejected(name, mutate, reason) {
    test(name, () => { const h = host(); mutate(h); assert.throws(() => spec(h), reason); });
}
test('Core goal template accepted; detached host expectation and repair permissions', () => {
    const h = host(), p = spec(h);
    assert.equal(p.steps.length, 1); assert.equal(p.steps[0], choice);
    assert.equal(p.expected.modules[0].minWidth, 160);
    assert(p.catalog.some(c => c.id === 'REPAIR_MINIVIEW_SHRINK'));
    assert(p.catalog.some(c => c.id === 'REPAIR_MINIVIEW_PAGE'));
    h.goal.minWidth = 999; h.snapshot.page = 8;
    assert.equal(p.expected.modules[0].minWidth, 160); assert.equal(p.guard.page, 1);
});
rejected('model expectation injection rejected', h => h.candidates[0].expected = {page: 0}, /expectations/);
rejected('transaction baseline injection rejected', h => h.candidates[0].before = {}, /expectations/);
rejected('model repair scope injection rejected', h => h.candidates[0].repairFor = [choice], /expectations/);
rejected('duplicate trusted IDs rejected', h => h.candidates.push(clone(h.candidates[0])), /duplicate/);
rejected('different module cannot reuse goal ID', h => h.candidates[0].module = 'attitude', /mismatch/);
rejected('different action cannot reuse goal ID', h => h.candidates[0].factor = 2, /mismatch/);
rejected('missing minimum does not invent readability', h => delete h.goal.minWidth, /minimums/);
rejected('invalid minimum rejected', h => h.goal.minHeight = NaN, /minimums/);
rejected('missing repair permission rejected', h => delete h.goal.allowShrink, /permissions/);
rejected('hidden target rejected', h => h.snapshot.modules.miniView.visible = false, /visible/);
rejected('locked snapshot rejected', h => h.snapshot.modules.miniView.locked = true, /unlocked/);
rejected('off-page target requires fresh measurements', h => h.snapshot.page = 0, /current/);
rejected('stale geometry rejected', h => h.snapshot.modules.miniView.rect.x += 2, /does not match/);
rejected('nonfinite frame rejected', h => h.frame.override.dx = Infinity, /finite/);
rejected('unsupported transform rejected', h => h.frame.mapping = 'rotated', /supported/);
rejected('huge finite geometry cannot make Core freeSpot unbounded', h => h.frame.area.w = 1e100, /32768/);
rejected('missing revision rejected', h => delete h.revision, /revision/);
rejected('oversized obstacle inventory rejected', h => h.frame.others = Array(129).fill({x: 0, y: 0, w: 1, h: 1}), /bounded/);
test('all repairs require their explicit host permission', () => {
    const h = host(); h.goal.allowMove = h.goal.allowShrink = h.goal.allowNavigate = false;
    assert.equal(spec(h).catalog.length, 1);
});
test('freeSpot no-space fallback is never advertised as a valid move', () => {
    const h = host(); h.frame.others = [{x: 0, y: 0, w: 800, h: 600}];
    assert(!spec(h).catalog.some(c => c.id.startsWith('REPAIR_MINIVIEW_MOVE_')));
});
test('shrink never weakens original readable minimum', () => {
    const h = host(); h.goal.minWidth = 230;
    const p = spec(h); assert(!p.catalog.some(c => c.id === 'REPAIR_MINIVIEW_SHRINK'));
    assert.equal(p.expected.modules[0].minWidth, 230);
});
test('move repairs are unique and scoped to geometry failures', () => {
    const repairs = spec(host()).catalog.filter(c => c.id.startsWith('REPAIR_MINIVIEW_MOVE_'));
    assert(repairs.length > 0);
    const points = new Set();
    for (const c of repairs) {
        const h = host(), before = Core.layoutTarget('scale', h.frame.base, h.frame.area, h.frame.override, 1.25, [], Core.MODULES.find(p => p.id === 'miniView'));
        const next = Core.layoutTarget('move', h.frame.base, h.frame.area, before, c.action.region, [], Core.MODULES.find(p => p.id === 'miniView'));
        const key = next.dx + ':' + next.dy + ':' + next.scale;
        assert(!points.has(key)); points.add(key);
        assert.deepEqual(clone(c.repairFor), [choice]);
        assert(!c.failureCodes.includes('TEXT_TRUNCATED'));
        assert.equal(c.expected.modules[0].minWidth, 160);
    }
});
test('common viewport translation is checked against measured AABB', () => {
    const h = host(); h.frame.origin = {x: 10, y: 15};
    h.snapshot.modules.miniView.rect.x += 10; h.snapshot.modules.miniView.rect.y += 15;
    assert.equal(spec(h).guard.revision, 4);
});
function runLoop(repair) {
    const h = host(), initial = clone(h.snapshot);
    h.frame.others = [{x: 300, y: 100, w: 80, h: 80}];
    h.snapshot.modules.blocker = {page: 1, visible: true, opacity: 1, locked: false, scale: 1,
        paintOrder: 2, occludes: true, rect: clone(h.frame.others[0])};
    let state = clone(h.snapshot), ov = clone(h.frame.override), begins = 0, commits = 0, rollbacks = 0, proposes = 0;
    const p = spec(h), candidateIds = new Set(p.catalog.map(c => c.id));
    const loop = Loop.create(p, {
        begin() { ++begins; return 'group'; }, commit() { ++commits; },
        rollback() { ++rollbacks; state = clone(initial); },
        checkpoint() { return {state: clone(state), ov: clone(ov)}; },
        restore(c) { state = clone(c.state); ov = clone(c.ov); },
        snapshot() { return clone(state); }, verify: Verify.verify,
        execute(a, done) {
            if (a.kind === 'nav') { state.page = a.page; state.section = a.section; }
            else {
                ov = Core.layoutTarget(a.op, h.frame.base, h.frame.area, ov, a.op === 'move' ? a.region : a.factor,
                    h.frame.others, Core.MODULES.find(m => m.id === 'miniView'));
                const m = state.modules.miniView;
                m.scale = ov.scale; m.rect = {x: 100 + ov.dx, y: 100 + ov.dy, w: 200 * ov.scale, h: 120 * ov.scale};
            }
            done();
        },
        propose(request, done) {
            ++proposes;
            assert(request.failures.some(f => f.code === 'OVERLAP'));
            assert(request.candidates.every(c => candidateIds.has(c.id)));
            const move = request.candidates.find(c => c.id.startsWith('REPAIR_MINIVIEW_MOVE_'));
            assert(move); done(repair(move.id));
        }
    });
    assert.equal(begins, 0); loop.start(true);
    return {result: loop.state(), commits, rollbacks, proposes};
}
test('new catalog + production Loop/Verifier: overlap repaired, one commit', () => {
    const r = runLoop(id => ({steps: [{choice_id: id}]}));
    assert.equal(r.result.phase, 'complete'); assert.equal(r.commits, 1);
    assert.equal(r.rollbacks, 0); assert.equal(r.proposes, 1);
    assert.equal(r.result.executions, 2);
});
test('production Loop rejects extra repair expectation and rolls back whole group', () => {
    const r = runLoop(id => ({steps: [{choice_id: id, expected: {page: 1}}]}));
    assert.equal(r.result.phase, 'failed'); assert.equal(r.commits, 0); assert.equal(r.rollbacks, 1);
});
test('production Loop rejects unknown repair ID and rolls back whole group', () => {
    const r = runLoop(() => ({steps: [{choice_id: 'NAV_10'}]}));
    assert.equal(r.result.phase, 'failed'); assert.equal(r.commits, 0); assert.equal(r.rollbacks, 1);
});
console.log(JSON.stringify({suite: 'catalog_v6', cases: count, status: 'PASS', backend_calls: 0, qt: false}));
