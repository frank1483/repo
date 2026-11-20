// W4 數值卡（說明 v1.2 §2、Q2）：最多 3 張 GcpTelemetryMetricCard 並排；accentColor 只從 3 個主題色挑。
// bind-m1-0.3：字級改用正式主題的通用級距（內文 scale16＝22、說明 scale13＝18、標題 sectionTitle＝18），不用各頁專用的大字級（real01 截圖重疊、裁切）。
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
                valueSize: GcpTheme.font.scale20      // 允許清單「valueSize 固定」：轉接層固定成 28 px（原預設 66 px 塞不進 W4 框，real01 截圖）
                accentColor: GcpTheme.color[modelData.accent]
            }
        }
    }
    Text { visible: !root.ok; x: 16; y: 8; text: "資料無法顯示"
           font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
}
