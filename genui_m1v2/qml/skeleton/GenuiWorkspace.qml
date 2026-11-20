// 骨架工作區（轉場說明 v1，使用者 11/19 23:02「轉場照建議」）：放 W1～W5，換排版時整個工作區模糊再恢復。
// 只模糊這個工作區；告警列、狀態列、套用按鈕列在工作區外，不受影響（T2）。轉場只是外觀，交易照 txn-m1-0.2（T1：120／180 ms；T3：超支停用）。
// 時間來源：live＝true 時用 FrameAnimation 每格 advance(Date.now())；驗證時 live＝false，由外部用固定時間呼叫 advance()。
// 骨架版本 skel-m1-0.3。0.3：加「查看手冊引文」視窗（viewer-m1-0.1）：W5 有收起的段落時，骨架在 W5 框上加點擊區；新回答、critical 時自動關閉；開關記錄。
// 0.2 之前：0.2：host06 run1 在 software 繪圖後端時，模糊層整塊空白約 300 ms → 自動偵測：繪圖後端是 Software 或未知時 effectOk＝false，
//   轉場照說明 §3-1 略過、直接換（log「skip:effect_unavailable」），不留空白。
import QtQuick
import QtQuick.Effects
import QGroundControl.GCP
import "../GenuiTransition.js" as Trans
import "../GenuiBind.js" as Bind
import "../widgets"

Item {
    id: root
    property var sd: null                 // 目前顯示的 {plan, res, answer}
    property var rects: []                // 目前排版的框
    property var pending: null            // 交易 SWITCHED 後等著換上的 {sd, rects}
    property int blurMax: 32              // 模糊最大值；之後改取正式主題的對應值（名稱待 PC 原檔確認）
    property bool reducedMotion: false
    property bool effectOk: root.GraphicsInfo.api !== GraphicsInfo.Software && root.GraphicsInfo.api !== GraphicsInfo.Unknown
    readonly property int graphicsApi: root.GraphicsInfo.api
    property string overrunState: "NORMAL"
    property bool live: true
    property var tst: Trans.init()
    property real blur: 0
    property bool applyLocked: false      // 轉場期間「套用」不可再按
    property int swapCount: 0
    signal swapped()
    // ---- 引文視窗（V1～V4 照建議）
    property bool viewerOpen: false
    property var viewerCitations: []
    property var viewerLog: []            // {t, ev, request_id, n, source, reason}
    property var nowFn: function () { return Date.now() }
    function reqId() { return sd && sd.plan ? sd.plan.request_id : null }
    function openViewer(w5item, source) {
        if (viewerOpen || !w5item || !w5item.ok || !(w5item.n > 0) || !(w5item.hidden > 0)) return false
        viewerCitations = JSON.parse(JSON.stringify(w5item.bound.data.citations))      // 開啟當下的快照
        viewerOpen = true
        viewerLog = viewerLog.concat([{ t: nowFn(), ev: "open", request_id: reqId(), n: viewerCitations.length, source: source }])
        return true
    }
    function closeViewer(reason) {
        if (!viewerOpen) return
        viewerOpen = false
        viewerLog = viewerLog.concat([{ t: nowFn(), ev: "close", request_id: reqId(), n: viewerCitations.length, reason: reason }])
    }

    function nodeOf(id) { if (!sd) return null; for (var i = 0; i < sd.plan.nodes.length; ++i) if (sd.plan.nodes[i].node_id === id) return sd.plan.nodes[i]; return null }
    function compOf(id) { var n = nodeOf(id); return n ? n.component_id : "" }
    function doSwap() { if (!pending) return; rects = []; sd = pending.sd; rects = pending.rects;   // 先清空框，避免舊框配到新資料
        pending = null; swapCount += 1; swapped() }
    function act(actions) {
        for (var i = 0; i < actions.length; ++i) {
            var a = actions[i]
            if (a === "swap" || a === "swap_now") doSwap()
            else if (a === "apply_lock") applyLocked = true
            else if (a === "apply_unlock") applyLocked = false
        }
    }
    function show(nextSd, nextRects) { closeViewer("new_answer"); rects = []; sd = nextSd; rects = nextRects }      // 第一次顯示，不做轉場
    function switched(nextSd, nextRects, now) {                             // 交易結果 SWITCHED
        closeViewer("new_answer")
        pending = { sd: nextSd, rects: nextRects }
        var r = Trans.onTxn(tst, "SWITCHED", now, { overrun_state: overrunState, reduced_motion: reducedMotion, effect_ok: effectOk })
        tst = r.st; act(r.actions)
    }
    function advance(now) { var r = Trans.tick(tst, now); tst = r.st; blur = r.blur; act(r.actions) }
    function critical(now) { closeViewer("critical"); var r = Trans.onCritical(tst, now); tst = r.st; blur = r.blur; act(r.actions) }
    function overrun(now) { var r = Trans.onOverrun(tst, now); tst = r.st; blur = r.blur; act(r.actions) }

    FrameAnimation { running: root.live && root.tst.state !== "IDLE"; onTriggered: root.advance(Date.now()) }

    Item {
        id: ws
        anchors.fill: parent
        layer.enabled: root.blur > 0
        layer.effect: MultiEffect { blurEnabled: true; blur: root.blur; blurMax: root.blurMax; autoPaddingEnabled: false }
        Repeater {
            id: wsRep
            model: root.rects
            delegate: GenuiWidget {
                required property var modelData
                x: modelData.x; y: modelData.y; width: modelData.width; height: modelData.height
                property string nodeId: modelData.node_id
                componentId: root.compOf(modelData.node_id)
                bound: root.sd ? Bind.resolve(root.nodeOf(modelData.node_id), root.sd.res, root.sd.answer) : null
                // 骨架的點擊區：只在 W5 有收起的段落時出現（W 元件本身不接事件）
                MouseArea {
                    id: w5tap
                    z: 10
                    anchors.fill: parent
                    enabled: visible
                    visible: parent.componentId === "W5_DOC" && !!parent.item && parent.item.ok && parent.item.n > 0 && parent.item.hidden > 0
                    onClicked: root.openViewer(parent.item, parent.item.cards.length === 0 ? "view" : "more")
                }
            }
        }
    }
    GenuiCitationViewer {
        id: viewer
        anchors.fill: parent
        visible: root.viewerOpen
        citations: root.viewerCitations
        onCloseRequested: function (reason) { root.closeViewer(reason) }
    }
    readonly property alias viewerItem: viewer
    function w5Item() { for (var i = 0; i < wsRep.count; ++i) { var w = wsRep.itemAt(i); if (w && w.componentId === "W5_DOC") return w.item } return null }
}
