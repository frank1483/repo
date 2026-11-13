import QtQuick
import QGroundControl.GCP
import "../OwnedGroupCheck.js" as Checks

// New controls only. Do not invoke AdapterV6's already-passed 20 checks here.
Window {
    id: win
    width: 400; height: 300; visible: true
    property bool ran: false
    property string resultJson: ""
    property var rows: []
    Item {
        id: viewport
        width: 400; height: 300
        Rectangle { id: mini; width: 80; height: 40; color: "red" }
        Rectangle { id: wind; x: 150; width: 30; height: 30; color: "blue" }
    }
    QtObject {
        id: host
        property int page: 1
        property int section: -1
        function agentLocation() { return {page: page, section: section} }
        function agentGoTo(p, s) { page = p; section = s; return true }
    }
    function need(ok, why) { if (!ok) throw new Error(why) }
    function snap() { return JSON.stringify(GcpAgentState.snapshot()) }
    function history() { return JSON.stringify([GcpAgentState.undoStack, GcpAgentState.redoStack]) }
    function check(name, work) {
        rows.push(Checks.run(name, GcpAgentState, null, work))
    }
    function run() {
        if (ran) throw new Error("first-execution harness cannot run twice")
        ran = true
        GcpAgentState.shell = host
        GcpAgentState.register("miniView", mini, viewport)
        GcpAgentState.register("windGauge", wind, viewport)
        check("owned-throw-restores-real-item-and-redo", function() {
            GcpAgentState.beginChange("seed redo")
            GcpAgentState.setOverride("miniView", {dx: 5, dy: 6, scale: 1, hidden: false})
            GcpAgentState.undo(1)
            var before = snap(), stacks = history(), mapped = mini.mapToItem(viewport, 0, 0)
            var row = Checks.run("injected", GcpAgentState, null, function(scope) {
                scope.beginGroup()
                GcpAgentState.beginChange("temporary")
                GcpAgentState.setOverride("miniView", {dx: 35, dy: 12, scale: 1, hidden: false})
                var moved = mini.mapToItem(viewport, 0, 0)
                need(moved.x !== mapped.x || moved.y !== mapped.y, "real item was not moved")
                throw new Error("FIRST_ASSERTION")
            })
            need(!row.ok && row.error.indexOf("FIRST_ASSERTION") >= 0, "first failure lost")
            need(row.cleanup.rolledBack === 1 && !row.cleanup.errors.length, "owned rollback")
            need(snap() === before && history() === stacks, "snapshot/history not restored")
            var restored = mini.mapToItem(viewport, 0, 0)
            need(restored.x === mapped.x && restored.y === mapped.y && !GcpAgentState._groupActive,
                 "real item/group not restored")
        })
        check("next-check-can-open-after-failure", function(scope) {
            var token = scope.beginGroup()
            GcpAgentState.rollbackGroup(token)
        })
        check("successful-check-with-leaked-group-is-failed-and-restored", function() {
            var before = snap(), stacks = history()
            var row = Checks.run("leak", GcpAgentState, null, function(scope) {
                scope.beginGroup()
                GcpAgentState.beginChange("leaked")
                host.agentGoTo(8, 11)
            })
            need(!row.ok && row.error === "check left an owned group open", "silent success leak")
            need(row.cleanup.rolledBack === 1 && snap() === before && history() === stacks, "leak recovery")
        })
        check("already-committed-token-not-rolled-back", function(scope) {
            var before = snap(), row = Checks.run("commit", GcpAgentState, null, function(inner) {
                var token = inner.beginGroup()
                GcpAgentState.beginChange("move wind")
                GcpAgentState.setOverride("windGauge", {dx: 3, dy: 4, scale: 1, hidden: false})
                GcpAgentState.commitGroup(token, "committed")
            })
            need(row.ok && row.cleanup.attempted === 0 && snap() !== before, "committed token touched")
            GcpAgentState.undo(1)
            need(snap() === before, "committed change undo")
        })
        check("already-rolled-back-token-not-rolled-back-twice", function() {
            var row = Checks.run("rollback", GcpAgentState, null, function(scope) {
                var token = scope.beginGroup()
                GcpAgentState.rollbackGroup(token)
                throw new Error("AFTER_ROLLBACK")
            })
            need(!row.ok && row.error.indexOf("AFTER_ROLLBACK") >= 0 && row.cleanup.attempted === 0,
                 "stale token rollback")
        })
        check("nested-begin-does-not-steal-foreign-group", function(scope) {
            var foreign = scope.beginGroup(), before = snap(), stacks = history()
            var row = Checks.run("foreign", GcpAgentState, null, function(inner) { inner.beginGroup() })
            need(!row.ok && row.error.indexOf("nested change group") >= 0, "nested error lost")
            need(row.cleanup.attempted === 0 && GcpAgentState._activeGroupCheckpoint === foreign,
                 "foreign token stolen")
            need(snap() === before && history() === stacks, "foreign state changed")
            GcpAgentState.rollbackGroup(foreign)
        })
        check("setup-throw-preserves-foreign-token", function(scope) {
            var foreign = scope.beginGroup(), called = false
            var row = Checks.run("setup", GcpAgentState, function() { throw new Error("SETUP_FAILURE") },
                                 function() { called = true })
            need(!row.ok && row.error.indexOf("SETUP_FAILURE") >= 0 && !called, "setup failure")
            need(row.cleanup.attempted === 0 && GcpAgentState._activeGroupCheckpoint === foreign, "setup stole token")
            GcpAgentState.rollbackGroup(foreign)
        })
        check("multiple-owned-tokens-only-active-token-is-cleaned", function() {
            var before = snap(), stacks = history()
            var row = Checks.run("multiple", GcpAgentState, null, function(scope) {
                var first = scope.beginGroup()
                GcpAgentState.rollbackGroup(first)
                scope.beginGroup()
                GcpAgentState.beginChange("temporary second")
                host.agentGoTo(3, -1)
                throw new Error("SECOND_ASSERTION")
            })
            need(!row.ok && row.error.indexOf("SECOND_ASSERTION") >= 0, "second assertion")
            need(row.cleanup.attempted === 1 && row.cleanup.rolledBack === 1 && !row.cleanup.errors.length,
                 "inactive token touched")
            need(snap() === before && history() === stacks && !GcpAgentState._groupActive, "second recovery")
        })
        var failed = rows.filter(function(row) { return !row.ok }).length
        resultJson = JSON.stringify({schema: 1, suite: "qt-owned-group-v6-batch5b2-part1", cases: rows,
            total: rows.length, failed: failed, passed: rows.length - failed, modelCalls: 0,
            adapterRegressionRun: false, rendererPixelsChecked: false})
    }
}
