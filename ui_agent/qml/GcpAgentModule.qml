import QtQuick

import QGroundControl.GCP

// 把畫面上的一個區塊登記成 agent 可調整的模組。放在該畫面內，例如：
//   GcpAgentModule { moduleId: "windGauge"; target: windGauge; container: flightArea }
// moduleId 要對應 GcpAgentCore.js 的 MODULES。
QtObject {
    id: root
    property string moduleId: ""
    property Item target: null
    property Item container: null

    // Transforms do not alter target x/y, so this does not feed back into itself.
    property Connections _containerResize: Connections {
        target: root._registeredContainer
        function onWidthChanged() { GcpAgentState.reflow(root._registeredId) }
        function onHeightChanged() { GcpAgentState.reflow(root._registeredId) }
    }
    property Connections _targetGeometry: Connections {
        target: root._registeredTarget
        function onXChanged() { GcpAgentState.reflow(root._registeredId) }
        function onYChanged() { GcpAgentState.reflow(root._registeredId) }
        function onWidthChanged() { GcpAgentState.reflow(root._registeredId) }
        function onHeightChanged() { GcpAgentState.reflow(root._registeredId) }
    }

    property bool _ready: false
    property string _registeredId: ""
    property Item _registeredTarget: null
    property Item _registeredContainer: null
    function _unregister() {
        if (_registeredId) GcpAgentState.unregister(_registeredId, _registeredTarget)
        _registeredId = ""
        _registeredTarget = null
        _registeredContainer = null
    }
    function _register() {
        if (!_ready) return
        const actualContainer = container || (target ? target.parent : null)
        if (_registeredId === moduleId && _registeredTarget === target && _registeredContainer === actualContainer) return
        _unregister()
        if (!moduleId || !target || !actualContainer) return
        GcpAgentState.register(moduleId, target, actualContainer)
        _registeredId = moduleId
        _registeredTarget = target
        _registeredContainer = actualContainer
    }
    onModuleIdChanged: Qt.callLater(_register)
    onTargetChanged: Qt.callLater(_register)
    onContainerChanged: Qt.callLater(_register)
    Component.onCompleted: { _ready = true; Qt.callLater(_register) }
    Component.onDestruction: { _ready = false; _unregister() }
}
