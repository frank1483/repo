// W2 曲線（精簡版，抄 GcpTelemetryChartPanel 的線條樣式；說明 v1.2 §2）：沒有 hover；只在資料或大小改變時重畫一次。
// 缺口斷線；電量圖畫保留電量水平線（Q4）。bind-m1-0.2 R4：左側標縱軸最小／最大值，右側標「目前」「保留」與差距；兩標籤太近時改兩行。
// 0.2.2：「目前」標籤改兩行（第 1 行目前值、第 2 行與保留值的差距），避免 bind02 截圖裡差距說明被「…」截掉。
import QtQuick
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok)
    readonly property bool overflow: false
    property int paintCount: 0                     // 驗證用：重畫次數
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    Text { id: title; x: 16; y: 8; height: Math.ceil(GcpTheme.font.telemetryPanelTitle * 1.5)
           text: root.ok ? root.bound.data.subject + (root.bound.data.unit ? "（" + root.bound.data.unit + "）" : "") : "資料無法顯示"
           font.pixelSize: GcpTheme.font.telemetryPanelTitle; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary }
    readonly property real labelH: Math.ceil(GcpTheme.font.telemetryPanelCaption * 1.4)
    readonly property real leftW: 56
    readonly property real rightW: 168
    readonly property var labels: ok ? Bind.seriesLabels(bound.data, cv.height, labelH * 2) : null
    Text { visible: !!root.labels; x: 16; y: cv.y - 2; width: root.leftW - 6; horizontalAlignment: Text.AlignRight; text: root.labels ? root.labels.max : ""
           font.pixelSize: GcpTheme.font.telemetryPanelCaption; color: GcpTheme.color.textSecondary }
    Text { visible: !!root.labels; x: 16; y: cv.y + cv.height - height + 2; width: root.leftW - 6; horizontalAlignment: Text.AlignRight; text: root.labels ? root.labels.min : ""
           font.pixelSize: GcpTheme.font.telemetryPanelCaption; color: GcpTheme.color.textSecondary }
    Text { visible: !!root.labels; x: cv.x + cv.width + 6; y: root.labels ? Math.max(cv.y, Math.min(cv.y + cv.height - height, cv.y + root.labels.current.y - height / 2)) : 0
           width: root.rightW - 8; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
           text: root.labels ? root.labels.current.text + (root.labels.diff ? "\n" + root.labels.diff : "") : ""
           font.pixelSize: GcpTheme.font.telemetryPanelCaption; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.primary }
    Text { visible: !!(root.labels && root.labels.reserve); x: cv.x + cv.width + 6
           y: (root.labels && root.labels.reserve) ? Math.max(cv.y, Math.min(cv.y + cv.height - height, cv.y + root.labels.reserve.y - height / 2)) : 0
           width: root.rightW - 8; elide: Text.ElideRight; text: (root.labels && root.labels.reserve) ? root.labels.reserve.text : ""
           font.pixelSize: GcpTheme.font.telemetryPanelCaption; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.statusWarning }
    Canvas {
        id: cv
        x: 16 + root.leftW; y: title.y + title.height + 4; width: Math.max(0, root.width - 32 - root.leftW - root.rightW); height: Math.max(0, root.height - y - 12)
        renderStrategy: Canvas.Immediate
        onPaint: {
            root.paintCount += 1
            var ctx = getContext("2d"); ctx.reset()
            if (!root.ok) return
            var d = root.bound.data
            ctx.strokeStyle = GcpTheme.color.lineSubtle; ctx.lineWidth = 1
            for (var g = 0; g <= 4; ++g) { var gy = Math.round(height * g / 4) + 0.5; ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke() }
            if (d.reserve_pct !== null && d.y) {
                var ry = height - (d.reserve_pct - d.y.min) / ((d.y.max - d.y.min) || 1) * height
                ctx.strokeStyle = GcpTheme.color.statusWarning; ctx.setLineDash([6, 4]); ctx.beginPath(); ctx.moveTo(0, ry); ctx.lineTo(width, ry); ctx.stroke(); ctx.setLineDash([])
            }
            var segs = Bind.seriesPaths(d, width, height)
            ctx.strokeStyle = GcpTheme.color.primary; ctx.lineWidth = 2
            for (var s = 0; s < segs.length; ++s) {
                ctx.beginPath(); ctx.moveTo(segs[s][0].x, segs[s][0].y)
                for (var i = 1; i < segs[s].length; ++i) ctx.lineTo(segs[s][i].x, segs[s][i].y)
                ctx.stroke()
            }
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }
    onBoundChanged: cv.requestPaint()
}
