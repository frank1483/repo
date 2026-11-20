// W1 答案區（說明 v1.2 §2；bind-m1-0.2 R3）：GcpPanel＋GcpCard。mandatory 行永遠顯示，其餘從最後一行收，改顯示「還有 N 行」。
// bind-m1-0.3：字級改用正式主題的通用級距（內文 scale16＝22、說明 scale13＝18、標題 sectionTitle＝18），不用各頁專用的大字級（real01 截圖重疊、裁切）。
// 引用行（T-DOC）最多 3 行：第 1 行出處（文件、章節、版本，一定保留），第 2～3 行引文，在完整句邊界縮短。
import QtQuick
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok)
    readonly property real lineH: Math.ceil(GcpTheme.font.scale16 * 1.5)
    readonly property int charsPerLine: Math.max(1, Math.floor((card.width - 24) / GcpTheme.font.scale16))
    // 每行：一般行 1 行高；引用行 = 出處 1 行 + 引文行數（1～2）
    readonly property var rows: ok ? bound.data.lines.map(function (l) {
        if (l.kind !== "doc") return { kind: "text", text: l.text, h: lineH, mandatory: l.mandatory }
        var q = Bind.shortenAtSentence(l.quote, charsPerLine * 2)
        var qt = q.sentences > 0 ? "「" + q.text + (q.whole ? "」" : "…」") : ""
        var qLines = qt ? Math.min(2, Math.ceil(Array.from(qt).length / charsPerLine)) : 0
        return { kind: "doc", source: "出處：" + l.source, quote: qt, qLines: qLines, h: lineH * (1 + qLines), mandatory: l.mandatory }
    }) : []
    readonly property var fit: ok ? Bind.fitLinesH(rows.map(function (r) { return r.h }), rows.map(function (r) { return r.mandatory }), card.height - 16, lineH) : ({ shown: 0, hidden: 0 })
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
                Column {
                    property var r: root.rows[index]
                    width: col.width
                    Text { width: parent.width; height: root.lineH; elide: r.kind === "doc" ? Text.ElideMiddle : Text.ElideRight
                           text: r.kind === "doc" ? r.source : r.text
                           font.pixelSize: r.kind === "doc" ? GcpTheme.font.scale13 : GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily
                           color: r.kind === "doc" ? GcpTheme.color.textLabel : GcpTheme.color.textPrimary }
                    Text { visible: r.kind === "doc" && r.qLines > 0; width: parent.width; height: root.lineH * r.qLines
                           wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; text: r.quote || ""
                           font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary }
                }
            }
            Text { visible: root.fit.hidden > 0; width: col.width; height: root.lineH; text: "還有 " + root.fit.hidden + " 行"
                   font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
            Text { visible: !root.ok; width: col.width; height: root.lineH; text: "資料無法顯示"
                   font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
        }
    }
}
