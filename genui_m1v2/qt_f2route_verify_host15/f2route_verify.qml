// host15：F2 接進問答流程（gate-m1-0.5、tools-m1-0.6、claims-m1-0.6；說明 F2_接進問答流程 v2 §4）在筆電 Qt 上：
//   (1) 33 句意圖判斷與 4 個情境的路由、工具、回答句、排版，和 node 輸出（expected_node.json）逐項相同；
//   (2) 4 個情境在工作區（1280×600，正式主題）的截圖：W1 每一行完整看得到、成功情境有 W2、無法取得只有 W1。截圖底不透明（host13 做法）。
import QtQuick
import QGroundControl.GCP
import "../qml/GenuiGate.js" as Gate
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout
import "../qml/GenuiBind.js" as Bind
import "scene_f2.js" as Scene
import "../qml/skeleton"

Window {
    id: win
    width: 1280; height: 656; visible: true; color: "#ffffff"
    property var out: ({ intents: [], scenes: [], steps: [], errors: [] })
    property var built: []
    property int si: -1
    Rectangle { x: 0; y: 0; width: 1280; height: 656; color: win.color }
    Rectangle { x: 0; y: 0; width: 1280; height: 56; color: GcpTheme.color.panelFill
        Text { x: 16; anchors.verticalCenter: parent.verticalCenter; text: "告警列（骨架）"; font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.statusCritical } }
    GenuiWorkspace { id: ws; x: 0; y: 56; width: 1280; height: 600; live: false }

    function texts(item) {
        var arr = []
        function walk(o) { if (!o || !o.visible) return; if (o.text !== undefined && o.contentWidth !== undefined && o.font !== undefined && String(o.text).length) arr.push(o)
            var ch = o.children || []; for (var k = 0; k < ch.length; ++k) walk(ch[k]) }
        walk(item); return arr
    }
    function cmOf(sd) { return function (n, w) { return Bind.contentMinH(n, sd.res, sd.answer, w) } }
    function w1Expected(sd) {
        var n = sd.plan.nodes.filter(function (x) { return x.component_id === "W1_FACT" })[0], lines = Bind.resolve(n, sd.res, sd.answer).data.lines
        return lines.map(function (l) { return l.role === "omitted" ? l.short : l.text })
    }
    function probe(sd) {
        var ts = texts(ws), want = w1Expected(sd), res = { missing: [], truncated: [], comps: [], w2: false }
        for (var i = 0; i < want.length; ++i) {
            var hit = ts.filter(function (t) { return String(t.text) === want[i] })
            if (!hit.length) { res.missing.push(want[i]); continue }
            if (hit[0].truncated || hit[0].contentHeight > hit[0].height + 1 || hit[0].contentWidth > hit[0].width + 1) res.truncated.push(want[i])
        }
        res.w1_lines = want
        return res
    }
    function next() {
        si += 1
        if (si >= built.length) { finish(0); return }
        var b = built[si]
        try {
            var L = Layout.layout(b.sd.plan, { width: 1280, height: 600, revision: 1 }, b.sd.res, { request_id: "r_" + b.name, answer: b.sd.answer }, cmOf(b.sd))
            if (!L.ok) { out.errors.push(b.name + ": layout " + L.error); next(); return }
            ws.show(b.sd, L.layout.rects)
            out.steps.push({ name: b.name, rects: L.layout.rects.map(function (r) { return [b.sd.plan.nodes.filter(function (n) { return n.node_id === r.node_id })[0].component_id, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] }) })
        } catch (e) { out.errors.push(b.name + ": " + e); finish(2); return }
        settle.restart()
    }
    function grab() {
        var b = built[si], st = out.steps[out.steps.length - 1]
        st.probe = probe(b.sd)
        var ok = win.contentItem.grabToImage(function (img) { var n = "shot_" + b.name + ".png"; st.shot = img.saveToFile(n) ? n : "SAVE_FAILED"; next() }, Qt.size(1280, 656))
        if (!ok) { st.shot = "GRAB_FAILED"; next() }
    }
    function finish(code) {
        var s = JSON.stringify(out, function (k, v) { return typeof v === "number" ? v.toPrecision(17) : v }), n = Math.ceil(s.length / 2000)
        for (var i = 0; i < n; ++i) console.log("QTR|" + i + "|" + n + "|" + s.substr(i * 2000, 2000))
        console.log("QTR_END"); Qt.exit(code)
    }
    Timer { id: settle; interval: 400; repeat: false; onTriggered: win.grab() }
    Timer { interval: 60000; running: true; onTriggered: { win.out.errors.push("watchdog"); win.finish(3) } }
    Component.onCompleted: {
        try {
            out.intents = Scene.intents(Gate)
            for (var i = 0; i < Scene.SCENES.length; ++i) { var b = Scene.build(Gate, Tools, Claims, Layout, Scene.SCENES[i]); built.push(b)
                out.scenes.push({ name: b.name, route: b.route, status: b.status, reason: b.reason, max: b.max, mean: b.mean, lines: b.lines, comps: b.comps }) }
            out.versions = [Gate.POLICY_VERSION, Tools.TOOLS_VERSION, Claims.CLAIMS_VERSION]
            next()
        } catch (e) { out.errors.push(String(e)); finish(2) }
    }
}
