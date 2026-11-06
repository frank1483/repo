const fs = require('fs'), path = require('path')
const read = f => fs.readFileSync(path.join(__dirname, '../qml', f), 'utf8').replace(/^\.pragma library/m, '').replace(/^\.import .*$/mg, '')
const SlotLoop = new Function(read('GcpSlotLoop.js') + '\nreturn {session, run, copy, ENGINE_VERSION, DEFAULT_MAX_CALLS}')()
module.exports = new Function('SlotLoop', read('GcpAgentStateMachine.js') + '\nreturn {create, runSync, VERSION, SYSTEM_PROMPT, KINDS, MAX_MODEL_CALLS}')(SlotLoop)
module.exports.SlotLoop = SlotLoop
