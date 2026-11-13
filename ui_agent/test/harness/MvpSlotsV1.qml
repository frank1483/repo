import QtQuick
import "MvpSlots/GcpMvpInstalled.js" as MvpInstalled

// 與 elan_gcp_mvp_slots.patch 相同的三個插槽寫法；正式 UI 的 C++ 單例以假物件代替。
Item {
    id: root
    width: 1280; height: 800
    property var fakeAlertManager: QtObject {
        property var calls: []
        function addConditionAlert(sev, source, vid, msg, value) { calls.push(["add", sev, source, vid, msg]); return "id" + calls.length }
        function resolveCondition(id) { calls.push(["resolve", id]); return true }
    }
    property QtObject fakeVehicle: QtObject { property int id: 7 }
    property var activeVehicle: null
    property var fakeMissionController: QtObject { property var visualItems: null }
    readonly property int alertsStatus: mvpAlertsSlot.status
    readonly property int missionStatus: mvpMissionSlot.status
    function env(name, fallback) { return name === "GCS_MVP_API_URL" ? "http://127.0.0.1:65530" : fallback }

    Item {
        id: mvpFloatingLayer
        anchors.fill: parent
        z: 90
        Loader {
            id: mvpAlertsSlot
            objectName: "alertsSlot"
            anchors.right: parent.right; anchors.top: parent.top
            anchors.rightMargin: 16; anchors.topMargin: 16
            active: MvpInstalled.has("AiAlerts/GcpAiAlertsPanel.qml")
            source: active ? "AiAlerts/GcpAiAlertsPanel.qml" : ""
            onLoaded: MvpInstalled.bind(item, {
                apiBase: root.env("GCS_MVP_API_URL", "http://127.0.0.1:8765"),
                alertManager: root.fakeAlertManager,
                shell: root,
                envValue: function (name, fallback) { return root.env(name, fallback) }
            })
        }
        Binding {
            target: mvpAlertsSlot.item
            property: "vehicleId"
            value: root.activeVehicle ? root.activeVehicle.id : 0
            when: mvpAlertsSlot.item !== null && ("vehicleId" in mvpAlertsSlot.item)
        }
    }
    Item {
        id: mapFrame
        anchors.fill: parent
        Loader {
            id: mvpMissionSlot
            objectName: "missionSlot"
            anchors.fill: parent
            anchors.leftMargin: 120
            active: MvpInstalled.has("AiMission/GcpMissionAiPanel.qml")
            source: active ? "AiMission/GcpMissionAiPanel.qml" : ""
            onLoaded: MvpInstalled.bind(item, {
                missionController: root.fakeMissionController,
                map: null,
                apiBase: root.env("GCS_MVP_API_URL", "http://127.0.0.1:8765"),
                envValue: function (name, fallback) { return root.env(name, fallback) }
            })
        }
        Binding {
            target: mvpMissionSlot.item
            property: "activeVehicle"
            value: root.activeVehicle
            when: mvpMissionSlot.item !== null && ("activeVehicle" in mvpMissionSlot.item)
        }
    }
    Loader {
        objectName: "reportSlot"
        active: MvpInstalled.has("AiMission/GcpMissionReportView.qml")
        source: active ? "AiMission/GcpMissionReportView.qml" : ""
    }
}
