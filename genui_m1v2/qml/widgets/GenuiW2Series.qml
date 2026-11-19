// W2 曲線（精簡版，抄 GcpTelemetryChartPanel 的線條樣式；說明 v1.2 §2）：沒有 hover；只在資料或大小改變時重畫一次。
// 缺口斷線；電量圖畫保留電量水平線（Q4）。
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
    Canvas {
        id: cv
        x: 16; y: title.y + title.height + 4; width: root.width - 32; height: Math.max(0, root.height - y - 12)
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
