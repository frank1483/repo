'use strict';
// New focused helper controls only. Claude owns their first functional execution.
// node ui_agent/test/test_owned_group_v6.js <fresh-evidence-directory>
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert'), crypto = require('crypto');
assert.equal(process.argv.length, 3, 'exactly one fresh evidence directory required');
const out = path.resolve(process.argv[2]); fs.mkdirSync(out); // exclusive, no overwrite
const put = (name, value) => fs.writeFileSync(path.join(out, name), JSON.stringify(value, null, 2) + '\n', {flag: 'wx'});
const files = [__filename, path.join(__dirname, 'OwnedGroupCheck.js')];
put('inputs.json', files.map(file => ({file, sha256: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')})));
put('versions.json', {node: process.version, platform: process.platform, arch: process.arch});
const rows = [];
function check(name, fn) {
    try { fn(); rows.push({name, ok: true}); }
    catch (e) { rows.push({name, ok: false, error: String(e), stack: e.stack}); }
}
function fake() {
    return {
        _groupActive: false, _activeGroupCheckpoint: null, value: 0, undo: [], redo: ['seed'], calls: [],
        beginGroup() {
            if (this._groupActive) throw new Error('nested change group');
            const t = {value: this.value, undo: this.undo.slice(), redo: this.redo.slice()};
            this._groupActive = true; this._activeGroupCheckpoint = t; return t;
        },
        rollbackGroup(t) {
            assert(this._groupActive && this._activeGroupCheckpoint === t, 'invalid group rollback');
            this.calls.push(t); this.value = t.value; this.undo = t.undo.slice(); this.redo = t.redo.slice();
            this._groupActive = false; this._activeGroupCheckpoint = null;
        },
        commitGroup(t) {
            assert(this._groupActive && this._activeGroupCheckpoint === t);
            this._groupActive = false; this._activeGroupCheckpoint = null;
        }
    };
}
try {
    const ctx = {}; vm.createContext(ctx);
    vm.runInContext(fs.readFileSync(files[1], 'utf8').replace(/^\.pragma library\r?\n/, ''), ctx, {filename: files[1]});
    const run = ctx.run;
    check('no-group-success', () => {
        const s = fake(), r = run('ok', s, null, () => {});
        assert(r.ok && r.cleanup.attempted === 0 && !s.calls.length);
    });
    check('own-error-restores-state-and-history', () => {
        const s = fake(), r = run('fail', s, null, own => {
            own.beginGroup(); s.value = 4; s.undo = ['temp']; s.redo = []; throw Error('FIRST');
        });
        assert(!r.ok && r.error.includes('FIRST') && r.cleanup.rolledBack === 1 && !s._groupActive);
        assert.equal(s.value, 0); assert.deepEqual(s.undo, []); assert.deepEqual(s.redo, ['seed']);
    });
    check('successful-leak-fails-and-rolls-back', () => {
        const s = fake(), r = run('leak', s, null, own => { own.beginGroup(); s.value = 10; });
        assert(!r.ok && r.error === 'check left an owned group open' && s.value === 0 && s.calls.length === 1);
    });
    check('committed-token-is-never-rolled-back', () => {
        const s = fake(), r = run('commit', s, null, own => { const t = own.beginGroup(); s.value = 4; s.commitGroup(t); });
        assert(r.ok && s.value === 4 && !s.calls.length);
    });
    check('explicit-rollback-is-never-repeated', () => {
        const s = fake(), r = run('rollback', s, null, own => { s.rollbackGroup(own.beginGroup()); throw Error('AFTER'); });
        assert(!r.ok && r.error.includes('AFTER') && s.calls.length === 1 && r.cleanup.attempted === 0);
    });
    check('preexisting-foreign-token-preserved-on-nested-begin', () => {
        const s = fake(), foreign = s.beginGroup();
        const r = run('foreign', s, null, own => own.beginGroup());
        assert(!r.ok && r.error.includes('nested change group') && !s.calls.length && s._activeGroupCheckpoint === foreign);
    });
    check('setup-failure-preserves-foreign-token', () => {
        const s = fake(), foreign = s.beginGroup(); let work = false;
        const r = run('prepare', s, () => { throw Error('PREPARE'); }, () => { work = true; });
        assert(!r.ok && r.error.includes('PREPARE') && !work && !s.calls.length && s._activeGroupCheckpoint === foreign);
    });
    check('new-unowned-token-is-detected-and-not-rolled-back', () => {
        const s = fake(); let foreign;
        const r = run('unowned', s, null, () => { foreign = s.beginGroup(); });
        assert(!r.ok && r.cleanup.foreignActive && !s.calls.length && s._activeGroupCheckpoint === foreign);
    });
    check('rollback-failure-retains-first-error-and-cleanup-error', () => {
        const s = fake(); s.rollbackGroup = () => { throw Error('ROLLBACK'); };
        const r = run('double', s, null, own => { own.beginGroup(); throw Error('FIRST'); });
        assert(!r.ok && r.error.includes('FIRST') && r.cleanup.errors.length === 1 && r.cleanup.errors[0].includes('ROLLBACK'));
        assert.equal(r.cleanup.attempted, 1); assert.equal(r.cleanup.rolledBack, 0); assert(s._groupActive);
    });
    check('rollback-noop-is-reported', () => {
        const s = fake(); s.rollbackGroup = () => {};
        const r = run('noop', s, null, own => { own.beginGroup(); throw Error('FIRST'); });
        assert(!r.ok && r.error.includes('FIRST') && r.cleanup.errors[0].includes('still active') && r.cleanup.rolledBack === 0);
    });
    check('two-owned-tokens-clean-only-current-token', () => {
        const s = fake(); let second;
        const r = run('two', s, null, own => {
            s.rollbackGroup(own.beginGroup()); second = own.beginGroup(); throw Error('SECOND');
        });
        assert(!r.ok && s.calls.length === 2 && s.calls[1] === second && r.cleanup.attempted === 1 && !s._groupActive);
    });
    check('late-scope-use-cannot-open-another-group', () => {
        const s = fake(); let late;
        assert(run('close', s, null, own => { late = own; }).ok);
        assert.throws(() => late.beginGroup(), /closed check scope/); assert(!s._groupActive);
    });
    check('replacement-foreign-token-is-not-stolen', () => {
        const s = fake(); let foreign;
        const r = run('replace', s, null, own => {
            s.commitGroup(own.beginGroup()); foreign = s.beginGroup(); throw Error('FIRST');
        });
        assert(!r.ok && r.error.includes('FIRST') && r.cleanup.foreignActive && !s.calls.length && s._activeGroupCheckpoint === foreign);
    });
    check('next-check-can-open-after-injected-failure', () => {
        const s = fake(); assert(!run('first', s, null, own => { own.beginGroup(); throw Error('FIRST'); }).ok);
        const next = run('next', s, null, own => s.rollbackGroup(own.beginGroup()));
        assert(next.ok && !s._groupActive && s.calls.length === 2);
    });
    assert.equal(rows.length, 14, 'truncated suite');
} catch (e) {
    put('first_failure.json', {error: String(e), stack: e.stack});
    rows.push({name: 'suite-infrastructure', ok: false, error: String(e)});
}
const failed = rows.filter(row => !row.ok).length;
const results = {suite: 'owned-group-v6-batch5b2-part1', total: rows.length, failed, passed: rows.length - failed, cases: rows};
put('results.json', results); put('exit.json', {exit: failed ? 1 : 0, control_type: 'new-helper-only', external_model_calls: 0});
console.log(JSON.stringify({total: results.total, failed, evidence: out})); process.exitCode = failed ? 1 : 0;
