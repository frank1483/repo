// 替身：只開放 outlined（允許清單 v2）
import QtQuick
Rectangle { property bool outlined: false; color: GcpTheme.color.bgCard; radius: GcpTheme.radius.medium; border.width: outlined ? 1 : 0; border.color: GcpTheme.color.borderDefault }
