// 用 Qt 原生 qml 工具執行：QT_QPA_PLATFORM=offscreen ~/Qt/6.8.3/gcc_64/bin/qml verify.qml > qt_raw.txt 2>&1
// 輸出以「QTV|序號|總數|片段」分段印在 console（每段 2000 字元），由 collect_qt.py 拼回 JSON。
import QtQml
import "../qml/GenuiGate.js" as Gate
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout
import "scenarios_v2.js" as S
import "input_data.js" as D

QtObject {
    Component.onCompleted: {
        var s
        try { s = JSON.stringify(S.runAll(Gate, Tools, Claims, Layout, D.INPUT)) }
        catch (e) { s = JSON.stringify({ run_error: String(e) + (e.stack ? "\n" + e.stack : "") }) }
        var n = Math.ceil(s.length / 2000)
        for (var i = 0; i < n; ++i) console.log("QTV|" + i + "|" + n + "|" + s.substr(i * 2000, 2000))
        console.log("QTV_END")
        Qt.exit(0)
    }
}
