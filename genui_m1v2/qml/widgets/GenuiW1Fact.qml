// W1 答案區（說明 v1.2 §2）：GcpPanel＋GcpCard，答案行原樣顯示；mandatory 行永遠顯示，其餘從最後一行收，改顯示「還有 N 行」。
import QtQuick
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null                       // Bind.resolve() 的結果
    readonly property bool ok: !!(bound && bound.ok)
    readonly property real lineH: Math.ceil(GcpTheme.font.body * 1.5)
    readonly property var fit: ok ? Bind.fitLines(bound.data.lines, card.height - 16, lineH) : ({ shown: 0, hidden: 0 })
    readonly property bool overflow: col.implicitHeight > card.height - 16 + 0.5
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    GcpCard {
        id: card
        anchors.fill: parent; anchors.margins: 8
        outlined: true
        Column {
            id: col
            x: 12; y: 8; width: card.width - 24
            Repeater {
                model: root.ok ? root.fit.shown : 0
                Text { width: col.width; height: root.lineH; elide: Text.ElideRight; text: root.bound.data.lines[index].text
                       font.pixelSize: GcpTheme.font.body; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary }
            }
            Text { visible: root.fit.hidden > 0; width: col.width; height: root.lineH; text: "還有 " + root.fit.hidden + " 行"
                   font.pixelSize: GcpTheme.font.caption; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
            Text { visible: !root.ok; width: col.width; height: root.lineH; text: "資料無法顯示"
                   font.pixelSize: GcpTheme.font.body; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
        }
    }
}
