// 同一份 scenarios_v2.js 用 node 跑，產生期望值 node.json。用法：node run_node.js input.json > node.json
const fs = require('fs'), path = require('path'), L = require('../test/load.js')
const S = new Function(fs.readFileSync(path.join(__dirname, 'scenarios_v2.js'), 'utf8') + '\nreturn { runAll }')()
process.stdout.write(JSON.stringify(S.runAll(L.Gate, L.Tools, L.Claims, L.Layout, JSON.parse(fs.readFileSync(process.argv[2], 'utf8')))))
