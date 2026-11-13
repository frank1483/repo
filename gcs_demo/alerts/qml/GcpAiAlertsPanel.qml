pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "GcpAiAlertsCore.js" as Core

// 智慧告警浮動面板（MVP 桌面版）。資料：gcs_demo.server（預設 127.0.0.1:8765）GET /api/alerts，每秒輪詢。
// 等級與規則文字立即顯示，模型說明（經 gateway 呼叫 gemma4:e2b）由伺服器非同步補上。
// 鎖定模組：可拖曳、可縮放、可收合成標題列，但不能隱藏。嚴重等級不能按「知道了」收起。
// 只顯示與建議，不送任何飛行指令。
Item {
    id: root

    property string apiBase: "http://127.0.0.1:8765"
    property int pollMs: 1000
    property real panelScale: 1.0
    property bool collapsed: false

    property color cPanel: Qt.rgba(0.04, 0.05, 0.07, 0.94)
    property color cBorder: Qt.rgba(1, 1, 1, 0.12)
    property color cText: "white"
    property color cMuted: Qt.rgba(1, 1, 1, 0.6)
    property color cOk: "#4ADE80"
    property color cLlm: "#C4B5FD"
    property real fs: 14

    // 由 UI 串插槽設定：GcpAlertManager 單例（沒裝在正式 UI 時為 null）、envValue、目前載具 id
    property var alertManager: null
    property var envValue: function (name, fallback) { return fallback }
    property int vehicleId: 0
    property var _rows: ({})

    property bool online: false
    property string modelName: ""
    property var cardList: []
    property var dismissed: ({})
    property string status: ""
    property bool _busy: false

    width: 360 * panelScale
    height: frame.height
    z: 1000

    function request(method, path, body, done) {
        const xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            let j = null
            if (xhr.status >= 200 && xhr.status < 300) { try { j = JSON.parse(xhr.responseText) } catch (e) { j = null } }
            done(j)
        }
        xhr.open(method, apiBase.replace(/\/$/, "") + path)
        if (body) xhr.setRequestHeader("Content-Type", "application/json")
        xhr.send(body ? JSON.stringify(body) : null)
    }

    function poll() {
        request("GET", "/api/alerts", null, function (j) {
            root.online = j !== null
            if (j) { root.cardList = Core.cards(j.alerts, root.dismissed); root.syncManager(j.alerts) }
        })
    }

    function syncManager(alerts) {
        if (!alertManager) return
        const plan = Core.managerSync(alerts, _rows)
        const rows = Object.assign({}, _rows)
        plan.resolve.forEach(r => { alertManager.resolveCondition(r.rowId); delete rows[r.condKey] })
        plan.add.forEach(a => {
            const id = alertManager.addConditionAlert(a.severity, qsTr("預測告警"), vehicleId, a.message, a.value)
            if (id) rows[a.condKey] = id
        })
        _rows = rows
    }

    function refreshInfo() {
        request("GET", "/api/scenario", null, function (j) {
            if (j && j.llm) root.modelName = j.llm.model + (j.llm.available ? "" : qsTr("（未連線）"))
        })
    }

    function dismiss(key) {
        const d = Object.assign({}, dismissed); d[key] = true; dismissed = d
        poll()
    }

    function startDemo() {
        if (_busy) return
        _busy = true; status = qsTr("規劃中…")
        request("POST", "/api/reset", {}, function () {
            root.syncManager([])
            request("POST", "/api/plan", {}, function (plan) {
                const body = Core.startBody(plan)
                if (!body) { root._busy = false; root.status = qsTr("沒有可執行的示範方案"); return }
                root.status = qsTr("模擬飛行中…")
                request("POST", "/api/start", body, function (r) {
                    root._busy = false
                    root.status = r ? (r.ok === false ? r.reason_zh : qsTr("示範情境已啟動")) : qsTr("伺服器沒有回應")
                    root.poll()
                })
            })
        })
    }

    Timer { interval: root.pollMs; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.poll() }
    Timer { interval: 10000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refreshInfo() }

    DragHandler { target: root; xAxis.enabled: true; yAxis.enabled: true }

    Rectangle {
        id: frame
        width: parent.width
        height: col.implicitHeight + 16 * root.panelScale
        radius: 8; color: root.cPanel; border.color: root.cBorder

        ColumnLayout {
            id: col
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 8 * root.panelScale }
            spacing: 6 * root.panelScale

            RowLayout {
                Layout.fillWidth: true
                Label { text: qsTr("智慧告警"); color: root.cText; font.bold: true; font.pixelSize: root.fs * root.panelScale }
                Label { text: root.cardList.length ? "(" + root.cardList.length + ")" : ""; color: root.cMuted; font.pixelSize: root.fs * root.panelScale }
                Item { Layout.fillWidth: true }
                ToolButton { text: "−"; onClicked: root.panelScale = Math.max(0.7, root.panelScale - 0.1) }
                ToolButton { text: "+"; onClicked: root.panelScale = Math.min(1.6, root.panelScale + 0.1) }
                ToolButton { text: root.collapsed ? "▾" : "▴"; onClicked: root.collapsed = !root.collapsed }
            }

            Repeater {
                model: root.collapsed ? [] : root.cardList
                delegate: Rectangle {
                    id: card
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: cardCol.implicitHeight + 12 * root.panelScale
                    radius: 6; color: Qt.rgba(1, 1, 1, 0.05); border.color: card.modelData.color
                    Rectangle { width: 4 * root.panelScale; height: parent.height; radius: 2; color: card.modelData.color }
                    ColumnLayout {
                        id: cardCol
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 6 * root.panelScale; leftMargin: 12 * root.panelScale }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: card.modelData.levelZh; color: card.modelData.color; font.bold: true; font.pixelSize: root.fs * root.panelScale }
                            Label { text: card.modelData.title; color: root.cText; font.pixelSize: root.fs * root.panelScale; Layout.fillWidth: true; elide: Text.ElideRight }
                            Label {
                                text: card.modelData.badge.zh
                                color: card.modelData.badge.kind === "ai" ? root.cLlm : root.cMuted
                                font.pixelSize: (root.fs - 2) * root.panelScale
                            }
                        }
                        Label {
                            Layout.fillWidth: true; wrapMode: Text.Wrap
                            text: card.modelData.text
                            color: card.modelData.hold ? "#EF4444" : root.cText
                            font.pixelSize: root.fs * root.panelScale
                        }
                        Button {
                            visible: card.modelData.dismissible
                            text: qsTr("知道了"); font.pixelSize: (root.fs - 2) * root.panelScale
                            onClicked: root.dismiss(card.modelData.key)
                        }
                    }
                }
            }

            Label {
                visible: !root.collapsed && root.cardList.length === 0
                text: root.online ? qsTr("目前沒有告警") : qsTr("告警伺服器未連線（請先啟動 gcs_demo.server）")
                color: root.cMuted; font.pixelSize: (root.fs - 1) * root.panelScale; Layout.fillWidth: true; wrapMode: Text.Wrap
            }

            RowLayout {
                visible: !root.collapsed
                Layout.fillWidth: true
                Button { text: qsTr("示範情境"); enabled: root.online && !root._busy; onClicked: root.startDemo() }
                Label { text: root.status; color: root.cMuted; font.pixelSize: (root.fs - 2) * root.panelScale; Layout.fillWidth: true; elide: Text.ElideRight }
            }

            RowLayout {
                Layout.fillWidth: true
                Rectangle { width: 8; height: 8; radius: 4; color: root.online ? root.cOk : "#EF4444" }
                Label {
                    text: (root.modelName || qsTr("模型未知")) + qsTr("　容量判斷：停用（MVP）")
                    color: root.cMuted; font.pixelSize: (root.fs - 3) * root.panelScale; Layout.fillWidth: true; elide: Text.ElideRight
                }
            }
        }
    }
}
