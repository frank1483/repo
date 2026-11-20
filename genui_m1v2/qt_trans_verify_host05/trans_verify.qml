// host05：轉場接上骨架工作區（skel-m1-0.1、trans-m1-0.1）。用小主程式（正式 GCP 原檔與字型）在筆電截圖驗證。
// 視窗 1280×720：上方 56 px 是骨架告警列（不模糊），下方是工作區。情境 A（電量 80%）→ 交易 SWITCHED → 情境 B（電量 25%，會出 W4）。
// 時間由本檔固定給（live＝false），每步後等 300 ms 讓畫面畫好再截圖：
//  ref_B（B 靜態，供比較）→ before（A）→ t60（模糊進入一半）→ t120（換內容、最模糊）→ t210（恢復一半）→ t300（結束）
//  → critical（新轉場進行到 60 ms 時來 critical：立刻清楚）→ reduced（reduced motion：直接換、不模糊，不截圖）。
import QtQuick
import QGroundControl.GCP
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout
import "../qml/GenuiBind.js" as Bind
import "../qml/GenuiTransition.js" as Trans
import "../qml/skeleton"

Window {
    id: win
    width: 1280; height: 720; visible: true; color: "#ffffff"
    property var A: null
    property var B: null
    property int si: -1
    property var steps: []
    property var out: ({ trans: Trans.TRANS_VERSION, steps: [], errors: [] })
    Rectangle { id: alertBar; x: 0; y: 0; width: 1280; height: 56; color: GcpTheme.color.panelFill
        Text { x: 16; anchors.verticalCenter: parent.verticalCenter; text: "告警列（骨架，不模糊）：電池 電壓過低"
               font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.statusCritical } }
    GenuiWorkspace { id: ws; x: 0; y: 56; width: 1280; height: 664; live: false }

    function build(ea) {
        var R = function (a, b) { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, soc: a + b * t / 60 }); return s }
        var al = [{ t: 10, level: "critical", predictor: "電池", text: "電壓過低" }]
        var man = [{ chunk_id: "k1", doc: "PX4 使用手冊", heading: "返航（RTL）", version: "v1.15", text: "返航保留電量的設定方式：在電池故障保護頁設定低電量門檻，到達門檻時飛機會自動返航。" }]
        var res = [Tools.energyTrend(R(ea, -1), { now: 60, reservePct: 20, vehicleType: "multirotor" }), Tools.alertHistory(al, { t0: 0, t1: 70 }, []), Tools.manualSearch(man, "返航保留電量", {})]
        var a = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] }), p = Layout.plan("r1", a, res), sd = { res: res, answer: a, plan: p }
        var L = Layout.layout(p, { width: 1280, height: 664, revision: 1 }, res, { request_id: "r1", answer: a }, function (n, w) { return Bind.contentMinH(n, res, a, w) })
        if (!L.ok) throw new Error("layout " + L.error)
        return { sd: sd, rects: L.layout.rects }
    }
    function rec(name, shot) {
        out.steps.push({ name: name, shot: shot, state: ws.tst.state, blur: ws.blur, swapCount: ws.swapCount, applyLocked: ws.applyLocked,
                         answer_first: ws.sd ? ws.sd.answer.lines[0].text : null, rects: ws.rects.length, log: ws.tst.log.map(function (x) { return x.ev + (x.why ? ":" + x.why : "") }) })
    }
    function plan() {
        return [
            { name: "ref_B", shot: true, run: function () { ws.show(B.sd, B.rects) } },
            { name: "before", shot: true, run: function () { ws.show(A.sd, A.rects); ws.tst = Trans.init(); ws.swapCount = 0 } },
            { name: "switched_t0", shot: false, run: function () { ws.switched(B.sd, B.rects, 1000) } },
            { name: "t60", shot: true, run: function () { ws.advance(1060) } },
            { name: "t120", shot: true, run: function () { ws.advance(1120) } },
            { name: "t210", shot: true, run: function () { ws.advance(1210) } },
            { name: "t300", shot: true, run: function () { ws.advance(1300) } },
            { name: "crit_setup", shot: false, run: function () { ws.show(A.sd, A.rects); ws.tst = Trans.init(); ws.swapCount = 0; ws.switched(B.sd, B.rects, 2000); ws.advance(2060) } },
            { name: "critical", shot: true, run: function () { ws.critical(2070) } },
            { name: "reduced", shot: false, run: function () { ws.show(A.sd, A.rects); ws.tst = Trans.init(); ws.swapCount = 0; ws.reducedMotion = true; ws.switched(B.sd, B.rects, 3000) } }
        ]
    }
    function next() {
        si += 1
        if (si >= steps.length) { finish(0); return }
        try { steps[si].run() } catch (e) { out.errors.push(steps[si].name + ": " + e); finish(2); return }
        settle.restart()
    }
    function grab() {
        var s = steps[si]
        if (!s.shot) { rec(s.name, ""); next(); return }
        var ok = win.contentItem.grabToImage(function (img) { var n = "shot_" + s.name + ".png"; rec(s.name, img.saveToFile(n) ? n : "SAVE_FAILED"); next() }, Qt.size(1280, 720))
        if (!ok) { rec(s.name, "GRAB_FAILED"); next() }
    }
    function finish(code) {
        var s = JSON.stringify(out), n = Math.ceil(s.length / 2000)
        for (var i = 0; i < n; ++i) console.log("QTV|" + i + "|" + n + "|" + s.substr(i * 2000, 2000))
        console.log("QTV_END"); Qt.exit(code)
    }
    Timer { id: settle; interval: 300; repeat: false; onTriggered: win.grab() }
    Timer { interval: 60000; running: true; onTriggered: { win.out.errors.push("watchdog"); win.finish(3) } }
    Component.onCompleted: { try { A = build(80); B = build(25); steps = plan(); next() } catch (e) { out.errors.push(String(e)); finish(2) } }
}
