// 替身（不是正式原檔）：正式 GcpEnv 是 C++ 單例（GCP/GcpEnv.h），小主程式沒有編入。允許清單的檔案只有 GcpThemeLayout.qml 第 11 行用到
// GcpEnv.value("GCP_TOUCH_SIZES", "")；這裡一律回傳預設值，所以 touchDevice＝false，與桌面版相同。cwaApiKey 不提供（不需要、也不放金鑰）。
pragma Singleton
import QtQuick
QtObject {
    function value(name, defaultValue) { return defaultValue === undefined ? "" : defaultValue }
}
