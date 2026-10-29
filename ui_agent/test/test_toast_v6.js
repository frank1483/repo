'use strict';
// First execution belongs to Claude. Uses production QML JS with mocks; no HTTP/Qt/Settings IO.
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const Core = require('./load_core');
const stateSource = fs.readFileSync(path.join(__dirname, '../qml/GcpAgentState.qml'), 'utf8');
const overlaySource = fs.readFileSync(path.join(__dirname, '../qml/GcpAgentOverlay.qml'), 'utf8');
function extract(src, name) {
    const start = src.indexOf('    function ' + name + '(');
    assert(start >= 0, 'missing production function ' + name);
    const lineEnd = src.indexOf('\n', start);
    if (src.slice(start, lineEnd).trimEnd().endsWith('}')) return src.slice(start, lineEnd).trim();
    const end = src.indexOf('\n    }', lineEnd);
    assert(end >= 0, 'missing function end ' + name);
    return src.slice(start, end + 6).trim();
}
const plain = x => JSON.parse(JSON.stringify(x));
function setup() {
    let loc = { page: 0, section: -1 }, syncs = 0;
    const S = { Core, JSON, Object, Array, Number, Math, Error, isFinite, console,
        GcpTheme: { font: { textScale: 1 } }, revision: 0, _modules: {}, _overrides: {}, _cancelRedo: [],
        undoStack: [], redoStack: [], _groupActive: false, _savedLoaded: true, _savedCorrupt: false,
        _savedFingerprint: '{"overrides":{},"textScale":1}', _apply() {},
        _layoutSettings: { savedLayoutJson: '', sync() { syncs++; } },
        shell: { agentLocation: () => ({ ...loc }), agentGoTo(page, section) { loc = { page, section }; return true; } }, qsTr: s => s };
    Object.defineProperties(S, {
        textScale: { get: () => S.GcpTheme.font.textScale },
        hasUnsavedChanges: { get: () => S.layoutFingerprint() !== S._savedFingerprint }
    });
    vm.createContext(S);
    vm.runInContext(['snapshot', '_restore', 'checkedLayout', 'layoutFingerprint', 'beginChange',
        'beginGroup', 'commitGroup', 'rollbackGroup', 'undo', 'redo', 'resetAll', 'setTextScale',
        'loadSavedLayout', 'saveCurrentLayout', 'undoHint'].map(n => extract(stateSource, n)).join('\n'), S);
    vm.runInContext('String.prototype.arg = function(v) { return String(this).replace(/%[1-9]/, String(v)); }', S);
    const toast = { opacity: 0, mode: '', action: '', entryKey: '', snapshotKey: '' };
    const timer = { running: false, restarts: 0, stop() { this.running = false; }, restart() { this.running = true; this.restarts++; } };
    const O = { GcpAgentState: S, Core, toast, toastTimer: timer, JSON, Date, console,
        busy: false, _transaction: null, choices: [], pendingText: '', messageText: '', changeLog: [],
        open: true, qsTr: s => s, executeSteps() { throw Error('unexpected transaction in toast test'); } };
    O.root = O;
    Object.defineProperty(O, 'canSaveLayout', { get: () => !O.busy && S.hasUnsavedChanges });
    vm.createContext(O);
    vm.runInContext(['dismissToast', 'showHistoryToast', 'showToast', 'toastActionAvailable',
        'performToastAction', 'recordChange', 'execute', 'done'].map(n => extract(overlaySource, n)).join('\n'), O);
    vm.runInContext('String.prototype.arg = function(v) { return String(this).replace(/%[1-9]/, String(v)); }', O);
    function change(kind, mutate) {
        const before = S.layoutFingerprint(), oldPage = loc.page, oldSection = loc.section;
        S.beginChange(kind, kind);
        mutate();
        O.done({ label_zh: kind }, 'test', before !== S.layoutFingerprint(), oldPage !== loc.page || oldSection !== loc.section);
    }
    return { S, O, toast, timer, change, loc: () => ({ ...loc }), syncs: () => syncs };
}
let count = 0;
function test(name, run) { run(); count++; console.log('PASS ' + name); }
test('navigation has a timed return and does not enable save', () => {
    const { S, O, toast, timer, change } = setup();
    change('navigation', () => S.shell.agentGoTo(1, -1));
    assert.equal(toast.mode, 'navigation'); assert.equal(toast.action, 'undo');
    assert(timer.running); assert(!O.canSaveLayout); assert(!S.hasUnsavedChanges);
});
test('return restores only this navigation; no layout write', () => {
    const { S, O, toast, change, loc, syncs } = setup();
    change('navigation', () => S.shell.agentGoTo(1, -1)); O.performToastAction();
    assert.equal(loc().page, 0); assert.equal(toast.opacity, 0); assert.equal(syncs(), 0); assert.equal(S.undoStack.length, 0);
});
test('navigation registration revisions do not disable the correct return', () => {
    const { S, O, change } = setup();
    change('navigation', () => S.shell.agentGoTo(1, -1)); S.revision++;
    assert(O.toastActionAvailable());
});
test('manual navigation cannot make an old return undo another screen', () => {
    const { S, O, change, loc } = setup();
    change('navigation', () => S.shell.agentGoTo(1, -1)); S.shell.agentGoTo(3, -1);
    assert(!O.toastActionAvailable()); O.performToastAction(); assert.equal(loc().page, 3); assert.equal(S.undoStack.length, 1);
});
test('layout toast replaces a running navigation timer with a persistent toast', () => {
    const { S, O, toast, timer, change } = setup();
    change('navigation', () => S.shell.agentGoTo(1, -1)); change('layout', () => S.setTextScale(1.15));
    assert.equal(toast.mode, 'layout'); assert(!timer.running); assert(O.canSaveLayout);
});
test('undo layout keeps a persistent redo even at the saved layout', () => {
    const { S, O, toast, timer, change } = setup();
    change('layout', () => S.setTextScale(1.15)); O.performToastAction();
    assert.equal(S.textScale, 1); assert.equal(toast.mode, 'layout'); assert.equal(toast.action, 'redo');
    assert.equal(toast.opacity, 1); assert(!timer.running); assert(!O.canSaveLayout);
});
test('redo layout restores the adjustment and enables save', () => {
    const { S, O, toast, change } = setup();
    change('layout', () => S.setTextScale(1.15)); O.performToastAction(); O.performToastAction();
    assert.equal(S.textScale, 1.15); assert.equal(toast.action, 'undo'); assert(O.canSaveLayout);
});
test('close retains unsaved layout, saved data, undo and redo', () => {
    const { S, O, toast, timer, change, syncs } = setup();
    change('layout', () => S.setTextScale(1.15));
    const before = JSON.stringify({ snap: S.snapshot(), undo: S.undoStack, redo: S.redoStack });
    O.dismissToast(); assert.equal(toast.opacity, 0); assert(!timer.running); assert(O.canSaveLayout);
    assert.equal(JSON.stringify({ snap: S.snapshot(), undo: S.undoStack, redo: S.redoStack }), before); assert.equal(syncs(), 0);
});
test('explicit save after close clears dirty state and logs the save', () => {
    const { S, O, change, syncs } = setup();
    change('layout', () => S.setTextScale(1.15)); O.dismissToast(); O.execute({ kind: 'layout_save_current' }, 'test');
    assert.equal(syncs(), 1); assert(!S.hasUnsavedChanges); assert(!O.canSaveLayout); assert.equal(O.changeLog.length, 2);
});
test('save in a clean navigation-only state does not write Settings', () => {
    const { S, O, change, syncs } = setup();
    change('navigation', () => S.shell.agentGoTo(1, -1)); O.execute({ kind: 'layout_save_current' }, 'test');
    assert.equal(syncs(), 0); assert(!O.canSaveLayout);
});
test('existing unsaved layout remains saveable after navigation', () => {
    const { S, O, toast, change } = setup();
    change('layout', () => S.setTextScale(1.15)); change('navigation', () => S.shell.agentGoTo(1, -1));
    assert.equal(toast.mode, 'navigation'); assert(O.canSaveLayout);
});
test('module overrides, not just text scale, enable saving', () => {
    const { S, O, change } = setup();
    change('layout', () => { S._overrides = { windGauge: { rx: 0.1, ry: 0, scale: 1, hidden: false } }; S.revision++; });
    assert(O.canSaveLayout); O.performToastAction(); assert(!O.canSaveLayout);
});
test('save then undo is dirty relative to the new saved layout', () => {
    const { S, O, toast, change } = setup();
    change('layout', () => S.setTextScale(1.15)); O.execute({ kind: 'layout_save_current' }, 'test');
    assert(O.toastActionAvailable()); O.performToastAction();
    assert.equal(S.textScale, 1); assert(O.canSaveLayout); assert.equal(toast.action, 'redo');
});
test('stale stack does not let the toast undo a different action', () => {
    const { S, O, change } = setup(); change('layout', () => S.setTextScale(1.15));
    S.beginChange('other', 'layout'); const count = S.undoStack.length;
    assert(!O.toastActionAvailable()); O.performToastAction(); assert.equal(S.undoStack.length, count); assert.equal(S.textScale, 1.15);
});
test('busy state blocks toast actions and saving', () => {
    const { S, O, change } = setup(); change('layout', () => S.setTextScale(1.15)); O.busy = true;
    assert(!O.canSaveLayout); O.performToastAction(); assert.equal(S.textScale, 1.15);
});
test('failed Settings recovery keeps unsaved adjustment and logs no success', () => {
    const { S, O, change, syncs } = setup(); change('layout', () => S.setTextScale(1.15)); S._savedCorrupt = true;
    O.execute({ kind: 'layout_save_current' }, 'test'); assert.equal(syncs(), 0); assert(O.canSaveLayout); assert.equal(O.changeLog.length, 1);
});
test('change log retains the action and undo even after undo stack removal', () => {
    const { S, O, change } = setup(); change('layout', () => S.setTextScale(1.15)); O.performToastAction();
    assert.equal(S.undoStack.length, 0); assert.equal(O.changeLog.length, 2); assert(O.changeLog[1].label.includes('layout'));
});
test('change log bounds session memory without changing history stacks', () => {
    const { S, O } = setup(); for (let i = 0; i < 60; i++) O.recordChange('row ' + i);
    assert.equal(O.changeLog.length, 50); assert.equal(O.changeLog[0].label, 'row 59'); assert.equal(S.undoStack.length, 0);
});
console.log('PASS ' + count + ' new toast controls under JS mocks; Qt bindings/rendering/durable Settings remain unverified');
