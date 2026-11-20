// W1 答案區（說明 v1.2 §2；bind-m1-0.2 R3；bind-m1-0.4 D2）：GcpPanel＋GcpCard。
// D2（使用者 11/20 16:40）：依序顯示 安全提示 → 最重要的事實 → 其他必顯示事實 → 補充（放不下就收起，顯示「還有 N 行」）→ 常駐「未查：…」（最後一行）。
//   「未查：…」是「本次未執行：…」的縮短版，只用在 W1；答案區原句與紀錄不改。排版用同一套量法（Bind.contentMinH）保證放得下必顯示的行。
// 字級：內文 scale16＝22、出處與「還有 N 行」scale13＝18；行高固定 33（與 Bind.W1M 一致）。
import QtQuick
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok)
    readonly property real lineH: Bind.W1M.lineH
    readonly property var arr: ok ? Bind.w1Arrange(bound.data.lines, root.height - Bind.W1M.padH, root.width - Bind.W1M.padW) : ({ rows: [], tail: [], hidden: 0 })
    readonly property bool overflow: col.implicitHeight > card.height - 16 + 0.5
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    component Line: Column {
        id: ln
        property var r
        width: parent ? parent.width : 0
        Text { visible: ln.r.kind === "doc"; width: ln.width; height: root.lineH; elide: Text.ElideMiddle
               text: ln.r.kind === "doc" ? "出處：" + ln.r.source : ""
               font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textLabel
               lineHeightMode: Text.FixedHeight; lineHeight: root.lineH; verticalAlignment: Text.AlignVCenter }
        Text { readonly property int n: ln.r.kind === "doc" ? ln.r.qLines : ln.r.lines
               visible: n > 0; width: ln.width; height: root.lineH * n
               wrapMode: Text.Wrap; maximumLineCount: n; elide: Text.ElideRight
               text: ln.r.kind === "doc" ? (ln.r.quote || "") : ln.r.text
               font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily
               font.bold: ln.r.role === "safety"
               color: ln.r.role === "safety" ? GcpTheme.color.statusWarning : (ln.r.role === "omitted" ? GcpTheme.color.textSecondary : GcpTheme.color.textPrimary)
               lineHeightMode: Text.FixedHeight; lineHeight: root.lineH }
    }
    GcpCard {
        id: card
        anchors.fill: parent; anchors.margins: 8
        outlined: true
        Column {
            id: col
            x: 12; y: 8; width: card.width - 24
            Repeater { model: root.arr.rows; Line { required property var modelData; r: modelData } }
            Text { visible: root.ok && root.arr.hidden > 0; width: col.width; height: root.lineH; text: "還有 " + root.arr.hidden + " 行"
                   font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary
                   lineHeightMode: Text.FixedHeight; lineHeight: root.lineH; verticalAlignment: Text.AlignVCenter }
            Repeater { model: root.arr.tail; Line { required property var modelData; r: modelData } }
            Text { visible: !root.ok; width: col.width; height: root.lineH; text: "資料無法顯示"
                   font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
        }
    }
}
