// W4 數值卡（說明 v1.2 §2、Q2；bind-m1-0.4 D1）：最多 3 張 GcpCard 並排；圓點顏色只從 3 個主題色挑。
// D1（使用者 11/20 16:40）：不用 GcpTelemetryMetricCard（標籤 33 px 比數值 28 px 大）。標籤與單位 18 px、可換行；數值 28 px 起；
//   兩行還放不下時由排版把卡片加高（Bind.contentMinH 與本檔用同一套量法），不裁掉「無法估計」這類關鍵文字。
import QtQuick
import QtQuick.Layouts
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok && bound.data && bound.data.cards)   // 0.4.1：host01 載入瞬間 bound 為 null 的 TypeError
    readonly property var lay: ok ? Bind.w4CardLayout(bound.data.cards, root.width) : null
    function lines(i, k) { return (lay && lay.cards[i]) ? lay.cards[i][k] : 1 }
    readonly property bool overflow: ok && lay.minH > root.height + 0.5
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    RowLayout {
        anchors.fill: parent; anchors.margins: Bind.W4M.padOuter; spacing: Bind.W4M.gap
        visible: root.ok
        Repeater {
            model: root.ok ? root.bound.data.cards : []
            GcpCard {
                id: c
                required property var modelData
                required property int index
                Layout.fillHeight: true; Layout.preferredWidth: root.lay ? root.lay.cardW : 0; Layout.fillWidth: true
                outlined: true
                Rectangle { id: dot; x: Bind.W4M.padCard; y: Bind.W4M.padCard + (Bind.W4M.labelLineH - 14) / 2; width: 14; height: 14; radius: 7
                            color: c.modelData ? GcpTheme.color[c.modelData.accent] : "transparent" }
                Text { id: lab
                       x: Bind.W4M.padCard + Bind.W4M.dot; y: Bind.W4M.padCard; width: c.width - 2 * Bind.W4M.padCard - Bind.W4M.dot
                       height: Bind.W4M.labelLineH * root.lines(c.index, "labelLines")
                       wrapMode: Text.Wrap; text: c.modelData.label
                       font.pixelSize: Bind.W4M.labelPx; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textLabel
                       lineHeightMode: Text.FixedHeight; lineHeight: Bind.W4M.labelLineH }
                Flow { x: Bind.W4M.padCard; y: lab.y + lab.height; width: c.width - 2 * Bind.W4M.padCard; spacing: 6
                    Text { height: Bind.W4M.valueLineH; text: c.modelData.value; verticalAlignment: Text.AlignBottom
                           font.pixelSize: Math.max(Bind.W4M.valuePx, GcpTheme.font.scale20); font.family: GcpTheme.font.chineseFamily; font.bold: true
                           color: GcpTheme.color.textPrimary }
                    Text { visible: text.length > 0; height: c.modelData.unit && root.lines(c.index, "valueLines") > 1 ? Bind.W4M.labelLineH : Bind.W4M.valueLineH
                           text: c.modelData.unit || ""; verticalAlignment: Text.AlignBottom
                           font.pixelSize: Bind.W4M.unitPx; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
                }
            }
        }
    }
    Text { visible: !root.ok; x: 16; y: 8; text: "資料無法顯示"
           font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
}
