pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

import "GcpMissionAiCore.js" as Core

// 遙測／飛航數據頁的「任務報告」子頁（MVP 桌面版）。讀 GET /api/report（gcs_demo.server :8765）：
// 最近一次在規劃頁「模擬飛行與報告」產生的報告。摘要與建議由伺服器撰寫（模型或規則，會標明），
// 每條建議附事實編號；事實由演算法算出。MVP 階段是模擬資料；真實飛行紀錄與 CSV/KML/KMZ 匯出留到報告 v2。
Item {
    id: root

    property string apiBase: "http://127.0.0.1:8765"
    property int pollMs: 3000

    property color cPanel: Qt.rgba(0.04, 0.05, 0.07, 0.96)
    property color cBorder: Qt.rgba(1, 1, 1, 0.1)
    property color cText: "white"
    property color cMuted: Qt.rgba(1, 1, 1, 0.55)
    property color cWarn: "#FBBF24"
    property color cCrit: "#EF4444"
    property color cLlm: "#C4B5FD"
    property real fs: 14

    property bool online: false
    property var report: null
    property string missionName: ""

    function refresh() {
        const xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            let j = null
            if (xhr.status >= 200 && xhr.status < 300) { try { j = JSON.parse(xhr.responseText) } catch (e) { j = null } }
            root.online = j !== null
            if (j) { root.report = j.report; root.missionName = j.mission_name || "" }
        }
        xhr.open("GET", apiBase.replace(/\/$/, "") + "/api/report")
        xhr.send()
    }
    Timer { interval: root.pollMs; running: root.visible; repeat: true; triggeredOnStart: true; onTriggered: root.refresh() }

    component Lbl: Text { color: root.cText; font.pixelSize: root.fs; wrapMode: Text.Wrap }

    Rectangle {
        anchors.fill: parent; anchors.margins: 16
        color: root.cPanel; radius: 10; border.color: root.cBorder
        Flickable {
            anchors.fill: parent; anchors.margins: 16
            contentHeight: col.implicitHeight; clip: true
            ColumnLayout {
                id: col
                width: parent.width
                spacing: 10
                Lbl { text: qsTr("智慧任務報告（模擬）"); font.pixelSize: root.fs + 4; font.bold: true }
                Lbl { objectName: "reportState"; Layout.fillWidth: true; color: root.online ? root.cMuted : root.cCrit
                      text: !root.online ? qsTr("AI 服務未連線（%1）").arg(root.apiBase)
                            : !root.report ? qsTr("還沒有報告：請到任務規劃頁按「AI 任務建議 → 模擬飛行與報告」")
                            : qsTr("%1・%2").arg(root.missionName).arg(Core.reportTag(root.report).zh) }
                Lbl { objectName: "summary"; visible: !!root.report; Layout.fillWidth: true
                      color: root.report && root.report.source === "llm" ? root.cLlm : root.cText
                      text: root.report ? root.report.summary_zh : "" }
                Lbl { visible: !!root.report; text: qsTr("建議"); font.bold: true }
                Repeater {
                    model: root.report ? root.report.suggestions : []
                    delegate: Lbl {
                        required property var modelData
                        Layout.fillWidth: true
                        color: modelData.level === "crit" ? root.cCrit : modelData.level === "warn" ? root.cWarn : root.cText
                        text: "• " + modelData.text_zh + "  [" + (modelData.evidence_ids || []).join(",") + "]"
                    }
                }
                Lbl { visible: !!root.report; text: qsTr("演算法算出的事實"); font.bold: true }
                Repeater {
                    model: root.report ? root.report.facts : []
                    delegate: Lbl { required property var modelData; Layout.fillWidth: true; color: root.cMuted; font.pixelSize: root.fs - 2
                                    text: modelData.id + "  " + modelData.text }
                }
            }
        }
    }
}
