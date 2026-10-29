// 讓 node 載入 QML 用的 .pragma library 檔
const fs = require("fs"), path = require("path"), vm = require("vm")
module.exports = function () {
    const src = fs.readFileSync(path.join(__dirname, "..", "GcpMissionCore.js"), "utf8").replace(/^\.pragma library/, "")
    const m = { exports: {} }
    vm.runInNewContext(src, { module: m, Math, JSON, String, Number, Array })
    return m.exports
}
