pragma Singleton
import QtQuick

// 測試用：正式 UI 的 GcpTheme 只模擬 agent 會用到的 font.textScale。
// color 只是空殼：沒有真色票，色彩檢查不會就緒；復原／重做寫回空色彩群組時不出錯。
// 要測自由調色，請給 run_live_ui_gateway_v6.py 已安裝 UI 副本的 GCP 資料夾（用真的 GcpTheme*）。
QtObject {
    property QtObject font: QtObject { property real textScale: 1.0 }
    property QtObject color: QtObject { function setAgentThemeGroups(groups) {} }
}
