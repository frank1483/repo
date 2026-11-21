// F2 接進問答流程（gate-m1-0.5、tools-m1-0.6、claims-m1-0.6）：說明 f2_deviation_v1/F2_接進問答流程_說明_v2 §4 驗證計畫，使用者 11/21 12:51、13:11 裁決。
const { Gate, Tools, Claims, Layout, Bind } = require('./load.js')
let pass = 0, fail = 0; const log = []
function ok(n, c, i) { if (c) pass++; else { fail++; log.push('FAIL ' + n + ' :: ' + JSON.stringify(i)) } }
const R = 6371008.8, deg = m => m / R * 180 / Math.PI
// 1. 意圖（§2-1 例句表＋使用者 13:11 例句）
const F2 = ['上一趟偏離航線多遠？', '最近一次有沒有偏移？', '離規劃航線最遠多少？', '離規劃航線多遠', '上一趟偏了多遠？', '這趟偏離任務多少', '上一趟偏多少',
            '最近一次偏離航點多遠', '上一趟偏離路線了嗎', 'GPS 正常嗎，上一趟偏離航線多遠', '拿上一趟和目前載入的航線比較，偏離多遠？']
const GENERAL = ['GPS 為什麼偏移？', '上一趟 GPS 偏移多少？', '位置偏移了嗎？', '偏移是什麼意思？', '航線上的 GPS 偏移多少', '上一趟定位偏移多少', '羅盤偏移怎麼校正',
                 '磁力計偏移是什麼意思', '訊號偏移了嗎', '上一趟為什麼偏離航線？', '偏移量', '雲台偏移了', '高度偏移多少', '上一趟飛了多久？', '現在電量多少',
                 '規劃一條巡檢航線', '航線怎麼設定', '最近一次告警', '圖表偏移了', '位置是否偏移', 'GPS 偏移多少公尺', '定位偏移太大']
