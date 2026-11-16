// 同一份 scenarios.js 用 node 跑，輸出 JSON（和 run_qt.py 比對）。用法：node run_node.js input.json
const fs = require('fs'), path = require('path'), L = require('../test/load.js')
const S = new Function(fs.readFileSync(path.join(__dirname, 'scenarios.js'), 'utf8') + '\nreturn { runAll }')()
process.stdout.write(JSON.stringify(S.runAll(L.Gate, L.Tools, L.Claims, L.Layout, JSON.parse(fs.readFileSync(process.argv[2], 'utf8')))))
