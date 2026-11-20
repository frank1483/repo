// W5 手冊引用（說明 v1.2 §2；bind-m1-0.2 R2）：每段一張 GcpCard，標題「文件／章節／版本」，引文只在完整句邊界縮短。
// bind-m1-0.3：字級改用正式主題的通用級距（內文 scale16＝22、說明 scale13＝18、標題 sectionTitle＝18），不用各頁專用的大字級（real01 截圖重疊、裁切）。
// 有空間時至少顯示 1 段（出處＋至少一句完整引文），其餘「還有 N 段」；連一句都放不下時改顯示「查看手冊引文（N 段）」，開啟由骨架負責。
import QtQuick
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok)
    readonly property real titleH: Math.ceil(GcpTheme.font.scale13 * 1.5)
    readonly property real lineH: Math.ceil(GcpTheme.font.scale16 * 1.5)
    readonly property real moreH: Math.ceil(GcpTheme.font.scale13 * 1.5)
    readonly property int charsPerLine: Math.max(1, Math.floor((width - 16 - 24) / GcpTheme.font.scale16))
    readonly property int n: ok ? bound.data.citations.length : 0
    // 每張卡最多 3 行引文；卡數依剩餘高度，引文行數依實際句子
    readonly property var cards: {
        if (!ok) return []
        var out = [], used = 0, avail = height - 16, i
        for (i = 0; i < n; ++i) {
            var reserveMore = (i < n - 1) ? moreH + 8 : 0
            var maxLines = Math.min(3, Math.floor((avail - used - reserveMore - titleH - 12) / lineH))
            if (maxLines < 1) break
            var c = bound.data.citations[i], q = Bind.shortenAtSentence(c.text, charsPerLine * maxLines)
            if (q.sentences < 1) break
            var ql = Math.min(maxLines, Math.ceil(Array.from(q.text + (q.whole ? "" : "…")).length / charsPerLine))
            var h = titleH + ql * lineH + 12
            out.push({ source: c.doc + "／" + c.heading + "／" + c.doc_version, quote: q.text + (q.whole ? "" : "…"), lines: ql, h: h })
            used += h + 8
        }
        return out
    }
    readonly property int hidden: n - cards.length
    readonly property bool overflow: col.implicitHeight > height - 16 + 0.5
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    Column {
        id: col
        x: 8; y: 8; width: root.width - 16; spacing: 8
        Repeater {
            model: root.cards.length
            GcpCard {
                property var c: root.cards[index]
                width: col.width; height: c.h; outlined: true
                Text { x: 12; y: 6; width: parent.width - 24; elide: Text.ElideMiddle; text: c.source
                       font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textLabel }
                Text { x: 12; y: 6 + root.titleH; width: parent.width - 24; height: root.lineH * c.lines
                       wrapMode: Text.Wrap; maximumLineCount: c.lines; text: c.quote
                       font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary }
            }
        }
        Text { visible: root.ok && root.cards.length > 0 && root.hidden > 0; height: root.moreH; text: "還有 " + root.hidden + " 段"
               font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
        Text { visible: root.ok && root.cards.length === 0 && root.n > 0; height: root.lineH; text: "查看手冊引文（" + root.n + " 段）"
               font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.primary }
        Text { visible: !root.ok; text: "資料無法顯示"
               font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
    }
}
