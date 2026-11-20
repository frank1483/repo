// W2 曲線（精簡版，抄 GcpTelemetryChartPanel 的線條樣式；說明 v1.2 §2）：沒有 hover；只在資料或大小改變時重畫一次。
// bind-m1-0.3：字級改用正式主題的通用級距（內文 scale16＝22、說明 scale13＝18、標題 sectionTitle＝18），不用各頁專用的大字級（real01 截圖重疊、裁切）。
// 缺口斷線；電量圖畫保留電量水平線（Q4）。bind-m1-0.2 R4：左側標縱軸最小／最大值，右側標「目前」「保留」與差距；兩標籤太近時改兩行。
// 0.4.2（使用者 11/20 21:02）：右側標籤字級 18、行高固定 27；「目前」與差距各自可換行、不省略；放不下時由排版讓 W2 增高（Bind.w2MinH）。
// 0.2.2：「目前」標籤改兩行（第 1 行目前值、第 2 行與保留值的差距），避免 bind02 截圖裡差距說明被「…」截掉。
import QtQuick
import QGroundControl.GCP
import "../GenuiBind.js" as Bind

GcpPanel {
    id: root
    property var bound: null
    readonly property bool ok: !!(bound && bound.ok && bound.data && bound.data.points)
    readonly property bool overflow: ok && Bind.w2MinH(bound.data) > root.height + 0.5
    property int paintCount: 0                     // 驗證用：重畫次數
    cornerRadius: GcpTheme.radius.medium
    blurSource: null
    Text { id: title; x: 16; y: 8; height: Math.ceil(GcpTheme.font.sectionTitle * 1.5)
           text: root.ok ? root.bound.data.subject + (root.bound.data.unit ? "（" + root.bound.data.unit + "）" : "") : "資料無法顯示"
           font.pixelSize: GcpTheme.font.sectionTitle; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary }
    readonly property real labelH: Bind.W2M.lineH
    readonly property real leftW: Bind.W2M.leftW
    readonly property real rightW: Bind.W2M.rightW
    readonly property var box0: ok ? Bind.w2LabelBox(Bind.seriesLabels(bound.data, 100, 0)) : null
    // 0.4.3：不用舊 stacked 規則（傳 0），上下順序交給 labelTops；0.4.4：註解移出三元運算式（host03 語法錯誤）
    readonly property var labels: ok ? Bind.seriesLabels(bound.data, cv.height, 0) : null
    Text { visible: !!root.labels; x: 16; y: cv.y - 2; width: root.leftW - 6; horizontalAlignment: Text.AlignRight; text: root.labels ? root.labels.max : ""
           font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
    Text { visible: !!root.labels; x: 16; y: cv.y + cv.height - height + 2; width: root.leftW - 6; horizontalAlignment: Text.AlignRight; text: root.labels ? root.labels.min : ""
           font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
    readonly property var tops: (labels && box0) ? Bind.labelTops(labels, cv.height, box0.hCur, Math.max(labelH, box0.hRes)) : null
    Text { visible: !!root.labels; x: cv.x + cv.width + 6; y: root.tops ? cv.y + root.tops.current : 0; height: root.box0 ? root.box0.hCur : root.labelH * 2
           width: root.rightW - 8; wrapMode: Text.Wrap; lineHeightMode: Text.FixedHeight; lineHeight: root.labelH
           text: root.labels ? root.labels.current.text + (root.labels.diff ? "\n" + root.labels.diff : "") : ""
           font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.primary }
    Text { visible: !!(root.labels && root.labels.reserve); x: cv.x + cv.width + 6
           y: (root.tops && root.tops.reserve !== null) ? cv.y + root.tops.reserve : 0; height: root.box0 ? Math.max(root.labelH, root.box0.hRes) : root.labelH
           width: root.rightW - 8; wrapMode: Text.Wrap; lineHeightMode: Text.FixedHeight; lineHeight: root.labelH; text: (root.labels && root.labels.reserve) ? root.labels.reserve.text : ""
           font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.statusWarning }
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
