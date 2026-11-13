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
        width: Math.max(0, win.width - 100); height: Math.max(0, win.height - 140)
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
            objectName: "part6Overlay"
            width: viewport.width; height: viewport.height
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
        agent = agentComponent.createObject(viewport)
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

    property string geometryJson: ""
    property bool destructionArmed: false
    property string destructionBefore: ""
    property var destructionToken: null
    property var scheduledHandles: []
    property int cancelledHandles: 0
    property bool schedulerDrained: false
    property string destructionEvidence: ""
    QtObject {
        id: pausedScheduler
        function schedule(fn, delay) {
            const handle = {fn: fn, delay: delay, cancelled: false, fired: false}
            win.scheduledHandles = win.scheduledHandles.concat([handle])
            return handle
        }
        function cancel(handle) {
            if (!handle.cancelled) { handle.cancelled = true; win.cancelledHandles++ }
        }
    }
    function lookup(item, name) {
        if (item.objectName === name) return item
        const children = item.children || []
        for (let i = 0; i < children.length; ++i) {
            const found = lookup(children[i], name)
            if (found) return found
        }
        return null
    }
    function rectInWindow(item, rect) {
        const r = rect || Qt.rect(0, 0, item.width, item.height)
        const p = item.mapToItem(win.contentItem, r.x, r.y)
        return {x:p.x, y:p.y, w:r.width, h:r.height}
    }
    function inside(r, bound) {
        const epsilon = 1
        return r.w > 0 && r.h > 0 && r.x >= bound.x-epsilon && r.y >= bound.y-epsilon &&
            r.x+r.w <= bound.x+bound.w+epsilon && r.y+r.h <= bound.y+bound.h+epsilon
    }
    function scrollConfirmationTop() {
        const scroll = lookup(agent, "agentConfirmationScroll")
        if (!scroll) throw new Error("missing confirmation scroll")
        scroll.contentY = 0
    }
    function scrollConfirmationBottom() {
        const scroll = lookup(agent, "agentConfirmationScroll")
        if (!scroll) throw new Error("missing confirmation scroll")
        scroll.contentY = Math.max(0, scroll.contentHeight-scroll.height)
    }
    function measureConfirmation() {
        const names = ["agentPanel", "agentConfirmationCard", "agentConfirmationScroll",
            "agentConfirmYes", "agentConfirmNo", "agentSaveLayout", "agentHistoryHeading",
            "agent_undo", "agent_redo", "agent_reset_all"]
        const measured = {}, visible = {}, rects = {}
        for (let i=0; i<names.length; ++i) {
            const item = lookup(agent, names[i])
            if (!item) throw new Error("missing geometry item " + names[i])
            measured[names[i]] = item
            visible[names[i]] = item.visible
            rects[names[i]] = rectInWindow(item)
        }
        const panel = rects.agentPanel, card = rects.agentConfirmationCard, scroll = measured.agentConfirmationScroll
        const label = lookup(agent, "agentConfirmationText")
        const last = rectInWindow(label, label.lastLineRect)
        const bounds = {x:0,y:0,w:win.width,h:win.height}, owner = rectInWindow(viewport)
        let ok = inside(panel,bounds) && inside(panel,owner) && inside(card,panel) && inside(rects.agentConfirmationScroll,card)
        for(let i=3;i<names.length;++i) ok = ok && visible[names[i]] && inside(rects[names[i]],panel)
        ok = ok && inside(rects.agentConfirmYes,card) && inside(rects.agentConfirmNo,card)
        ok = ok && inside(last,rects.agentConfirmationScroll) && inside(last,panel) && label.text.endsWith("對嗎？")
        geometryJson = JSON.stringify({ok:ok, window:bounds, owner:owner, rects:rects, visible:visible,
            last_line:last, content_y:scroll.contentY, content_height:scroll.contentHeight,
            last_line_text:label.text.split("\n").slice(-1)[0], text:label.text})
    }
    function armDestruction() {
        if (!agent || !agent._confirmation) throw new Error("confirmation required")
        destructionBefore = JSON.stringify(GcpAgentState.snapshot())
        agent.readableScheduler = pausedScheduler
        agent.confirmIntent()
        const token = GcpAgentState._activeGroupCheckpoint
        destructionArmed = agent.busy && agent._readableSession !== null && GcpAgentState._groupActive && token !== null &&
            GcpAgentState.overrideOf("miniView").scale > 1 && scheduledHandles.length === 1 && undoCount === 0 &&
            agent._readableSession.state().phase === "running"
        if (!destructionArmed) throw new Error("not paused in a mutated, owned, uncommitted session")
        destructionToken = token
        destructionEvidence = JSON.stringify({armed:true, phase:agent._readableSession.state().phase,
            mini_scale:miniScale, queued:scheduledHandles.length, undo_count:undoCount})
    }
    function destroyArmed() {
        if (!destructionArmed || !agent || GcpAgentState._activeGroupCheckpoint !== destructionToken ||
                !agent._readableSession || !agent.busy || cancelledHandles !== 0)
            throw new Error("session completed or changed before actual destruction")
        // Deliberately do not cancel, close, restore or null the pointer here.
        agent.destroy()
    }
    function probeAfterDestruction() {
        const state = JSON.stringify(GcpAgentState.snapshot())
        const restored = !GcpAgentState._groupActive && state === destructionBefore && undoCount === 0 &&
            GcpAgentState.redoStack.length === 0 && cancelledHandles === 1
        // Even a misdelivered cancelled callback must be inert after the session epoch changed.
        for (let i=0;i<scheduledHandles.length;++i) scheduledHandles[i].fn()
        schedulerDrained = restored && !GcpAgentState._groupActive &&
            JSON.stringify(GcpAgentState.snapshot()) === destructionBefore && undoCount === 0 &&
            GcpAgentState.redoStack.length === 0
        destructionEvidence = JSON.stringify({restored:restored, stale_callback_inert:schedulerDrained,
            cancelled:cancelledHandles, undo_count:undoCount, redo_count:GcpAgentState.redoStack.length,
            snapshot:GcpAgentState.snapshot()})
    }
}
