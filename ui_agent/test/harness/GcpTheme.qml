pragma Singleton
import QtQuick

// 測試用：正式 UI 的 GcpTheme 只模擬 agent 會用到的 font.textScale
QtObject {
    property QtObject font: QtObject { property real textScale: 1.0 }
}
