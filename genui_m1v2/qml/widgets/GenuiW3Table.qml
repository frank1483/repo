// W3 告警表（說明 v1.2 §2、Q1）：依工具給的順序；放不下的顯示「還有 N 筆」，不捲動。critical／warning 用主題狀態色。
import QtQuick
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok)
    readonly property real rowH: Math.ceil(GcpTheme.font.alertRowTitle * 1.6)
    readonly property var fit: ok ? Bind.fitCount(bound.data.rows.length, height - 16, rowH) : ({ shown: 0, hidden: 0 })
    readonly property bool overflow: col.implicitHeight > height - 16 + 0.5
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    Column {
        id: col
        x: 16; y: 8; width: root.width - 32
        Repeater {
            model: root.ok ? root.fit.shown : 0
            Text { property var r: root.bound.data.rows[index]
                   width: col.width; height: root.rowH; elide: Text.ElideRight
                   text: "t=" + r.t + " 秒　" + r.level + "　" + r.predictor + "　" + r.text
                   font.pixelSize: GcpTheme.font.alertRowTitle; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color[r.tone] }
        }
        Text { visible: root.fit.hidden > 0; width: col.width; height: root.rowH; text: "還有 " + root.fit.hidden + " 筆"
               font.pixelSize: GcpTheme.font.alertRowMeta; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
        Text { visible: !root.ok; width: col.width; height: root.rowH; text: "資料無法顯示"
               font.pixelSize: GcpTheme.font.body; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
    }
}
