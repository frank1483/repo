// host01（bind-m1-0.4、layout-m1-0.5）：用小主程式載入正式 GCP 原檔與正式字型，驗使用者 11/20 16:40 的兩項：
//  (1) W4 最窄時 R1 完整句「電量下降，無法估計到保留電量的時間」完整可讀；(2) W1 在最矮支援高度下，安全提示、主要事實、「未查」同時看得到。
// 最窄支援寬度（假設，回報時寫明）：工作區最窄 1280；W4 在排版實際拿到的最窄寬度，與目錄最小 3 欄（1280 下 308 px）兩種都驗。
// 最矮支援高度：排版（含內容最小高度）成功的最小視窗高度，逐 1 px 往下找；同時記錄再矮 1 px 時的錯誤。
// 執行：QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 120 <build>/genui_host $PWD/host_verify.qml > h_raw.txt 2>&1
import QtQuick
import QGroundControl.GCP
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout
import "../qml/GenuiBind.js" as Bind
import "../qml/widgets"

Window {
    id: win
    width: 1920; height: 1080; visible: true; color: "#ffffff"
    property var cases: []
    property int ci: -1
    property var sd: null
    property var cur: null
    property var out: ({ bind: Bind.BIND_VERSION, layout: Layout.LAYOUT_VERSION, cases: {}, errors: [], fonts: {} })

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
    Text { id: famProbe; visible: false; text: "電量"; font.family: GcpTheme.font.chineseFamily; font.pixelSize: 22 }
    function nodeOf(id) { for (var i = 0; i < sd.plan.nodes.length; ++i) if (sd.plan.nodes[i].node_id === id) return sd.plan.nodes[i]; return null }
    function compOf(id) { var n = nodeOf(id); return n ? n.component_id : "" }
    function cmOf(s) { return function (n, w) { return Bind.contentMinH(n, s.res, s.answer, w) } }

    function build(name) {
        var R = function (a, b, j) { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, soc: a + b * t / 60 + (j ? (t % 2 ? j : -j) : 0) }); return s }
        var al = [{ t: 10, level: "critical", predictor: "電池", text: "電壓過低" }]
        var man = [{ chunk_id: "k1", doc: "PX4 使用手冊", heading: "返航（RTL）", version: "v1.15", text: "返航保留電量的設定方式：在電池故障保護頁設定低電量門檻，到達門檻時飛機會自動返航。" }]
        var e = name === "r1" ? Tools.energyTrend(R(30, -15), { now: 60, reservePct: 20, vehicleType: "multirotor" })
                              : Tools.energyTrend(R(80, -1, 0.2), { now: 60, reservePct: 20, vehicleType: "multirotor" })   // 樣本不足 → T-CANNOT
        var res = [e, Tools.alertHistory(al, { t0: 0, t1: 70 }, name === "safe2" ? [{ t0: 30, t1: 40 }] : []), Tools.manualSearch(man, "返航保留電量", {})]
        var a = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] })
        return { res: res, answer: a, plan: Layout.plan("r1", a, res) }
    }
    function lay(s, W, H) { return Layout.layout(s.plan, { width: W, height: H, revision: 1 }, s.res, { request_id: "r1", answer: s.answer }, cmOf(s)) }
    function lowest(s, W) {
        var H = 1080, last = null
        while (H >= 40) { var L = lay(s, W, H); if (!L.ok) return { h: H + 1, below_error: L.error, layout: last }; last = L; H -= 1 }
        return { h: 40, below_error: "", layout: last }
    }
    // 要看得到的文字：W1＝每條安全提示原句、主要事實、「未查：…」；W4＝R1 完整句與「—」
    function mustOf(s, comp) {
        if (comp === "W4_DIAG") return [Bind.ETA_NA_LABEL, "—"]
        var lines = Bind.resolve(s.plan.nodes.filter(function (n) { return n.component_id === "W1_FACT" })[0], s.res, s.answer).data.lines, m = [], main = null
        for (var i = 0; i < lines.length; ++i) {
            if (lines[i].role === "safety") m.push(lines[i].text)
            else if (lines[i].role === "omitted") m.push(lines[i].short)
            else if (lines[i].role === "fact" && main === null) main = lines[i].kind === "doc" ? null : lines[i].text
        }
        if (main) m.push(main)
        return m
    }
    function plan() {
        var r1 = build("r1"), s1 = build("safe1"), s2 = build("safe2"), list = []
        var w4 = r1.plan.nodes.filter(function (n) { return n.component_id === "W4_DIAG" })[0]
        var cards = Bind.resolve(w4, r1.res, r1.answer).data.cards
        // (1) W4：排版實際寬度（1280／1920 × 數種高度），找出 W4 最窄的一個；另加目錄最小 3 欄（1280 下）
        var colW1280 = (1280 - (Layout.GRID_COLS - 1) * Layout.GAP) / Layout.GRID_COLS, minW = 3 * colW1280 + 2 * Layout.GAP
        var narrowest = null
        ;[1280, 1920].forEach(function (W) { [1080, 600, 400, 300].forEach(function (H) {
            var L = lay(r1, W, H); if (!L.ok) return
            var r = L.layout.rects.filter(function (x) { return x.node_id === w4.node_id })[0]
            if (r && (!narrowest || r.width < narrowest.r.width)) narrowest = { W: W, H: H, r: r, L: L }
        }) })
        if (narrowest) list.push({ key: "w4_layout_narrowest_" + narrowest.W + "x" + narrowest.H, s: r1, W: narrowest.W, H: narrowest.H, rects: narrowest.L.layout.rects, comp: "W4_DIAG", node: w4.node_id })
        var hMin = Math.ceil(Bind.w4CardLayout(cards, minW).minH)
        list.push({ key: "w4_catalog_min_" + Math.round(minW) + "x" + hMin, s: r1, W: 1280, H: hMin, rects: [{ node_id: w4.node_id, x: 0, y: 0, width: minW, height: hMin }], comp: "W4_DIAG", node: w4.node_id })
        // (2) W1：兩種安全情境 × 1280／1920，最矮支援高度
        ;[["safe1", s1], ["safe2", s2]].forEach(function (p) { [1280, 1920].forEach(function (W) {
            var lo = lowest(p[1], W), w1 = p[1].plan.nodes.filter(function (n) { return n.component_id === "W1_FACT" })[0]
            list.push({ key: "w1_" + p[0] + "_lowest_" + W + "x" + lo.h, s: p[1], W: W, H: lo.h, rects: lo.layout ? lo.layout.layout.rects : [], comp: "W1_FACT", node: w1.node_id, below_error: lo.below_error })
        }) })
        return list
    }

    function textProbe(widget, must) {
        var texts = [], res = { outside: [], overlap: [], clipped: [], elided: [], missing: [], families: {} }
        function walk(o) {
            if (!o || !o.visible) return
            if (o.text !== undefined && o.contentWidth !== undefined && o.font !== undefined && String(o.text).length > 0) texts.push(o)
            var ch = o.children || []
            for (var k = 0; k < ch.length; ++k) walk(ch[k])
        }
        walk(widget)
        var rs = texts.map(function (t) { var p = t.mapToItem(widget, 0, 0)
            var w = Math.min(t.width > 0 ? t.width : t.contentWidth, t.contentWidth), h = Math.min(t.height > 0 ? t.height : t.contentHeight, t.contentHeight)
            res.families[t.fontInfo.family] = (res.families[t.fontInfo.family] || 0) + 1
            return { t: t, x: p.x, y: p.y, w: w, h: h, s: String(t.text).slice(0, 24) } })
        function inside(r) { return !(r.x < -1 || r.y < -1 || r.x + r.w > widget.width + 1 || r.y + r.h > widget.height + 1) }
        for (var i = 0; i < rs.length; ++i) {
            var r = rs[i]
            if (!inside(r)) res.outside.push(r.s)
            if (r.t.contentHeight > r.t.height + 1 && r.t.height > 0 && !r.t.truncated) res.clipped.push(r.s)
            if (r.t.truncated) res.elided.push(r.s)
            for (var j = i + 1; j < rs.length; ++j) { var q = rs[j]
                if (r.x < q.x + q.w - 1 && q.x < r.x + r.w - 1 && r.y < q.y + q.h - 1 && q.y < r.y + r.h - 1) res.overlap.push(r.s + " × " + q.s) }
        }
        for (var m = 0; m < must.length; ++m) {
            var hit = rs.filter(function (x) { return String(x.t.text) === must[m] && !x.t.truncated && inside(x) && x.t.contentHeight <= x.t.height + 1 })
            if (!hit.length) res.missing.push(must[m])
        }
        return res
    }
    function next() {
        ci += 1
        if (ci >= cases.length) { finish(0); return }
        var c = cases[ci]
        sd = c.s
        stage.width = Math.max(1, c.W); stage.height = Math.max(1, c.H)
        rep.model = c.rects
        settle.restart()
    }
    function measure() {
        var c = cases[ci], items = []
        for (var i = 0; i < rep.count; ++i) {
            var w = rep.itemAt(i), it = w.item, isT = w.nodeId === c.node
            items.push({ node_id: w.nodeId, component_id: w.componentId, loaded: !!it, ok: it ? it.ok : false, overflow: it ? it.overflow : null,
                         w: w.width, h: w.height, error: w.bound ? w.bound.error : "no_bound",
                         probe: it ? textProbe(it, isT ? mustOf(c.s, c.comp) : []) : null, target: isT })
        }
        out.cases[c.key] = { W: c.W, H: c.H, comp: c.comp, below_error: c.below_error || null, must: mustOf(c.s, c.comp), items: items, shot: "" }
        var ok = stage.grabToImage(function (img) { var n = "shot_" + c.key + ".png"; out.cases[c.key].shot = img.saveToFile(n) ? n : "SAVE_FAILED"; next() }, Qt.size(stage.width, stage.height))
        if (!ok) { out.cases[c.key].shot = "GRAB_FAILED"; next() }
    }
    function finish(code) {
        out.fonts = { chineseFamily: String(GcpTheme.font.chineseFamily), probe_family: famProbe.fontInfo.family,
                      loaded_families: Qt.fontFamilies().filter(function (f) { return /Noto|Inter|JetBrains/i.test(f) }) }
        var s = JSON.stringify(out), n = Math.ceil(s.length / 2000)
        for (var i = 0; i < n; ++i) console.log("QTV|" + i + "|" + n + "|" + s.substr(i * 2000, 2000))
        console.log("QTV_END"); Qt.exit(code)
    }
    Timer { id: settle; interval: 800; repeat: false; onTriggered: win.measure() }
    Timer { interval: 110000; running: true; onTriggered: { win.out.errors.push("watchdog"); win.finish(3) } }
    Component.onCompleted: { try { cases = plan(); next() } catch (e) { out.errors.push(String(e)); finish(2) } }
}
