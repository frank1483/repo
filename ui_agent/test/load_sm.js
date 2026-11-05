const fs = require('fs'), path = require('path')
const src = fs.readFileSync(path.join(__dirname, '../qml/GcpAgentStateMachine.js'), 'utf8').replace(/^\.pragma library/m, '')
module.exports = new Function(src + '\nreturn {create, runSync, VERSION, SYSTEM_PROMPT, KINDS, MAX_MODEL_CALLS}')()
