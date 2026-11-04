import QtQuick
import QGroundControl.GCP
import "../../qml" as Agent

// Real Overlay and real pre/post gates; host navigation is a local deterministic spy.
Window {
    id: win
    width: 1000; height: 900; visible: true
    property string resultJson: ""
    property var rows: []
    property int navigationCalls: 0
    property int page: 0
    property int ticks: 0
    QtObject {
        id: host
        function agentLocation() { return {page: win.page, section: -1} }
        function agentGoTo(p, s) { win.page = p; win.navigationCalls++; return true }
    }
    Agent.GcpAgentOverlay {
        id: agent
        anchors.fill: parent
        shell: host
        open: true
        envValue: function(name, fallback) { return name === "GCS_LLM_BACKEND" ? "none" : fallback }
    }
    function record(name, ok, detail) {
        rows = rows.concat([{name: name, ok: !!ok, detail: detail || ""}])
    }
    function gate(stage, ok) {
        return agent.gateLog.some(function(row) { return row.gate === "post" && row.stage === stage && row.ok === ok })
    }
    function nav() { return {id: "NAV_2", kind: "nav", page: 2, section: -1, label_zh: "設備", score: 1} }
    function fresh() {
        agent.clearConfirmation(); agent._candidateScope = []; agent._pending = null
        agent.pendingText = ""; agent.choices = []; agent.messageText = ""
        agent.changeLog = []; agent.gateLog = []
    }
    function run() {
        GcpAgentState.shell = host
        fresh()
        agent.submit("幫我起飛")
        record("pre blocks explicit flight before dispatch", navigationCalls === 0 && !agent._confirmation &&
            agent.gateLog.length === 1 && agent.gateLog[0].gate === "pre" && !agent.gateLog[0].ok && agent.changeLog.length === 0)
        fresh()
        agent.submit("請說明介面選項")
        record("pre accepts UI text through submit", navigationCalls === 0 &&
            agent.gateLog.some(function(row) { return row.gate === "pre" && row.ok }))
        fresh()
        agent.requestExecution([nav()], "qt-fixture", {modelSelected: true, candidates: []})
        record("post rejects absent trusted scope before card", !agent._confirmation && navigationCalls === 0 && gate("before_card", false))
        fresh()
        var candidate = nav()
        agent.requestExecution([candidate], "qt-fixture", {modelSelected: true, candidates: [candidate]})
        candidate.page = 3
        record("valid detached candidate waits for Yes", !!agent._confirmation && agent._confirmation.steps[0].page === 2 &&
            navigationCalls === 0 && gate("before_card", true))
        // Simulate an altered trusted action after the card, with the same candidate ID.
        agent._confirmation.candidates[0].page = 3
        agent.confirmIntent()
        record("post rechecks card payload before dispatch", !agent._confirmation && navigationCalls === 0 && gate("after_card", false))
        fresh()
        candidate = nav()
        agent.requestExecution([candidate], "qt-fixture", {modelSelected: true, candidates: [candidate]})
        agent.confirmIntent()
        waitForIdle.start()
    }
    Timer {
        id: waitForIdle
        interval: 10; repeat: true
        onTriggered: {
            win.ticks++
            if (agent.busy && win.ticks < 200) return
            stop()
            win.record("confirmed valid navigation reaches real executor", !agent.busy && win.page === 2 && win.navigationCalls === 1 && !agent._confirmation)
            win.record("post records every navigation execution boundary", win.gate("before_card", true) && win.gate("after_card", true) &&
                win.gate("executor_begin", true) && win.gate("executor_step", true))
            win.record("gate audit leaves user change history quiet", agent.changeLog.length === 1 && agent.gateLog.length === 4 &&
                agent.gateLog.every(function(row) { return !!row.time && !!row.label }))
            agent.gateHistoryOpen = true
            win.resultJson = JSON.stringify({total: win.rows.length,
                passed: win.rows.filter(function(row) { return row.ok }).length,
                failed: win.rows.filter(function(row) { return !row.ok }).length,
                cases: win.rows, gate_count: agent.gateLog.length, change_count: agent.changeLog.length})
        }
    }
}
