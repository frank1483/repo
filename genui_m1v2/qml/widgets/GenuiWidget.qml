// 依 component_id 選 W1～W5（只允許目錄內 5 個；未知 ID 不建立任何元件）。
// 0.1.1：檔名用 Qt.resolvedUrl 以本檔所在目錄解析（0.1 用相對檔名，被當成入口檔目錄，筆電 v2 驗證全部載入失敗）。
import QtQuick

Loader {
    id: root
    property var bound: null
    readonly property var srcMap: ({ W1_FACT: "GenuiW1Fact.qml", W2_SERIES: "GenuiW2Series.qml", W3_TABLE: "GenuiW3Table.qml", W4_DIAG: "GenuiW4Diag.qml", W5_DOC: "GenuiW5Doc.qml" })
    property string componentId: ""
    source: Object.prototype.hasOwnProperty.call(srcMap, componentId) ? Qt.resolvedUrl(srcMap[componentId]) : ""
    onLoaded: item.bound = Qt.binding(function () { return root.bound })
}
