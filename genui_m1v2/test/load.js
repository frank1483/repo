// 用 node 載入 QML 的 .pragma library JS（做法同 ui_agent/test/load_core.js）。
const fs = require('fs'), path = require('path')
function load(file, names) {
  const src = fs.readFileSync(path.join(__dirname, '../qml', file), 'utf8').replace(/^\.pragma library/m, '')
  return new Function(src + '\nreturn {' + names.join(',') + '}')()
}
module.exports = {
  Gate: load('GenuiGate.js', ['gate', 'route', 'selectTools', 'resolveParam', 'timeWindowCandidates', 'normalize', 'maskNouns', 'splitClauses', 'splitClausesQ', 'commandVerbs', 'hasContentChar', 'capabilityOk', 'codePoints', 'isQuestion', 'POLICY_VERSION', 'LEXICON_VERSION', 'REPLY_TOO_LONG', 'REPLY_NO_CAUSE', 'REPLY_HOLD']),
  Hash: load('GenuiHash.js', ['sha256Hex']),
  Tools: load('GenuiTools.js', ['telemetryLatest', 'flightlogSeries', 'energyTrend', 'alertHistory', 'manualSearch', 'contentTerms', 'tokenize', 'TOOLS_VERSION', 'expandQuery', 'ENERGY', 'STATUS']),
  Claims: load('GenuiClaims.js', ['generate', 'selectRule', 'validateSelection', 'render', 'answer', 'quota', 'MAX_CLAIMS', 'CLAIMS_VERSION']),
  Bind: load('GenuiBind.js', ['resolve', 'fitLinesH', 'seriesLabels', 'splitDocLine', 'sentences', 'shortenAtSentence', 'ETA_WARN_MIN', 'ETA_NA_LABEL', 'fitLines', 'fitCount', 'seriesPaths', 'axisRange', 'num', 'ETA_NA_REASON', 'BIND_VERSION', 'MAX_POINTS']),
  Layout: load('GenuiLayout.js', ['plan', 'needsConfirm', 'checkApply', 'validatePlan', 'layout', 'validateLayout', 'CATALOG', 'GAP', 'GRID_COLS', 'LAYOUT_VERSION'])
}
