// 用 node 載入 QML 的 .pragma library JS（做法同 ui_agent/test/load_core.js）。
const fs = require('fs'), path = require('path')
function load(file, names) {
  const src = fs.readFileSync(path.join(__dirname, '../qml', file), 'utf8').replace(/^\.pragma library/m, '')
  return new Function(src + '\nreturn {' + names.join(',') + '}')()
}
module.exports = {
  Gate: load('GenuiGate.js', ['gate', 'route', 'selectTools', 'resolveParam', 'timeWindowCandidates', 'normalize', 'maskNouns', 'splitClauses', 'isQuestion', 'POLICY_VERSION', 'LEXICON_VERSION', 'REPLY_TOO_LONG', 'REPLY_NO_CAUSE']),
  Hash: load('GenuiHash.js', ['sha256Hex']),
  Tools: load('GenuiTools.js', ['telemetryLatest', 'flightlogSeries', 'energyTrend', 'alertHistory', 'manualSearch', 'tokenize', 'expandQuery', 'ENERGY', 'STATUS']),
  Claims: load('GenuiClaims.js', ['generate', 'selectRule', 'validateSelection', 'render', 'answer', 'quota', 'MAX_CLAIMS']),
  Layout: load('GenuiLayout.js', ['plan', 'needsConfirm', 'validatePlan', 'layout', 'validateLayout', 'CATALOG', 'GAP', 'GRID_COLS'])
}
