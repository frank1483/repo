import QtQuick
import QGroundControl.GCP
import "../../qml/GcpAgentCore.js" as Core
import "../../qml/GcpAgentLoop.js" as Loop
import "../../qml/GcpAgentHost.js" as Host
import "../../qml/GcpAgentCatalog.js" as Catalog

// Claude 首驗 part4：真實 QQuickItem 場景下的 State.readableHostInput（不接模型、不接 Overlay）。
Window {
    id: win
    width: 900; height: 700; visible: true
    property string resultJson: ""
    property var rows: []
    Item {
        id: viewport
        width: 800; height: 600
        Item {
            id: container
            x: 40; y: 30; width: 700; height: 520
            transformOrigin: Item.TopLeft
            Rectangle { id: mini; x: 20; y: 50; width: 180; height: 110; color: "red"; transformOrigin: Item.TopLeft }
        }
        Item {
            id: other
            x: 500; y: 300; width: 200; height: 200
            Rectangle { id: wind; x: 10; y: 10; width: 120; height: 120; color: "blue" }
        }
    }
    QtObject {
        id: host
        property int page: 1
        property int section: -1
        function agentLocation() { return {page: page, section: section} }
        function agentGoTo(p, s) { page = p; section = s; return true }
    }
    function goal() { return {kind: "readable", minWidth: 160, minHeight: 80, allowMove: true, allowShrink: false, allowNavigate: false} }
    function cands() {
        return JSON.parse(JSON.stringify(Loop.goalTemplate("讓小地圖看得清楚一點",
            {page: 1, modules: {miniView: {registered: true, visible: true}}}).candidates))
    }
    function clean() {
        container.x = 40; container.y = 30; container.scale = 1; container.rotation = 0; container.clip = false
        mini.width = 180; mini.height = 110; host.page = 1
    }
    function check(name, fn) {
        clean()
        try { fn(); rows.push({name: name, ok: true}) }
        catch (e) { rows.push({name: name, ok: false, error: String(e)}) }
    }
    function need(ok, why) { if (!ok) throw new Error(why) }
    function rejects(fn, label) {
        var caught = ""
        try { fn() } catch (e) { caught = String(e) }
        need(caught !== "", label + " was not rejected")
        return caught
    }
    function run() {
        GcpAgentState.shell = host
        GcpAgentState.register("miniView", mini, container)
        GcpAgentState.register("windGauge", wind, other)
        check("translation-container-accepted", function() {
            var h = GcpAgentState.readableHostInput(viewport, goal(), cands())
            need(h && h.frame, "no frame")
            need(JSON.stringify(h.frame.others).indexOf("windGauge") >= 0 || (h.frame.others || []).length > 0,
                 "other-container obstacle missing: " + JSON.stringify(h.frame.others))
        })
        check("scaled-container-rejected", function() {
            container.scale = 1.5
            rejects(function() { GcpAgentState.readableHostInput(viewport, goal(), cands()) }, "scaled")
        })
        check("rotated-container-rejected", function() {
            container.rotation = 10
            rejects(function() { GcpAgentState.readableHostInput(viewport, goal(), cands()) }, "rotated")
        })
        check("summary-shows-minimum-and-permissions", function() {
            var p = Host.prepareReadable(GcpAgentState.readableHostInput(viewport, goal(), cands()), Core, Catalog)
            need(p.summary.indexOf("160") >= 0 && p.summary.indexOf("移動允許") >= 0 && p.summary.indexOf("降尺寸不允許") >= 0, p.summary)
        })
        check("fresh-unchanged-accepted", function() {
            var p = Host.prepareReadable(GcpAgentState.readableHostInput(viewport, goal(), cands()), Core, Catalog)
            Host.assertReadableCurrent(p, GcpAgentState.readableHostInput(viewport, goal(), cands()), Core, Catalog)
        })
        check("container-moved-invalidates", function() {
            var p = Host.prepareReadable(GcpAgentState.readableHostInput(viewport, goal(), cands()), Core, Catalog)
            container.x = 90
            rejects(function() { Host.assertReadableCurrent(p, GcpAgentState.readableHostInput(viewport, goal(), cands()), Core, Catalog) }, "move")
        })
        check("minimap-resized-invalidates", function() {
            var p = Host.prepareReadable(GcpAgentState.readableHostInput(viewport, goal(), cands()), Core, Catalog)
            mini.width = 220
            rejects(function() { Host.assertReadableCurrent(p, GcpAgentState.readableHostInput(viewport, goal(), cands()), Core, Catalog) }, "resize")
        })
        check("missing-permission-rejected", function() {
            var g = goal(); delete g.allowMove
            rejects(function() { Host.prepareReadable(GcpAgentState.readableHostInput(viewport, g, cands()), Core, Catalog) }, "permission")
        })
        var failed = rows.filter(function(r) { return !r.ok }).length
        resultJson = JSON.stringify({total: rows.length, failed: failed, passed: rows.length - failed, cases: rows})
    }
}
