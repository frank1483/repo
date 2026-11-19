// 替身：cornerRadius、blurSource（固定 null）；正式原檔另 import QtQuick.Effects
import QtQuick
Rectangle { property real cornerRadius: 8; property var blurSource: null; radius: cornerRadius; color: GcpTheme.color.panelFill; border.width: 1; border.color: GcpTheme.color.panelBorder }
