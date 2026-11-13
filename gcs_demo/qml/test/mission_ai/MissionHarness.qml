import QtQuick
import QtPositioning
import "../../"

// 離屏測試架：假的 missionController（只實作面板用到的介面）＋面板＋報告子頁
Item {
    id: h
    width: 1200; height: 900

    Component { id: wpComp
        QtObject { property bool isSimpleItem: true; property bool specifiesCoordinate: true; property int command: 16
                   property var coordinate; property QtObject altitude: QtObject { property real rawValue: 50 } } }

    QtObject {
        id: mc
        property var plannedHomePosition: QtPositioning.coordinate(24.786, 120.997)
        property var items: []
        property QtObject visualItems: QtObject {
            property int count: mc.items.length
            function get(i) { return mc.items[i] }
            function indexOf(x) { return mc.items.indexOf(x) }
        }
        function add(lat, lon) { const o = wpComp.createObject(h, { coordinate: QtPositioning.coordinate(lat, lon) }); items = items.concat([o]) }
        function removeVisualItem(i) { const a = items.slice(); a.splice(i, 1); items = a }
        function insertSimpleMissionItem(c, i, cur) { const o = wpComp.createObject(h, { coordinate: c }); const a = items.slice(); a.splice(i, 0, o); items = a }
        Component.onCompleted: {
            add(24.7895, 121.0005); add(24.7930, 120.9960); add(24.7915, 120.9900)
            add(24.7860, 120.9880); add(24.7815, 120.9925); add(24.7830, 121.0020)
        }
    }
    function coords() { return mc.items.map(it => it.coordinate.latitude.toFixed(4) + "," + it.coordinate.longitude.toFixed(4)) }

    GcpMissionAiPanel { id: panel; objectName: "aiPanel"; anchors.left: parent.left; width: 600; height: parent.height; missionController: mc; apiBase: h.api }
    GcpMissionReportView { id: rep; objectName: "aiReport"; anchors.right: parent.right; width: 600; height: parent.height; apiBase: h.api }
    property string api: "http://127.0.0.1:8765"
}
