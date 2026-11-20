// APK 最小測試包（固定情境示範版）：不接模型、不連飛控、不讀即時資料。每 6 秒在 base／near／long 三個固定情境之間切換一次，
// 經骨架工作區（含轉場；沒有 GPU 時直接換）。上方是骨架告警列（固定文字）。只為確認 APK 能啟動、正式主題與字型、W1～W5 能顯示。
import QtQuick
import QGroundControl.GCP
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout
import "../qml/GenuiBind.js" as Bind
import "../qml/skeleton"

Window {
    id: win
    width: 1280; height: 720; visible: true; color: GcpTheme.color.panelFill
    title: "GenUI 示範（固定情境）"
    property int idx: 0
    property var names: ["base", "near", "long"]
    Rectangle { id: bar; x: 0; y: 0; width: win.width; height: 56; color: GcpTheme.color.panelFill
        Text { x: 16; anchors.verticalCenter: parent.verticalCenter; text: "示範模式（固定情境，不連飛控）：" + win.names[win.idx]
               font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary } }
    GenuiWorkspace { id: ws; x: 0; y: 56; width: win.width; height: win.height - 56 }
    function build(name) {
        var R = function (a, b) { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, soc: a + b * t / 60 }); return s }
        var al = [{ t: 10, level: "critical", predictor: "電池", text: "電壓過低" }, { t: 20, level: "warning", predictor: "GPS", text: "衛星數不足" }]
        var man = [{ chunk_id: "k1", doc: "PX4 使用手冊", heading: "返航（RTL）", version: "v1.15", text: "返航保留電量的設定方式：在電池故障保護頁設定低電量門檻，到達門檻時飛機會自動返航。" }]
        var ea = name === "long" ? 30 : (name === "near" ? 25 : 80), eb = name === "long" ? -15 : -1
        var res = [Tools.energyTrend(R(ea, eb), { now: 60, reservePct: 20, vehicleType: "multirotor" }), Tools.alertHistory(al, { t0: 0, t1: 70 }, []), Tools.manualSearch(man, "返航保留電量", {})]
        var a = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] }), p = Layout.plan("r1", a, res)
        var L = Layout.layout(p, { width: ws.width, height: ws.height, revision: 1 }, res, { request_id: "r1", answer: a }, function (n, w) { return Bind.contentMinH(n, res, a, w) })
        return { sd: { res: res, answer: a, plan: p }, rects: L.ok ? L.layout.rects : [] }
    }
    Timer { interval: 6000; repeat: true; running: true
        onTriggered: { win.idx = (win.idx + 1) % 3; var b = win.build(win.names[win.idx]); ws.switched(b.sd, b.rects, Date.now()) } }
    Component.onCompleted: { var b = build(names[0]); ws.show(b.sd, b.rects) }
}
