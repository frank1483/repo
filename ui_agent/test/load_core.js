const fs = require('fs'), path = require('path')
const src = fs.readFileSync(path.join(__dirname, '../qml/GcpAgentCore.js'), 'utf8').replace(/^\.pragma library/m, '')
const names = ['analyze','ruleDecide','needsModel','catalogCandidates','buildUserMessage','extractJson','validateModelDecision','candidateById','layoutTarget','SYSTEM_PROMPT','PAGES','SECTIONS','MODULES','afterCandidate','decisionSchema','nearestScale','validLayoutName']
module.exports = new Function(src + '\nreturn {' + names.join(',') + '}')()