for (const q of F2) { const r = Gate.route(q); ok('F2 ' + q, r.flightlog_op === 'DEVIATION' && r.tools.join() === 'T_FLIGHTLOG' && r.handler === 'qa_pipeline', [r.gate.class, r.tools, r.flightlog_op]) }
for (const q of GENERAL) { const r = Gate.route(q); ok('general ' + q, r.flightlog_op === null, [r.gate.class, r.tools, r.flightlog_op]) }
ok('GENERAL has ≥ 20 counterexamples', GENERAL.length >= 20, GENERAL.length)
ok('basis explicit', Gate.route('拿上一趟和目前載入的航線比較，偏離多遠？').route_basis === 'current_loaded')
ok('basis default', Gate.route('上一趟偏離航線多遠？').route_basis === 'record_check')
ok('basis needs compare word', Gate.route('目前航線上一趟偏離多遠').route_basis === 'record_check')
// 2. R-2：同句另外問的事
const r2 = Gate.route('上一趟偏離航線多遠、飛了多久？')
ok('R-2 only F2', r2.tools.join() === 'T_FLIGHTLOG' && r2.flightlog_op === 'DEVIATION', r2.tools)
ok('R-2 deferred', JSON.stringify(r2.deferred_asks) === '["飛行時間"]', r2.deferred_asks)
ok('R-2 deferred two', JSON.stringify(Gate.route('上一趟偏離航線多遠？電量掉多快').deferred_asks) === '["飛行時間","電量"]' || JSON.stringify(Gate.route('上一趟偏離航線多遠？電量掉多快').deferred_asks) === '["電量"]')
// 3. R-3／R-6／R-7：航線核對與比較基準
const line = (n, off) => Array.from({ length: n }, (_, i) => ({ seq: i, lat: deg(off || 0), lon: deg(100 * i) }))
const S = [{ t: 3, lat: deg(11), lon: deg(50) }]
const rec = wps => ({ samples: S, t0: 0, t1: 10, gaps: [], mission_waypoints: wps })
const na = (r, why) => r.status === 'ERROR' && r.detail && r.detail.unavailable_reason === why
ok('no loaded mission', na(Tools.deviationForRecord(rec(line(2)), null, 'record_check'), 'no_loaded_mission'))
ok('no loaded mission (explicit)', na(Tools.deviationForRecord(rec(line(2)), [], 'current_loaded'), 'no_loaded_mission'))
ok('record route missing', na(Tools.deviationForRecord(rec(null), line(2), 'record_check'), 'record_route_missing'))
ok('count differs', na(Tools.deviationForRecord(rec(line(3)), line(2), 'record_check'), 'route_mismatch'))
ok('1.2 m off → mismatch', na(Tools.deviationForRecord(rec(line(2)), line(2, 1.2), 'record_check'), 'route_mismatch'))
const m08 = Tools.deviationForRecord(rec(line(2)), line(2, 0.8), 'record_check')
ok('0.8 m off → runs with recorded waypoints', m08.status === 'OK' && Math.abs(m08.facts[1].value - 11) < 1e-6 && m08.detail.route_check.ok && m08.detail.basis === 'record_check', [m08.status, m08.facts[1] && m08.facts[1].value])
const m1 = Tools.routeMatch(line(2), line(2, 0.999999))
ok('≤ 1 m inclusive (0.999999 m)', m1.ok, m1)
ok('tolerance edge', Tools.routeMatch([{ seq: 0, lat: 0, lon: 0 }], [{ seq: 0, lat: deg(1), lon: 0 }]).ok === (Math.sqrt(Math.pow(R * deg(1) * Math.PI / 180, 2)) <= 1))
ok('order matters', na(Tools.deviationForRecord(rec(line(3)), line(3).slice().reverse(), 'record_check'), 'route_mismatch'))
ok('validity must agree', !Tools.routeMatch([{ seq: 0, lat: 0, lon: 0 }, { seq: 1, lat: NaN, lon: 0 }], [{ seq: 0, lat: 0, lon: 0 }, { seq: 1, lat: 0, lon: 0 }]).ok)
// 明確指定：拿不同航線比較（跳過核對），用載入的航線
const other = [{ seq: 0, lat: deg(5), lon: 0 }, { seq: 1, lat: deg(5), lon: deg(100) }]
const ex = Tools.deviationForRecord(rec(line(2)), other, 'current_loaded')
ok('explicit uses loaded route', ex.status === 'OK' && Math.abs(ex.facts[1].value - 6) < 1e-6 && ex.detail.basis === 'current_loaded' && !ex.detail.route_check, [ex.status, ex.facts[1] && ex.facts[1].value])
ok('explicit without record route', Tools.deviationForRecord(rec(null), other, 'current_loaded').status === 'OK')
// 4. 回答句
const txt = (res, ctx) => Claims.answer([res], ctx || {}).lines.map(l => l.text)
const tOk = txt(m08)
ok('sentence max', tOk.indexOf('該趟紀錄中偏離航線距離最大值是 11公尺（t=3 秒）') >= 0, tOk)
ok('no basis suffix by default', !tOk.some(t => t.indexOf('以目前載入的航線比較') >= 0), tOk)
const tEx = txt(ex)
ok('basis suffix max', tEx.indexOf('該趟紀錄中偏離航線距離最大值是 6公尺（t=3 秒）（以目前載入的航線比較）') >= 0, tEx)
ok('basis suffix mean', tEx.indexOf('該趟紀錄中偏離航線距離平均值是 6公尺（以目前載入的航線比較）') >= 0, tEx)
const tNa = txt(Tools.deviationForRecord(rec(line(2)), line(2, 1.2), 'record_check'))
ok('NA sentence mismatch', JSON.stringify(tNa) === JSON.stringify(['無法取得偏離航線距離（無法確認載入的航線是該趟的規劃航線）']), tNa)
ok('NA sentence no mission', txt(Tools.deviationForRecord(rec(line(2)), null))[0] === '無法取得偏離航線距離（沒有載入任務）')
ok('NA sentence record missing', txt(Tools.deviationForRecord(rec(null), line(2)))[0] === '無法取得偏離航線距離（該趟紀錄沒有任務航點）')
const exNa = txt(Tools.deviationForRecord(rec(line(2)), null, 'current_loaded'))
ok('explicit failure has no basis suffix', exNa.length === 1 && exNa[0].indexOf('以目前載入的航線比較') < 0, exNa)
// 數字：原始精度、顯示一位小數、去尾 .0
const r109 = Tools.deviationForRecord({ samples: [{ t: 0, lat: deg(10.94), lon: deg(50) }], t0: 0, t1: 10, mission_waypoints: line(2) }, line(2))
ok('10.9公尺', txt(r109).some(t => t.indexOf('最大值是 10.9公尺') >= 0) && r109.facts[1].value !== 10.9, [txt(r109), r109.facts[1].value])
// R-5：W1 最後一行
const aDef = Claims.answer([m08], { deferred_asks: ['飛行時間'] })
const lastLine = aDef.lines[aDef.lines.length - 1]
ok('deferred line in answer', aDef.lines.some(l => l.text === '本次未回答：飛行時間。請另外再問一次。' && l.mandatory), aDef.lines)
ok('W1 short form', Bind.shortOmitted('本次未回答：飛行時間。請另外再問一次。') === '未查：飛行時間。請另外再問一次。')
const pDef = Layout.plan('rD', aDef, [m08]), w1 = pDef.nodes.filter(n => n.component_id === 'W1_FACT')[0]
const b1 = Bind.resolve(w1, [m08], aDef), rows = b1.data.lines
const arr = Bind.w1Arrange(rows, 600, 1280), shown = arr.rows.concat(arr.tail).map(x => x.text)
ok('W1 last line is 未查', shown.length && shown[shown.length - 1] === '未查：飛行時間。請另外再問一次。', shown)
// 5. 排版：W1＋W2；INSUFFICIENT／無法取得只有 W1
const comps = p => p.nodes.map(n => n.component_id).join(',')
ok('plan W1+W2', comps(Layout.plan('r1', Claims.answer([m08], {}), [m08])) === 'W1_FACT,W2_SERIES', comps(Layout.plan('r1', Claims.answer([m08], {}), [m08])))
const ins = Tools.deviationForRecord({ samples: S, t0: 0, t1: 10, mission_waypoints: [{ seq: 0, lat: 0, lon: 0 }] }, [{ seq: 0, lat: 0, lon: 0 }])
ok('INSUFFICIENT only W1', ins.status === 'INSUFFICIENT' && comps(Layout.plan('r2', Claims.answer([ins], {}), [ins])) === 'W1_FACT', [ins.status])
const nar = Tools.deviationForRecord(rec(null), line(2))
ok('NA only W1', comps(Layout.plan('r3', Claims.answer([nar], {}), [nar])) === 'W1_FACT')
const w2 = Layout.plan('r1', Claims.answer([m08], {}), [m08]).nodes[1], b2 = Bind.resolve(w2, [m08], Claims.answer([m08], {}))
ok('W2 binds deviation series', b2.ok !== false && b2.data && b2.data.unit === '公尺', b2)
ok('versions', Gate.POLICY_VERSION === 'gate-m1-0.5' && Tools.TOOLS_VERSION.startsWith('tools-m1-0.6') && Claims.CLAIMS_VERSION.startsWith('claims-m1-0.6'))
console.log(log.join('\n')); console.log(`test_f2_route_v1: pass ${pass} fail ${fail}`); process.exit(fail ? 1 : 0)
