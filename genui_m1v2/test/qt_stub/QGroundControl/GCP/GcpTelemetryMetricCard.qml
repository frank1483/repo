// 替身：label、value、unit、showDot、accentColor、valueColor（預設 = accentColor，同正式原檔）
import QtQuick
Rectangle {
    property string label: ""; property string value: ""; property string unit: ""; property bool showDot: false
    property real valueSize: GcpTheme.font.telemetryMetricValue; property color accentColor: GcpTheme.color.selectionGlow; property color valueColor: accentColor
    color: GcpTheme.color.bgCard; border.color: GcpTheme.color.borderDefault; border.width: 1; radius: GcpTheme.radius.small
    Rectangle { visible: showDot; x: 10; y: 12; width: 8; height: 8; radius: 4; color: accentColor }
    Text { x: 24; y: 6; text: label; font.pixelSize: GcpTheme.font.telemetryMetricLabel; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textLabel }
    Text { id: v; x: 10; y: 26; text: value; font.pixelSize: valueSize; color: valueColor }
    Text { x: v.x + v.width + 4; y: v.y + v.height - height - 4; text: unit; font.pixelSize: GcpTheme.font.telemetryMetricUnit; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
}
