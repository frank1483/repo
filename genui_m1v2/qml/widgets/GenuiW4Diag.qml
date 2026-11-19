// W4 數值卡（說明 v1.2 §2、Q2）：最多 3 張 GcpTelemetryMetricCard 並排；accentColor 只從 3 個主題色挑。
import QtQuick
import QtQuick.Layouts
import QGroundControl.GCP

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok)
    readonly property bool overflow: false
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    RowLayout {
        anchors.fill: parent; anchors.margins: 8; spacing: 8
        visible: root.ok
        Repeater {
            model: root.ok ? root.bound.data.cards : []
            GcpTelemetryMetricCard {
                required property var modelData
                Layout.fillWidth: true; Layout.fillHeight: true
                label: modelData.label; value: modelData.value; unit: modelData.unit; showDot: true
                accentColor: GcpTheme.color[modelData.accent]
            }
        }
    }
    Text { visible: !root.ok; x: 16; y: 8; text: "資料無法顯示"
           font.pixelSize: GcpTheme.font.body; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
}
