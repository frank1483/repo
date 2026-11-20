// host09：「查看手冊引文」視窗（viewer-m1-0.1、skel-m1-0.3），說明 citation_viewer_v1 §8 驗收。offscreen 即可（不用模糊）。
// 開啟用工作區的 openViewer()（等同骨架點擊區 onClicked 呼叫的函式；offscreen 沒有真的滑鼠點擊，限制照實記錄）。
import QtQuick
import QGroundControl.GCP
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout
import "../qml/GenuiBind.js" as Bind
import "../qml/skeleton"

Window {
    id: win
    width: 1280; height: 656; visible: true; color: "#ffffff"
    property var sceneLong: null
    property var sceneOther: null
    property int si: -1
    property var steps: []
    property int clock: 1000
    property var out: ({ steps: [], errors: [] })
    Rectangle { x: 0; y: 0; width: 1280; height: 56; color: GcpTheme.color.panelFill
        Text { x: 16; anchors.verticalCenter: parent.verticalCenter; text: "告警列（骨架）"; font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.statusCritical } }
    GenuiWorkspace { id: ws; x: 0; y: 56; width: 1280; height: 600; live: false; nowFn: function () { return win.clock } }

    function build(long) {
        var R = function (a, b) { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, soc: a + b * t / 60 }); return s }
        var man = long ? [
            { chunk_id: "k1", doc: "PX4 使用手冊", heading: "返航（RTL）", version: "v1.15", text: "返航保留電量的設定方式：在電池故障保護頁設定低電量門檻，到達門檻時飛機會自動返航。返航時會先爬升到設定的返航高度，再直線飛回起飛點上空，最後依降落設定下降。若返航途中電量再降到緊急門檻，會改為就地降落。" },
            { chunk_id: "k2", doc: "QGC 使用手冊", heading: "電池設定（Battery）", version: "v4.4", text: "保留電量是返航所需的最低電量百分比。設定時要考慮風速、距離與機體重量；距離越遠、風越大，保留電量就要越高。建議先在空曠場地實測一次返航所需的電量，再依結果調整。" },
            { chunk_id: "k3", doc: "PX4 使用手冊", heading: "低電量故障保護", version: "v1.15", text: "低電量時可選擇警告、返航或降落。警告只會在地面站顯示訊息；返航會依返航設定飛回；降落會在目前位置下降。三段門檻依序是低電量、嚴重低電量與緊急電量，每一段的動作可以分別設定。" }
        ] : [{ chunk_id: "k9", doc: "PX4 使用手冊", heading: "起飛", version: "v1.15", text: "起飛前確認電量。" }]
        var res = [Tools.energyTrend(R(80, -1), { now: 60, reservePct: 20, vehicleType: "multirotor" }), Tools.manualSearch(man, long ? "返航保留電量 電池 低電量" : "起飛前確認電量", {})]
        var a = Claims.answer(res, {}), p = Layout.plan(long ? "rL" : "rO", a, res)
        var w5 = p.nodes.filter(function (n) { return n.component_id === "W5_DOC" })[0]
        return { sd: { res: res, answer: a, plan: p }, w5: w5 }
    }
    function rectsW5(s, h) { return [{ node_id: s.w5.node_id, x: 0, y: 0, width: 1280, height: h }] }
    function texts(item) {
        var arr = []
        function walk(o) { if (!o || !o.visible) return; if (o.text !== undefined && o.contentWidth !== undefined && o.font !== undefined && String(o.text).length) arr.push(o)
            var ch = o.children || []; for (var k = 0; k < ch.length; ++k) walk(ch[k]) }
        walk(item); return arr
    }
    // 視窗內：每段出處與全文都有、沒被省略、沒被裁切；inView＝true 時只算目前在捲動視窗內看得到的
    function probeViewer(lastOnly) {
        var v = ws.viewerItem, f = v.flick, ts = texts(v), res = { missing: [], truncated: [], families: {} }
        var cits = ws.viewerCitations, want = []
        for (var i = 0; i < cits.length; ++i) { if (lastOnly && i < cits.length - 1) continue
            want.push("出處：" + cits[i].doc + " › " + cits[i].heading + "，" + cits[i].doc_version); want.push(cits[i].text) }
        for (var w = 0; w < want.length; ++w) {
            var hit = ts.filter(function (t) { return String(t.text) === want[w] })
            if (!hit.length) { res.missing.push(want[w].slice(0, 20)); continue }
            var t = hit[0]; res.families[t.fontInfo.family] = 1
            if (t.truncated || t.contentHeight > t.height + 1) res.truncated.push(want[w].slice(0, 20))
            if (lastOnly) { var p = t.mapToItem(f, 0, 0); if (p.y < -1 || p.y + t.height > f.height + 1) res.missing.push("not in view: " + want[w].slice(0, 20)) }
        }
        return res
    }
    function rec(name, extra) {
        var w5 = ws.w5Item()
        var r = { name: name, viewerOpen: ws.viewerOpen, log: ws.viewerLog.map(function (x) { return x.ev + ":" + (x.source || x.reason) + ":" + x.request_id + ":" + x.n }),
                  w5: w5 ? { ok: w5.ok, n: w5.n, hidden: w5.hidden, cards: w5.cards.length } : null, shot: "" }
        if (extra) for (var k in extra) r[k] = extra[k]
        out.steps.push(r); return r
    }
    function plan() {
        var L = sceneLong, O = sceneOther
        return [
            { name: "w5_view_only", shot: true, run: function () { ws.show(L.sd, rectsW5(L, 96)) } },
            { name: "open_view", shot: true, run: function () { win.clock = 1100; out.open_view_ret = ws.openViewer(ws.w5Item(), ws.w5Item().cards.length === 0 ? "view" : "more") }, probe: false },
            { name: "scroll_end", shot: true, run: function () { ws.viewerItem.scrollToEnd() }, probe: true },
            { name: "close_new_answer", shot: false, run: function () { win.clock = 1200; ws.show(O.sd, rectsW5(O, 96)) } },
            { name: "reopen_for_critical", shot: false, run: function () { ws.show(L.sd, rectsW5(L, 96)) } },
            { name: "open2", shot: false, run: function () { win.clock = 1300; ws.openViewer(ws.w5Item(), "view") } },
            { name: "close_critical", shot: false, run: function () { win.clock = 1400; ws.critical(1400) } },
            { name: "open3", shot: false, run: function () { win.clock = 1500; ws.openViewer(ws.w5Item(), "view") } },
            { name: "close_back", shot: false, run: function () { win.clock = 1600; ws.viewerItem.backPressed() } },
            { name: "w5_more", shot: true, run: function () { ws.show(L.sd, rectsW5(L, 220)) } },
            { name: "open_more", shot: false, run: function () { win.clock = 1700; ws.openViewer(ws.w5Item(), ws.w5Item().cards.length === 0 ? "view" : "more") } },
            { name: "close_button", shot: false, run: function () { win.clock = 1800; ws.viewerItem.closeRequested("button") } },
            { name: "w5_all_fit", shot: false, run: function () { ws.show(L.sd, rectsW5(L, 600)) } },
            { name: "open_refused", shot: false, run: function () { out.open_refused_ret = ws.openViewer(ws.w5Item(), "more") } }
        ]
    }
    function next() {
        si += 1
        if (si >= steps.length) { finish(0); return }
        try { steps[si].run() } catch (e) { out.errors.push(steps[si].name + ": " + e); finish(2); return }
        settle.restart()
    }
    function grab() {
        var s = steps[si], extra = {}
        if (s.name === "open_view") extra.probe_top = probeViewer(false)
        if (s.name === "scroll_end") extra.probe_end = probeViewer(true)
        var r = rec(s.name, extra)
        if (!s.shot) { next(); return }
        var ok = win.contentItem.grabToImage(function (img) { var n = "shot_" + s.name + ".png"; r.shot = img.saveToFile(n) ? n : "SAVE_FAILED"; next() }, Qt.size(1280, 656))
        if (!ok) { r.shot = "GRAB_FAILED"; next() }
    }
    function finish(code) {
        var s = JSON.stringify(out), n = Math.ceil(s.length / 2000)
        for (var i = 0; i < n; ++i) console.log("QTV|" + i + "|" + n + "|" + s.substr(i * 2000, 2000))
        console.log("QTV_END"); Qt.exit(code)
    }
    Timer { id: settle; interval: 400; repeat: false; onTriggered: win.grab() }
    Timer { interval: 60000; running: true; onTriggered: { win.out.errors.push("watchdog"); win.finish(3) } }
    Component.onCompleted: { try { sceneLong = build(true); sceneOther = build(false); steps = plan(); next() } catch (e) { out.errors.push(String(e)); finish(2) } }
}
