// W1～W5 轉接元件畫面驗證（real02：加文字幾何檢查）（說明 v1.2 §4 第 3 步）。替身 GCP 模組，中文標籤。
// 執行：QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 90 ~/Qt/6.8.3/gcc_64/bin/qml -I ../test/qt_stub widgets_verify.qml > w_raw.txt 2>&1
// 三個情境（base、long、near：電量接近保留值，會出 W4）× 6 種高度：排版 → 每個框載入對應 W 元件 → 固定等 800 ms → 記錄 ok／overflow／W2 重畫次數 → 截圖 shot_<情境>_<高度>.png。
import QtQuick
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout
import "../qml/GenuiBind.js" as Bind
import "../qml/widgets"

Window {
    id: win
    width: 1920; height: 1080; visible: true; color: "#ffffff"
    property var heights: [1080, 600, 500, 400, 200, 120]
    property var scen: ["base", "long", "near"]
    property int si: 0
    property int hi: -1
    property var sd: null
    property var cur: null
    property var out: ({ cases: {}, errors: [] })

    Rectangle {
        id: stage
        x: 0; y: 0; width: 1920; height: 1080; color: "#ffffff"
        Repeater {
            id: rep
            model: []
            delegate: GenuiWidget {
                required property var modelData
                x: modelData.x; y: modelData.y; width: modelData.width; height: modelData.height
                property string nodeId: modelData.node_id
                componentId: win.compOf(modelData.node_id)
                bound: Bind.resolve(win.nodeOf(modelData.node_id), win.sd.res, win.sd.answer)
            }
        }
    }
    function nodeOf(id) { for (var i = 0; i < sd.plan.nodes.length; ++i) if (sd.plan.nodes[i].node_id === id) return sd.plan.nodes[i]; return null }
    function compOf(id) { var n = nodeOf(id); return n ? n.component_id : "" }

    function build(name) {
        var R = function (a, b) { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, soc: a + b * t / 60 }); return s }
        var al = [{ t: 10, level: "critical", predictor: "電池", text: "電壓過低" }, { t: 20, level: "warning", predictor: "GPS", text: "衛星數不足" }, { t: 30, level: "info", predictor: "系統", text: "返航點已更新" }]
        var man = [{ chunk_id: "k1", doc: "PX4 使用手冊", heading: "返航（RTL）", version: "v1.15", text: "返航保留電量的設定方式：在電池故障保護頁設定低電量門檻，到達門檻時飛機會自動返航。" }]
        if (name === "long") {
            for (var k = 0; k < 37; ++k) al.push({ t: 31 + k, level: k % 5 === 0 ? "critical" : "warning", predictor: "馬達", text: "溫度偏高 第 " + (k + 1) + " 次" })
            man.push({ chunk_id: "k2", doc: "QGC 使用手冊", heading: "電池設定", version: "v4.4", text: "保留電量是返航所需的最低電量百分比。" })
            man.push({ chunk_id: "k3", doc: "PX4 使用手冊", heading: "低電量故障保護", version: "v1.15", text: "低電量時可選擇警告、返航或降落。" })
        }
        var ea = name === "long" ? 30 : (name === "near" ? 25 : 80), eb = name === "long" ? -15 : -1
        var res = [Tools.energyTrend(R(ea, eb), { now: 60, reservePct: 20, vehicleType: "multirotor" }),
                   Tools.alertHistory(al, { t0: 0, t1: 70 }, []), Tools.manualSearch(man, "返航保留電量", {})]
        var a = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] })
        return { res: res, answer: a, plan: Layout.plan("r1", a, res) }
    }

    function next() {
        hi += 1
        if (hi >= heights.length) { si += 1; hi = 0; if (si >= scen.length) { finish(0); return } }
        if (hi === 0) sd = build(scen[si])
        var h = heights[hi]
        stage.height = h
        cur = Layout.layout(sd.plan, { width: 1920, height: h, revision: 1 }, sd.res, { request_id: "r1", answer: sd.answer })
        rep.model = (cur.ok && cur.layout) ? cur.layout.rects : []
        settle.restart()
    }

    // real02：逐一檢查每個框裡看得見的文字物件：(1) 有沒有超出框；(2) 彼此有沒有重疊；(3) 被裁切（內容高 > 物件高且沒省略號）；
    //   另記被「…」省略的文字（資訊用，不算失敗）。real01 的 overflow 旗標只看整欄高度，漏掉字級過大造成的重疊與裁切。
    function textProbe(widget) {
        var texts = [], res = { outside: [], overlap: [], clipped: [], elided: [] }
        function walk(o) {
            if (!o || !o.visible) return
            if (o.text !== undefined && o.contentWidth !== undefined && o.font !== undefined && String(o.text).length > 0) texts.push(o)
            var ch = o.children || []
            for (var k = 0; k < ch.length; ++k) walk(ch[k])
        }
        walk(widget)
        var rs = texts.map(function (t) { var p = t.mapToItem(widget, 0, 0)
            var w = Math.min(t.width > 0 ? t.width : t.contentWidth, t.contentWidth), h = Math.min(t.height > 0 ? t.height : t.contentHeight, t.contentHeight)
            return { t: t, x: p.x, y: p.y, w: w, h: h, s: String(t.text).slice(0, 24) } })
        for (var i = 0; i < rs.length; ++i) {
            var r = rs[i]
            if (r.x < -1 || r.y < -1 || r.x + r.w > widget.width + 1 || r.y + r.h > widget.height + 1) res.outside.push(r.s)
            if (r.t.contentHeight > r.t.height + 1 && r.t.height > 0 && !r.t.truncated) res.clipped.push(r.s)
            if (r.t.truncated) res.elided.push(r.s)
            for (var j = i + 1; j < rs.length; ++j) { var q = rs[j]
                if (r.x < q.x + q.w - 1 && q.x < r.x + r.w - 1 && r.y < q.y + q.h - 1 && q.y < r.y + r.h - 1) res.overlap.push(r.s + " × " + q.s) }
        }
        return res
    }
    function measure() {
        var key = scen[si] + "_" + heights[hi], items = [], i
        for (i = 0; i < rep.count; ++i) {
            var w = rep.itemAt(i), it = w.item
            items.push({ node_id: w.nodeId, component_id: w.componentId, loaded: !!it, ok: it ? it.ok : false, overflow: it ? it.overflow : null,
                         paint: (it && it.paintCount !== undefined) ? it.paintCount : null, error: w.bound ? w.bound.error : "no_bound",
                         status: w.status, probe: it ? textProbe(it) : null, cards: (w.bound && w.bound.ok && w.bound.data.cards) ? w.bound.data.cards.map(function (c) { return c.key + ":" + c.value + c.unit + ":" + c.accent }) : null })
        }
        out.cases[key] = { layout_ok: cur.ok, layout_error: cur.error, items: items, shot: "" }
        var ok = stage.grabToImage(function (img) { var n = "shot_" + key + ".png"; out.cases[key].shot = img.saveToFile(n) ? n : "SAVE_FAILED"; next() }, Qt.size(1920, heights[hi]))
        if (!ok) { out.cases[key].shot = "GRAB_FAILED"; next() }
    }
    function finish(code) {
        out.answer_lines_base = build("base").answer.lines.map(function (l) { return l.text })
        var s = JSON.stringify(out), n = Math.ceil(s.length / 2000)
        for (var i = 0; i < n; ++i) console.log("QTV|" + i + "|" + n + "|" + s.substr(i * 2000, 2000))
        console.log("QTV_END"); Qt.exit(code)
    }
    Timer { id: settle; interval: 800; repeat: false; onTriggered: win.measure() }
    Timer { interval: 80000; running: true; onTriggered: { win.out.errors.push("watchdog"); win.finish(3) } }
    Component.onCompleted: { try { next() } catch (e) { out.errors.push(String(e)); finish(2) } }
}
