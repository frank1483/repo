import QtQml
import "../qml/GenuiGate.js" as Gate
import "../qml/GenuiTools.js" as Tools
import "../qml/GenuiClaims.js" as Claims
import "../qml/GenuiLayout.js" as Layout
import "scenarios.js" as S

QtObject {
    property string inputJson: ""
    property string outputJson: ""
    property string error: ""
    function run() {
        try { outputJson = JSON.stringify(S.runAll(Gate, Tools, Claims, Layout, JSON.parse(inputJson))) }
        catch (e) { error = String(e) + (e.stack ? "\n" + e.stack : "") }
    }
}
