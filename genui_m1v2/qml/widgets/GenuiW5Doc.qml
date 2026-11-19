// W5 手冊引用（說明 v1.2 §2）：每段一張 GcpCard，標題「文件／章節／版本」，內文原樣；放不下時只減段數。
import QtQuick
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok)
    readonly property real cardH: Math.ceil(GcpTheme.font.cardTitle * 1.5) + Math.ceil(GcpTheme.font.body * 1.5) * 2 + 16
    readonly property var fit: ok ? Bind.fitCount(bound.data.citations.length, height - 16, cardH + 8) : ({ shown: 0, hidden: 0 })
    readonly property bool overflow: col.implicitHeight > height - 16 + 0.5
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    Column {
        id: col
        x: 8; y: 8; width: root.width - 16; spacing: 8
        Repeater {
            model: root.ok ? root.fit.shown : 0
            GcpCard {
                property var c: root.bound.data.citations[index]
                width: col.width; height: root.cardH; outlined: true
                Text { x: 12; y: 6; width: parent.width - 24; elide: Text.ElideRight; text: c.doc + "／" + c.heading + "／" + c.doc_version
                       font.pixelSize: GcpTheme.font.cardTitle; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textLabel }
                Text { x: 12; y: 6 + Math.ceil(GcpTheme.font.cardTitle * 1.5); width: parent.width - 24; height: Math.ceil(GcpTheme.font.body * 1.5) * 2
                       wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; text: c.text
                       font.pixelSize: GcpTheme.font.body; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary }
            }
        }
        Text { visible: root.fit.hidden > 0; text: "還有 " + root.fit.hidden + " 段"
               font.pixelSize: GcpTheme.font.caption; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
        Text { visible: !root.ok; text: "資料無法顯示"
               font.pixelSize: GcpTheme.font.body; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
    }
}
