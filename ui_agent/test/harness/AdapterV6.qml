import QtQuick
import QGroundControl.GCP
import "../../qml/GcpAgentSnapshot.js" as Snapshot
import "../OwnedGroupCheck.js" as Checks

// A real QQuickItem scene. No Overlay/model/network/flight dependency.
Window {
    id: win
    width: 900; height: 700; visible: true
    property string resultJson: ""
    property bool ran: false
    property var rows: []
    property var policies: [
        {id: "miniView", page: 1, locked: false},
        {id: "attitude", page: 1, locked: false},
        {id: "compass", page: 1, locked: false}
    ]
    Item {
        id: viewport
        width: 800; height: 600
        Item {
            id: front
            x: 10; y: 20; z: 2
            transformOrigin: Item.TopLeft
            Rectangle {
                id: a
                objectName: "adapterA"
                x: 30; y: 40; width: 80; height: 40
                transformOrigin: Item.TopLeft
                color: "red"
            }
            Rectangle {
                id: c
                objectName: "adapterC"
                x: 130; y: 40; width: 30; height: 30
                color: "green"
            }
        }
        Item {
            id: back
            x: 250; y: 100; z: 1
            Rectangle {
                id: b
                x: 5; y: 7; width: 50; height: 30; z: 999
                color: "blue"
            }
        }
    }
    Item { id: outside; width: 10; height: 10 }
    QtObject {
        id: host
        property int page: 1
        property int section: -1
        function agentLocation() { return {page: page, section: section} }
        function agentGoTo(p, s) { page = p; section = s; return true }
    }
    function requireValue(ok, detail) {
        if (!ok) throw new Error(detail || "assertion failed")
    }
    function near(got, expected, label) {
        requireValue(typeof got === "number" && isFinite(got) && Math.abs(got - expected) < 0.0001,
                     label + ": " + got + " expected " + expected)
    }
    function rect(got, x, y, w, h) {
        near(got.x, x, "x"); near(got.y, y, "y")
        near(got.w, w, "w"); near(got.h, h, "h")
    }
    function rejected(fn, text) {
        var caught = ""
        try { fn() } catch (e) { caught = String(e) }
        requireValue(caught.indexOf(text) >= 0, "expected rejection " + text + "; got " + caught)
    }
    function capture(registry) {
        return Snapshot.capture(viewport, registry || {
            miniView: {item: a}, attitude: {item: b}, compass: {item: c}
        }, policies, host.agentLocation(), function() { return {scale: 1} })
    }
    function cleanScene() {
        front.x = 10; front.y = 20; front.z = 2; front.scale = 1
        front.opacity = 1; front.visible = true; front.clip = false; front.layer.enabled = false
        back.z = 1; back.layer.enabled = false
        a.x = 30; a.y = 40; a.z = 0; a.scale = 1; a.rotation = 0
        a.opacity = 1; a.visible = true; a.enabled = true; a.layer.enabled = false
        c.z = 0; b.z = 999
        viewport.width = 800; viewport.height = 600; viewport.layer.enabled = false
        host.page = 1; host.section = -1
        qtOrder.stackAfter(c, a)
    }
    property var _checkScope: null
    function beginOwnedGroup() {
        if (!_checkScope) throw new Error("State group outside a check scope")
        return _checkScope.beginGroup()
    }
    function check(name, fn) {
        rows.push(Checks.run(name, GcpAgentState, cleanScene, function(scope) {
            _checkScope = scope
            try { fn() } finally { _checkScope = null }
        }))
    }
    function run() {
        if (ran) throw new Error("first-execution harness cannot run twice")
        ran = true
        check("translation-and-coverage", function() {
            var s = capture()
            rect(s.modules.miniView.rect, 40, 60, 80, 40)
            rect(s.modules.attitude.rect, 255, 107, 50, 30)
            requireValue(s.geometryCoverage === "registered-items-aabb", "coverage")
            requireValue(s.paintOrderCoverage === "ordinary-qquickitems-single-root", "paint coverage")
            requireValue(s.page === 1 && s.section === -1, "location")
        })
        check("rotation-aabb", function() {
            a.rotation = 90
            rect(capture().modules.miniView.rect, 0, 60, 40, 80)
        })
        check("nested-nonidentity-scale", function() {
            front.scale = 1.5; a.scale = 1.25
            rect(capture().modules.miniView.rect, 55, 80, 150, 75)
        })
        check("parent-z-beats-descendant-z", function() {
            a.z = -99
            var s = capture().modules
            requireValue(s.miniView.paintOrder > s.attitude.paintOrder, "cross-parent hierarchy ignored")
        })
        check("parent-z-change-reverses-order", function() {
            front.z = 0
            var s = capture().modules
            requireValue(s.miniView.paintOrder < s.attitude.paintOrder, "parent z not observed")
        })
        check("same-z-stackAfter-reorder", function() {
            var before = capture().modules
            requireValue(before.miniView.paintOrder < before.compass.paintOrder, "fixture order")
            qtOrder.stackAfter(a, c)
            var after = capture().modules
            requireValue(after.miniView.paintOrder > after.compass.paintOrder, "same-z reorder not observed")
        })
        check("negative-child-below-parent", function() {
            a.z = -1; c.z = 0
            var s = capture({miniView: {item: a}, attitude: {item: front}, compass: {item: c}}).modules
            requireValue(s.miniView.paintOrder < s.attitude.paintOrder &&
                         s.attitude.paintOrder < s.compass.paintOrder, "negative z phase")
        })
        check("inherited-opacity-product", function() {
            front.opacity = 0.5; a.opacity = 0.4
            near(capture().modules.miniView.opacity, 0.2, "opacity product")
        })
        check("zero-opacity-retains-visible-flag", function() {
            front.opacity = 0
            var m = capture().modules.miniView
            near(m.opacity, 0, "opacity"); requireValue(m.visible === true, "visible/opacity conflated")
        })
        check("hidden-ancestor", function() {
            front.visible = false
            requireValue(capture().modules.miniView.visible === false, "ancestor visibility")
        })
        check("ancestor-layer-rejected", function() {
            front.layer.enabled = true
            rejected(function() { capture() }, "layered rendering")
        })
        check("registered-layer-rejected", function() {
            a.layer.enabled = true
            rejected(function() { capture() }, "layered rendering")
        })
        check("viewport-layer-rejected", function() {
            viewport.layer.enabled = true
            rejected(function() { capture() }, "layered rendering")
        })
        check("ancestor-clip-rejected", function() {
            front.clip = true
            rejected(function() { capture() }, "clipped ancestor")
        })
        check("zero-viewport-rejected", function() {
            viewport.width = 0
            rejected(function() { capture() }, "viewport is not ready")
        })
        check("outside-viewport-rejected", function() {
            rejected(function() { capture({miniView: {item: outside}}) }, "module outside viewport")
        })
        check("unrecognized-registration-rejected", function() {
            rejected(function() { capture({unknown: {item: a}}) }, "unrecognized registered module")
        })
        check("state-atomic-one-undo-redo-and-real-transform", function() {
            GcpAgentState.shell = host
            GcpAgentState.register("miniView", a, viewport)
            GcpAgentState.register("windGauge", b, viewport)
            requireValue(GcpAgentState.undoStack.length === 0 && GcpAgentState.redoStack.length === 0,
                         "fresh settings/state required")
            var original = JSON.stringify(GcpAgentState.snapshot())
            var token = beginOwnedGroup()
            GcpAgentState.beginChange("move")
            GcpAgentState.setOverride("miniView", {dx: 15, dy: 10, scale: 1, hidden: false})
            GcpAgentState.beginChange("hide")
            GcpAgentState.setOverride("windGauge", {dx: 0, dy: 0, scale: 1, hidden: true})
            GcpAgentState.beginChange("navigate", "navigation")
            host.agentGoTo(8, 11)
            GcpAgentState.commitGroup(token, "one bounded plan", "layout")
            requireValue(GcpAgentState.undoStack.length === 1 && GcpAgentState.redoStack.length === 0,
                         "group did not collapse")
            rect(GcpAgentState.verificationSnapshot(viewport).modules.miniView.rect, 55, 70, 80, 40)
            near(b.opacity, 0, "real hidden item")
            requireValue(b.enabled === false && host.page === 8, "hidden/navigation apply")
            var changed = JSON.stringify(GcpAgentState.snapshot())
            var labels = GcpAgentState.undo(1)
            requireValue(labels.length === 1 && JSON.stringify(GcpAgentState.snapshot()) === original,
                         "one undo did not restore all actions")
            rect(GcpAgentState.verificationSnapshot(viewport).modules.miniView.rect, 40, 60, 80, 40)
            near(b.opacity, 1, "restore opacity"); requireValue(b.enabled === true, "restore enabled")
            requireValue(GcpAgentState.undoStack.length === 0 && GcpAgentState.redoStack.length === 1, "undo stacks")
            GcpAgentState.redo()
            requireValue(JSON.stringify(GcpAgentState.snapshot()) === changed && GcpAgentState.undoStack.length === 1,
                         "one redo did not restore entire plan")
        })
        // State tests are intentionally sequenced after the real atomic transaction.
        // They do not clean the singleton or replace its methods with mocks.
        check("state-rollback-preserves-existing-redo", function() {
            GcpAgentState.undo(1)
            var snap = JSON.stringify(GcpAgentState.snapshot())
            var undo = JSON.stringify(GcpAgentState.undoStack), redo = JSON.stringify(GcpAgentState.redoStack)
            var token = beginOwnedGroup()
            GcpAgentState.beginChange("temporary")
            GcpAgentState.setOverride("miniView", {dx: 22, dy: 12, scale: 1, hidden: false})
            GcpAgentState.rollbackGroup(token)
            requireValue(JSON.stringify(GcpAgentState.snapshot()) === snap, "rollback state")
            requireValue(JSON.stringify(GcpAgentState.undoStack) === undo &&
                         JSON.stringify(GcpAgentState.redoStack) === redo, "rollback history")
            rect(GcpAgentState.verificationSnapshot(viewport).modules.miniView.rect, 40, 60, 80, 40)
            rejected(function() { GcpAgentState.commitGroup(token, "stale") }, "invalid atomic group commit")
            rejected(function() { GcpAgentState.rollbackGroup(token) }, "invalid group rollback")
        })
        check("state-hide-unhide-preserves-binding", function() {
            // Install real QML bindings, then exercise State's Binding objects.
            b.opacity = Qt.binding(function() { return front.opacity * 0.8 })
            b.enabled = Qt.binding(function() { return front.opacity > 0.25 })
            GcpAgentState.setOverride("windGauge", {dx: 0, dy: 0, scale: 1, hidden: true})
            near(b.opacity, 0, "binding hidden"); requireValue(b.enabled === false, "hidden disabled")
            front.opacity = 0.5
            GcpAgentState.setOverride("windGauge", {dx: 0, dy: 0, scale: 1, hidden: false})
            near(b.opacity, 0.4, "original binding restored"); requireValue(b.enabled === true, "enabled binding")
            front.opacity = 0.1
            near(b.opacity, 0.08, "binding still live"); requireValue(b.enabled === false, "enabled still live")
        })
        var failed = rows.filter(function(r) { return !r.ok }).length
        resultJson = JSON.stringify({schema: 1, suite: "qt-adapter-v6-batch5b1", cases: rows,
            total: rows.length, failed: failed, passed: rows.length - failed,
            modelCalls: 0, rendererPixelsChecked: false})
    }
}
