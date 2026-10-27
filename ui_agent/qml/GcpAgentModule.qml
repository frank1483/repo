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

    property bool _done: false
    function _register() {
        if (_done || !moduleId || !target) return
        GcpAgentState.register(moduleId, target, container)
        _done = true
    }
    // 等整個畫面建立完（位置綁定已算好）才登記並套用既有覆寫
    Component.onCompleted: Qt.callLater(_register)
    Component.onDestruction: if (_done) GcpAgentState.unregister(moduleId, target)
}
