import QtQuick
import QtPositioning

import "GcpAiAgentBus.js" as Bus
import "GcpAiAgentCore.js" as Core

// 任務規劃頁上看不見的航線接收端：拿到本頁 missionController，替 AiAgent 面板寫航點與還原。
// 寫入做法和 AiMission 面板相同（removeVisualItem／insertSimpleMissionItem，再設座標與高度）。不送任何飛行指令。
Item {
    id: root
    objectName: "aiAgentRouteSink"
    visible: false
    property var missionController: null

    function waypointItems() {
        const out = []
        const vis = missionController ? missionController.visualItems : null
        if (!vis) return out
        for (let i = 0; i < vis.count; i++) {
            const it = vis.get(i)
            if (it && it.isSimpleItem && it.specifiesCoordinate && it.command === 16 && it.coordinate && it.coordinate.isValid)
                out.push(it)
        }
        return out
    }
    function snapshot() {
        return waypointItems().map(it => ({ lat: it.coordinate.latitude, lon: it.coordinate.longitude,
                                             alt: it.altitude ? it.altitude.rawValue : 50 }))
    }
    function writePoints(points) {
        let items = waypointItems()
        while (items.length > points.length && typeof missionController.removeVisualItem === "function") {
            missionController.removeVisualItem(missionController.visualItems.indexOf(items[items.length - 1]))
            items = waypointItems()
        }
        while (items.length < points.length && typeof missionController.insertSimpleMissionItem === "function") {
            const p = points[items.length]
            missionController.insertSimpleMissionItem(QtPositioning.coordinate(p.lat, p.lon), missionController.visualItems.count, false)
            items = waypointItems()
        }
        for (let i = 0; i < items.length && i < points.length; i++) {
            items[i].coordinate = QtPositioning.coordinate(points[i].lat, points[i].lon)
            if (items[i].altitude) items[i].altitude.rawValue = points[i].alt
        }
        return items.length === points.length
    }
    // 回傳 {ok, before, reason}；before 給復原用
    function apply(points) {
        const pts = Core.checkedPoints(points)
        if (!pts) return { ok: false, reason: qsTr("航點資料不合格") }
        if (!missionController) return { ok: false, reason: qsTr("任務規劃頁還沒就緒") }
        const before = snapshot()
        if (!writePoints(pts)) { writePoints(before); return { ok: false, reason: qsTr("航點寫入失敗，已還原") } }
        return { ok: true, before: before }
    }
    function restore(points) {
        if (!missionController) return false
        return writePoints(points || [])
    }

    Component.onCompleted: Bus.register(root)
    Component.onDestruction: Bus.unregister(root)
}
