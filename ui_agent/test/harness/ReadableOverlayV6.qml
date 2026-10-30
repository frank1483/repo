import QtQuick
import QGroundControl.GCP
import "../../qml" as Agent

Window {
    id: win
    width: 900; height: 740; visible: true
    property var agent: null
    property var baseline: null
    property var foreign: null
    readonly property bool idle: agent && !agent.busy && !GcpAgentState._groupActive
    readonly property bool active: GcpAgentState._groupActive
    readonly property int undoCount: GcpAgentState.undoStack.length
    readonly property real miniScale: GcpAgentState.overrideOf("miniView").scale
    readonly property string summary: agent ? agent.confirmationSummary() : ""
    readonly property string notice: agent ? agent.messageText : ""
    readonly property bool foreignOwned: foreign && GcpAgentState._activeGroupCheckpoint === foreign
    Item {
        id: viewport
        width: 800; height: 600
        Item {
            id: container
            x: 40; y: 30; width: 700; height: 520
            Rectangle { id: mini; x: 20; y: 50; width: 180; height: 110; color: "red" }
        }
        Item {
            id: other
            x: 500; y: 300; width: 160; height: 160
            Rectangle { id: wind; x: 10; y: 10; width: 50; height: 50; color: "blue" }
        }
    }
    QtObject {
        id: host
        function agentLocation() { return {page: 1, section: -1} }
        function agentGoTo(p, s) { return p === 1 && s === -1 }
    }
    Component {
        id: agentComponent
        Agent.GcpAgentOverlay {
            shell: host
            readableViewport: viewport
            readableGoalPolicy: ({kind: "readable", minWidth: 160, minHeight: 80,
                allowMove: true, allowShrink: false, allowNavigate: false})
            envValue: function(name, fallback) { return name === "GCS_LLM_BACKEND" ? "none" : fallback }
        }
    }
    function setup() {
        GcpAgentState.shell = host
        GcpAgentState.register("miniView", mini, container)
        GcpAgentState.register("windGauge", wind, other)
        baseline = GcpAgentState.snapshot()
        agent = agentComponent.createObject(viewport, {width: 800, height: 600})
        if (!agent) throw new Error("Overlay creation failed")
    }
    function reset() {
        if (agent._readableSession) agent._readableSession.cancel()
        if (GcpAgentState._groupActive) throw new Error("test cleanup does not own this group")
        GcpAgentState._restore(baseline)
        GcpAgentState.undoStack = []
        GcpAgentState.redoStack = []
        container.x = 40
        agent.open = true
        agent.submit("讓小地圖看得清楚一點")
    }
    function accept() { agent.confirmIntent() }
    function reject() { agent.rejectIntent() }
    function stale() { container.x += 10; agent.confirmIntent() }
    function cancel() { agent.confirmIntent(); agent.cancelWaiting() }
    function closePending() { agent.confirmIntent(); agent.open = false }
    function destroyPending() { agent.confirmIntent(); agent.destroy(); agent = null }
    function foreignCase() { foreign = GcpAgentState.beginGroup(); agent.confirmIntent() }
    function cleanForeign() {
        if (!foreignOwned) throw new Error("foreign token unexpectedly changed")
        GcpAgentState.rollbackGroup(foreign)
        foreign = null
    }
}
