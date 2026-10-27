import QtQuick
import QtQuick.Controls
import QGroundControl.GCP

// 雲端測試用的模擬殼層：模擬 GcpMainShell 的換頁、子頁與即時飛行畫面的模組位置。
// 不是正式 UI；正式整合見 patch/。
Window {
    id: win
    width: 1920; height: 1200
    visible: true
    color: "#0B1220"

    property var pageNames: ["首頁總覽", "即時飛行", "任務規劃", "安全設定", "告警中心", "設備管理", "飛行日誌",
                             "影像設置", "系統設定", "航線庫", "用戶管理", "天氣資訊", "媒體庫", "3D 視圖"]

    Item {
        id: shell
        objectName: "shell"
        anchors.fill: parent
        property int currentPage: 0
        property var sections: ({})     // page → section
        property var denied: [10]       // 模擬：此帳號沒有用戶管理權限

        function agentLocation() {
            return { page: currentPage, section: sections[currentPage] !== undefined ? sections[currentPage] : -1 }
        }
        function agentGoTo(page, section) {
            if (denied.indexOf(page) >= 0) return false
            currentPage = page
            if (section >= 0) { const s = Object.assign({}, sections); s[page] = section; sections = s }
            return true
        }

        Rectangle {   // 側邊欄
            id: side
            width: 220; anchors.top: parent.top; anchors.bottom: parent.bottom
            color: "#111827"
            Column {
                anchors.fill: parent; anchors.margins: 12; spacing: 4
                Repeater {
                    model: win.pageNames
                    delegate: Text {
                        required property string modelData
                        required property int index
                        text: modelData; font.pixelSize: 20
                        color: shell.currentPage === index ? "#22D3EE" : "#9CA3AF"
                    }
                }
            }
        }

        Item {
            id: content
            anchors.left: side.right; anchors.right: parent.right
            anchors.top: parent.top; anchors.bottom: parent.bottom

            Text {
                objectName: "pageTitle"
                visible: shell.currentPage !== 1
                anchors.centerIn: parent
                color: "#F3F4F6"; font.pixelSize: 44
                text: win.pageNames[shell.currentPage] +
                      (shell.sections[shell.currentPage] !== undefined ? " › 子頁 " + shell.sections[shell.currentPage] : "")
            }

            Loader {
                anchors.fill: parent
                active: shell.currentPage === 1
                sourceComponent: Rectangle {
                    id: flightArea
                    objectName: "flightArea"
                    color: "#1F2937"
                    Text { anchors.centerIn: parent; text: "（即時飛行地圖）"; color: "#4B5563"; font.pixelSize: 40 }
                    Rectangle { id: missionProgress; x: 24; y: 90; width: 360; height: 60; color: "#374151"; Text { anchors.centerIn: parent; text: "任務進度"; color: "white"; font.pixelSize: 22 } }
                    Rectangle { id: windGauge; objectName: "windGauge"; x: parent.width - 220; y: 300; width: 180; height: 180; radius: 90; color: "#065F46"; Text { anchors.centerIn: parent; text: "風速計"; color: "white"; font.pixelSize: 24 } }
                    Rectangle { id: miniView; objectName: "miniView"; x: 24; y: parent.height - 260; width: 360; height: 220; color: "#1E3A8A"; Text { anchors.centerIn: parent; text: "小地圖"; color: "white"; font.pixelSize: 24 } }
                    Rectangle { id: actionDock; x: parent.width - 420; y: parent.height - 140; width: 400; height: 110; color: "#7C2D12"; Text { anchors.centerIn: parent; text: "指令區"; color: "white"; font.pixelSize: 24 } }
                    Rectangle { id: telemetryBar; objectName: "telemetryBar"; x: 420; y: parent.height - 90; width: 700; height: 60; color: "#4C1D95"; Text { anchors.centerIn: parent; text: "底部遙測列"; color: "white"; font.pixelSize: 22 } }
                    GcpAgentModule { moduleId: "missionProgress"; target: missionProgress; container: flightArea }
                    GcpAgentModule { moduleId: "windGauge"; target: windGauge; container: flightArea }
                    GcpAgentModule { moduleId: "miniView"; target: miniView; container: flightArea }
                    GcpAgentModule { moduleId: "actionDock"; target: actionDock; container: flightArea }
                    GcpAgentModule { moduleId: "telemetryBar"; target: telemetryBar; container: flightArea }
                }
            }
        }

        GcpAgentOverlay {
            id: agent
            objectName: "agent"
            anchors.fill: parent
            z: 95
            shell: shell
            envValue: function (name, fallback) { return harnessEnv[name] !== undefined ? harnessEnv[name] : fallback }
            Component.onCompleted: GcpAgentState.shell = shell
        }
    }
}
