// 0.4.1b GUI 畫面驗證（排版引擎 → 真的 QtQuick 場景）。
// 執行：QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software ~/Qt/6.8.3/gcc_64/bin/qml gui_verify.qml > gui_raw.txt 2>&1
// 對 6 種工作區高度：用 Layout.layout 算矩形 → 交給 Repeater 畫出 → 等兩個畫格 → 量每個元件在場景裡的實際位置與大小
// → 和引擎給的矩形逐一比對、檢查不超出工作區且互不重疊 → 截圖存 shot_<高度>.png。結果以 QTV 分段印出。
import QtQuick
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout

Window {
    id: win
    width: 1920; height: 1080; visible: true; color: "#ffffff"
    property var heights: [1080, 600, 500, 400, 200, 120]
    property int idx: -1
    property var res: []
    property var answer: null
    property var plan: null
    property var current: null
    property var out: ({ cases: {}, errors: [] })
    property int framesWaited: 0

    Item {
        id: stage
        x: 0; y: 0; width: 1920; height: 1080
        Repeater {
            id: rep
            model: []
            delegate: Rectangle {
                required property var modelData
                x: modelData.x; y: modelData.y; width: modelData.width; height: modelData.height
                color: "#eef3fb"; border.color: "#1f4e8c"; border.width: 2; clip: true
                property string nodeId: modelData.node_id
                Text { x: 8; y: 6; text: modelData.node_id + " " + win.compOf(modelData.node_id) + " " + modelData.width + "x" + modelData.height; font.pixelSize: 14; color: "#000000" }
            }
        }
    }

    function compOf(id) { if (!plan) return ""; for (var i = 0; i < plan.nodes.length; ++i) if (plan.nodes[i].node_id === id) return plan.nodes[i].component_id; return "?" }

    function setup() {
        var R = function (a, b) { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, soc: a + b * t / 60 }); return s }
        res = [Tools.energyTrend(R(80, -1), { now: 60, reservePct: 20, vehicleType: "multirotor" }),
               Tools.alertHistory([{ t: 10, level: "critical", predictor: "p", text: "a" }, { t: 20, level: "warning", predictor: "p", text: "b" }, { t: 30, level: "info", predictor: "p", text: "c" }], { t0: 0, t1: 60 }, []),
               Tools.manualSearch([{ chunk_id: "k1", doc: "D", heading: "RTL", version: "v1", text: "返航保留電量的設定方式" }], "返航保留電量", {})]
        answer = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] })
        plan = Layout.plan("r1", answer, res)
    }

    function next() {
        idx += 1
        if (idx >= heights.length) { finish(0); return }
        var h = heights[idx]
        stage.height = h
        current = Layout.layout(plan, { width: 1920, height: h, revision: 1 }, res, { request_id: "r1", answer: answer })
        rep.model = (current.ok && current.layout) ? current.layout.rects : []
        framesWaited = 0
        settle.restart()
    }

    function measure() {
        var h = heights[idx], rects = (current.ok && current.layout) ? current.layout.rects : [], got = [], mism = [], i, j
        if (rep.count !== rects.length) mism.push("count rep=" + rep.count + " rects=" + rects.length)
        for (i = 0; i < rep.count; ++i) {
            var it = rep.itemAt(i), p = it.mapToItem(stage, 0, 0)
            var g = { node_id: it.nodeId, x: p.x, y: p.y, width: it.width, height: it.height }
            got.push(g)
            var r = rects[i]
            if (g.node_id !== r.node_id || g.x !== r.x || g.y !== r.y || g.width !== r.width || g.height !== r.height)
                mism.push(r.node_id + " want " + [r.x, r.y, r.width, r.height].join(",") + " got " + [g.x, g.y, g.width, g.height].join(","))
            if (g.x < 0 || g.y < 0 || g.x + g.width > stage.width || g.y + g.height > h) mism.push(r.node_id + " outside viewport")
        }
        for (i = 0; i < got.length; ++i) for (j = i + 1; j < got.length; ++j) {
            var a = got[i], b = got[j]
            if (a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height) mism.push("overlap " + a.node_id + " " + b.node_id)
        }
        out.cases["h" + h] = { ok: current.ok, error: current.error, rects: rects, measured: got, dropped: current.layout ? current.layout.dropped : null,
                               compact: current.layout ? current.layout.compact : null, mismatches: mism, shot: "" }
        var key = "h" + h
        var ok = stage.grabToImage(function (img) {
            var name = "shot_" + h + ".png"
            out.cases[key].shot = img.saveToFile(name) ? name : "SAVE_FAILED"
            next()
        }, Qt.size(1920, h))
        if (!ok) { out.cases[key].shot = "GRAB_FAILED"; next() }
    }

    function finish(code) {
        var s = JSON.stringify(out), n = Math.ceil(s.length / 2000)
        for (var i = 0; i < n; ++i) console.log("QTV|" + i + "|" + n + "|" + s.substr(i * 2000, 2000))
        console.log("QTV_END")
        Qt.exit(code)
    }

    // 等畫面真的畫出來：每次 frameSwapped 數一格，兩格後量測（另設 3 秒保底，避免 offscreen 不回報畫格）
    Connections { target: win; function onFrameSwapped() { if (settle.running) { win.framesWaited += 1; if (win.framesWaited >= 2) { settle.stop(); win.measure() } } } }
    Timer { id: settle; interval: 3000; repeat: false; onTriggered: { win.out.errors.push("no_frame_h" + win.heights[win.idx]); win.measure() } }
    Timer { id: watchdog; interval: 40000; running: true; repeat: false; onTriggered: { win.out.errors.push("watchdog"); win.finish(3) } }

    Component.onCompleted: {
        try { setup(); next() }
        catch (e) { out.errors.push(String(e)); finish(2) }
    }
}
