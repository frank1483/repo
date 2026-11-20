// host14：F2 偏離航線距離（tools-m1-0.5、claims-m1-0.5）在筆電 Qt 的 JS 引擎上跑同一組手算案例（說明 f2_deviation_v1 §6 驗證計畫）。
// 輸入 f2_cases_data.js（由雲端 test/f2_cases.js 轉出，NaN 照原樣；不用 XMLHttpRequest 讀檔，Qt 6 預設不准讀本機檔），輸出與 node 相同欄位（toPrecision(17)），
// collect_f2.py 和 expected_js.json（node 的輸出）逐位比對，另檢查回答句。只用 QtQuick，不用正式 UI。
import QtQuick
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "f2_cases_data.js" as Data

Item {
    function run() {
        var cases = Data.CASES, out = [], extra = {}
        for (var i = 0; i < cases.length; ++i) { var c = cases[i], r = Tools.flightlogDeviation(c.wp, c.s, c.t0, c.t1, c.gaps)
            var f = function (s) { return r.facts.filter(function (x) { return x.subject === s })[0] }
            var mx = f("deviation.max"), mn = f("deviation.mean"), se = f("deviation")
            out.push({ name: c.name, status: r.status, max: mx ? mx.value : null, mean: mn ? mn.value : null, n_series: se ? se.points.length : null, reason: r.detail ? r.detail.reason || null : null }) }
        var r1 = Tools.flightlogDeviation(cases[0].wp, [{ t: 3, lat: cases[0].s[0].lat, lon: cases[0].s[0].lon }], 0, 10)
        extra.sentences = Claims.answer([r1], {}).lines.map(function (l) { return l.text })
        extra.cannot = Claims.answer([Tools.flightlogDeviation(cases[4].wp, cases[4].s, 0, 10)], {}).lines.map(function (l) { return l.template_id + "|" + l.text })
        extra.versions = [Tools.TOOLS_VERSION, Claims.CLAIMS_VERSION]
        var s = JSON.stringify({ out: out, extra: extra }, function (k, v) { return typeof v === "number" ? v.toPrecision(17) : v })
        var n = Math.ceil(s.length / 2000)
        for (var j = 0; j < n; ++j) console.log("QTF|" + j + "|" + n + "|" + s.substr(j * 2000, 2000))
        console.log("QTF_END")
    }
    Component.onCompleted: { try { run(); Qt.exit(0) } catch (e) { console.log("QTF_ERROR " + e); Qt.exit(2) } }
}
