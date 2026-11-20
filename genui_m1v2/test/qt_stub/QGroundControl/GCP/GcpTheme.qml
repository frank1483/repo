// 替身主題（只為了在沒有 UI 原檔的地方驗 W 元件）：只有 W 元件用到的屬性，色碼為替身值，不是正式主題。
pragma Singleton
import QtQuick
QtObject {
    readonly property QtObject color: QtObject {
        readonly property color textPrimary: "#1b1f24"; readonly property color textSecondary: "#5b6470"; readonly property color textLabel: "#3a4350"
        readonly property color statusCritical: "#c62828"; readonly property color statusWarning: "#ef6c00"; readonly property color primary: "#1f6feb"
        readonly property color lineSubtle: "#d0d7de"; readonly property color bgCard: "#ffffff"; readonly property color borderDefault: "#c9d1d9"
        readonly property color panelFill: "#f3f6fa"; readonly property color panelBorder: "#c9d1d9"; readonly property color selectionGlow: "#1f6feb"
        readonly property color opaqueBgPanel: "#f3f6fa"; readonly property color opaqueBgCard: "#ffffff"; readonly property color opaqueBorderDefault: "#c9d1d9"
        readonly property color telemetryMetricGreen: "#2e7d32"; readonly property color telemetryMetricBlue: "#1565c0"; readonly property color telemetryMetricOrange: "#ef6c00"
    }
    readonly property QtObject font: QtObject {
        readonly property real body: 16; readonly property real caption: 13; readonly property real cardTitle: 15
        readonly property real alertRowTitle: 15; readonly property real alertRowMeta: 13; readonly property real telemetryPanelTitle: 15; readonly property real telemetryPanelCaption: 12
        readonly property real telemetryMetricValue: 28; readonly property real telemetryMetricLabel: 13; readonly property real telemetryMetricUnit: 13
        readonly property real scale13: 18; readonly property real scale16: 22; readonly property real scale20: 28; readonly property real sectionTitle: 18
        readonly property string chineseFamily: "Noto Sans CJK TC"
    }
    readonly property QtObject radius: QtObject { readonly property real small: 4; readonly property real medium: 8; readonly property real large: 12 }
}
