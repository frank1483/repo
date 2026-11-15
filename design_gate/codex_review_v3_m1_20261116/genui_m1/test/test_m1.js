// GenUI M1 規則版固定案例。執行：node genui_m1/test/test_m1.js
// 案例來源：契約附件 v3 第一部分 §A-5、v1 §A-1 例句、v1 §C-4、v3 §D-3、候選 ADR §4 固定案例。
const assert = require('assert'), crypto = require('crypto')
const { Gate, Hash, Tools, Claims, Layout } = require('./load.js')
let pass = 0, fail = 0
function t(name, fn) { try { fn(); pass++ } catch (e) { fail++; console.log('FAIL ' + name + '\n  ' + String(e.message).split('\n').join('\n  ')) } }
const cls = s => Gate.gate(s)['class']

// ---------------- Gate：v3 §A-5 固定案例
const gateCases = [
  ['今天天氣如何', 'OUT_OF_DOMAIN'], ['如何', 'OUT_OF_DOMAIN'], ['那現在呢', 'OUT_OF_DOMAIN'],
  ['電量現在多少', 'QA'], ['返航點在哪裡', 'QA'], ['顯示返航點後立即返航', 'FLIGHT_CMD'],
  ['返航，然後告訴我電量', 'FLIGHT_CMD'], ['不要返航', 'FLIGHT_CMD'], ['能不能返航', 'QA'],
  ['為什麼電量掉這麼快', 'NO_CAUSE_ANALYSIS'],
  // v1 §A-1 例句
  ['最近一趟電量掉多快', 'QA'], ['把地圖放大', 'UI_OP'], ['剛剛那個告警是什麼', 'ALERT_Q'],
  ['幫我規劃巡檢航線', 'MISSION'], ['產生這趟的報告', 'REPORT'], ['起飛', 'FLIGHT_CMD'], ['拍照', 'FLIGHT_CMD'],
  // 邊界
  ['', 'INVALID_INPUT'], ['？？！！', 'INVALID_INPUT'], ['   ', 'INVALID_INPUT'],
  ['返航高度怎麼設定', 'QA'], ['ＲＴＬ 返航', 'FLIGHT_CMD'], ['island 的地圖', 'QA'], ['land', 'FLIGHT_CMD']
]
for (const [input, want] of gateCases) t('gate ' + JSON.stringify(input), () => assert.strictEqual(cls(input), want))
t('gate 200 字不算過長', () => assert.notStrictEqual(cls('電量' + '多'.repeat(198)), 'INPUT_TOO_LONG'))
t('gate 201 字、後半句是返航：不截斷、不路由', () => {
  const g = Gate.gate('電量' + '多'.repeat(197) + '返航')
  assert.strictEqual(g['class'], 'INPUT_TOO_LONG'); assert.strictEqual(g.reply, Gate.REPLY_TOO_LONG)
})
t('gate 來源一律是 rule', () => assert.strictEqual(Gate.gate('電量現在多少').source, 'rule'))
t('gate 同一輸入兩次結果相同', () => assert.deepStrictEqual(Gate.gate('把地圖放大'), Gate.gate('把地圖放大')))
t('gate CLARIFY 列兩類', () => { const g = Gate.gate('告警報告'); assert.strictEqual(g['class'], 'CLARIFY'); assert.deepStrictEqual(g.clarify, ['ALERT_Q', 'REPORT']) })
t('名詞例外只遮剛好那幾個字', () => assert.strictEqual(Gate.maskNouns('顯示返航點後立即返航').text.slice(-2), '返航'))

// ---------------- Router
t('router QA 選工具', () => assert.deepStrictEqual(Gate.route('電量現在多少').tools, ['T_TELEMETRY', 'T_ENERGY']))
t('router 沒命中走手冊', () => assert.deepStrictEqual(Gate.route('返航點在哪裡').tools, ['T_MANUAL_SEARCH']))
t('router ALERT_Q 固定先跑告警歷史', () => assert.strictEqual(Gate.route('剛剛那個告警是什麼').tools[0], 'T_ALERT_HISTORY'))
t('router 飛控指令不進工具', () => { const r = Gate.route('起飛'); assert.strictEqual(r.handler, 'safety_hold'); assert.deepStrictEqual(r.tools, []) })
t('router 最多 3 個工具', () => { const r = Gate.route('目前電量 上一趟紀錄 告警 手冊'); assert.strictEqual(r.tools.length, 3); assert.strictEqual(r.tools_truncated, true) })
t('router RouteRecord 欄位', () => {
  const r = Gate.route('把地圖放大', { request_id: 'r1', sha256Hex: Hash.sha256Hex, timestamp_utc8: '2026-11-15T20:00:00+08:00' })
  assert.deepStrictEqual(Object.keys(r.record), ['request_id', 'input_hash', 'context_ref', 'gate_stage', 'category_id', 'candidates', 'selected_handler', 'parameter_source', 'reason_code', 'policy_version', 'timestamp_utc8'])
  assert.strictEqual(r.record.input_hash, crypto.createHash('sha256').update('把地圖放大').digest('hex'))
})
t('參數候選：1 個自動、0 個查不到、多個請使用者選且最多 5 個', () => {
  const c = n => Array.from({ length: n }, (_, i) => ({ candidate_id: 'L' + i }))
  assert.strictEqual(Gate.resolveParam(c(1)).status, 'AUTO')
  assert.strictEqual(Gate.resolveParam(c(0)).status, 'NOT_FOUND')
  const m = Gate.resolveParam(c(7)); assert.strictEqual(m.status, 'CLARIFY'); assert.strictEqual(m.options.length, 5); assert.strictEqual(m.selected, null)
})
for (const s of ['', 'abc', '電量現在多少', 'a'.repeat(55), 'a'.repeat(56), 'a'.repeat(64), '🚁返航點' + 'x'.repeat(200)])
  t('sha256 ' + s.length, () => assert.strictEqual(Hash.sha256Hex(s), crypto.createHash('sha256').update(s).digest('hex')))

// ---------------- 電量斜率：v1 §C-4
const ramp = (n, dt, slopePerMin, soc0 = 80) => Array.from({ length: n }, (_, i) => ({ t: i * dt, soc: soc0 + slopePerMin * (i * dt) / 60 }))
const E = (s, o) => Tools.energyTrend(s, Object.assign({ reservePct: 20 }, o || {}))
t('斜率 −1.0', () => { const r = E(ramp(61, 1, -1)); assert.strictEqual(r.status, 'OK'); assert(Math.abs(r.detail.slope_pct_per_min + 1) < 1e-9); assert.strictEqual(r.detail.direction, '下降'); assert(Math.abs(r.detail.eta_min - 59) < 1e-6) })
t('斜率 0（全部相同值）', () => { const r = E(ramp(61, 1, 0)); assert.strictEqual(r.status, 'OK'); assert.strictEqual(r.detail.direction, '持平'); assert.strictEqual(r.detail.r2, null); assert.strictEqual(r.detail.eta_min, null) })
t('斜率 +0.5', () => { const r = E(ramp(61, 1, 0.5, 50)); assert.strictEqual(r.detail.direction, '上升'); assert.strictEqual(r.detail.eta_min, null) })
t('剛好 10 筆', () => assert.strictEqual(E(ramp(10, 6, -1)).status, 'OK'))
t('只有 9 筆', () => { const r = E(ramp(9, 6.5, -1)); assert.strictEqual(r.status, 'INSUFFICIENT'); assert.strictEqual(r.detail.reason, 'n_valid') })
t('覆蓋率 0.80', () => assert.strictEqual(E(ramp(13, 4, -1)).status, 'OK'))
t('覆蓋率 0.79', () => { const r = E(ramp(11, 4.74, -1)); assert.strictEqual(r.status, 'INSUFFICIENT'); assert.strictEqual(r.detail.reason, 'coverage') })
t('中間缺 11 秒', () => { const s = ramp(61, 1, -1).filter(p => p.t <= 20 || p.t >= 31); const r = E(s); assert.strictEqual(r.status, 'INSUFFICIENT'); assert.strictEqual(r.detail.reason, 'gap') })
t('亂序 20% 接受、21% 拒絕', () => {
  const mk = k => { const s = ramp(100, 0.6, -1); for (let i = 0; i < k; ++i) { const j = 4 * i + 1; [s[j], s[j + 1]] = [s[j + 1], s[j]] } return s }
  assert.strictEqual(E(mk(20)).detail.disorder_ratio, 0.2); assert.strictEqual(E(mk(20)).status, 'OK')
  assert.strictEqual(E(mk(21)).status, 'INSUFFICIENT'); assert.strictEqual(E(mk(21)).detail.reason, 'disorder')
})
t('含 NaN、非有限時間戳、未來時間戳：丟掉並計數', () => {
  const s = ramp(61, 1, -1); s.push({ t: 30.5, soc: NaN }, { t: Infinity, soc: 50 }, { t: 500, soc: 50 }, { t: 31.5, soc: 140 })
  const r = E(s, { now: 60 }); assert.strictEqual(r.status, 'OK'); assert.strictEqual(r.detail.n_dropped, 4); assert(Math.abs(r.detail.slope_pct_per_min + 1) < 1e-9)
})
t('先清理再取視窗：壞的最後一筆不會變成 t_end', () => { const s = ramp(61, 1, -1); s.push({ t: 300, soc: -5 }); assert.strictEqual(E(s).coverage.requested[1], 60) })
t('時間戳重複只留最後到達的一筆', () => { const s = ramp(61, 1, -1); s.push({ t: 60, soc: 79 }); const r = E(s); assert.strictEqual(r.facts[1].value, 79) })
t('電量已低於保留值：不算 ETA', () => { const r = E(ramp(61, 1, -1, 15)); assert.strictEqual(r.detail.direction, '下降'); assert.strictEqual(r.detail.eta_min, null) })
t('保留值無效：照算斜率、不算 ETA', () => { const r = E(ramp(61, 1, -1), { reservePct: NaN }); assert.strictEqual(r.status, 'OK'); assert.strictEqual(r.detail.reserve_invalid, true); assert.strictEqual(r.detail.eta_min, null) })
t('R² 不足', () => { const s = ramp(61, 1, 0).map((p, i) => ({ t: p.t, soc: 50 + (i % 2 ? 3 : -3) })); const r = E(s); assert.strictEqual(r.status, 'INSUFFICIENT'); assert.strictEqual(r.detail.reason, 'r2') })
t('過期（只在問目前時檢查）', () => { assert.strictEqual(E(ramp(61, 1, -1), { now: 63, checkStale: true }).status, 'STALE'); assert.strictEqual(E(ramp(61, 1, -1), { now: 63 }).status, 'OK') })
t('讀不到來源、機型不支援', () => { assert.strictEqual(E(null).status, 'UNAVAILABLE'); assert.strictEqual(E(ramp(61, 1, -1), { vehicleType: 'fixedwing' }).status, 'UNSUPPORTED') })
t('ETA 超過 600 分鐘不輸出', () => assert.strictEqual(E(ramp(61, 1, -0.06)).detail.eta_min, null))

// ---------------- 其他工具
t('遙測：最新一筆、超過 2 秒標過期', () => {
  const s = [{ t: 1, value: 10 }, { t: 3, value: 12 }, { t: 2, value: 11 }]
  assert.strictEqual(Tools.telemetryLatest('alt', 'm', s, 4).facts[0].value, 12)
  assert.strictEqual(Tools.telemetryLatest('alt', 'm', s, 5).status, 'OK')
  assert.strictEqual(Tools.telemetryLatest('alt', 'm', s, 5.1).status, 'STALE')
  assert.strictEqual(Tools.telemetryLatest('alt', 'm', null, 5).status, 'UNAVAILABLE')
})
t('飛行紀錄：統計與分桶', () => {
  const s = Array.from({ length: 1000 }, (_, i) => ({ t: i, value: Math.sin(i / 20) * 10 }))
  const r = Tools.flightlogSeries('alt', 'm', s, 0, 999)
  assert.strictEqual(r.status, 'OK'); assert(r.facts[0].points.length <= 300); assert.strictEqual(r.facts[0].downsampled, true)
  const vals = s.map(p => p.value); assert.strictEqual(r.facts[1].value, Math.min(...vals)); assert.strictEqual(r.facts[2].value, Math.max(...vals))
  assert(r.facts[0].points.some(p => p.value === Math.max(...vals)))
  assert.strictEqual(Tools.flightlogSeries('alt', 'm', s, 0, 999, [{ t0: 100, t1: 120 }]).status, 'PARTIAL')
  assert.strictEqual(Tools.flightlogSeries('alt', 'm', [], 0, 10).status, 'EMPTY_COMPLETE')
})
const EV = [{ t: 10, level: 'warning', predictor: 'P1', text: 'a' }, { t: 30, level: 'critical', predictor: 'P1', text: 'b' }, { t: 50, level: 'warning', predictor: 'P2', text: 'c' }]
t('告警歷史：過濾、計數、由新到舊', () => {
  const r = Tools.alertHistory(EV, { t0: 0, t1: 60 }); assert.strictEqual(r.status, 'OK'); assert.strictEqual(r.facts[0].value, 3); assert.strictEqual(r.facts[1].rows[0].t, 50)
  assert.strictEqual(Tools.alertHistory(EV, { t0: 0, t1: 60, level: 'critical' }).facts[0].value, 1)
  assert.strictEqual(Tools.alertHistory(EV, { t0: 100, t1: 200 }).status, 'EMPTY_COMPLETE')
  assert.strictEqual(Tools.alertHistory(EV, { t0: 100, t1: 200 }, [{ t0: 120, t1: 130 }]).status, 'PARTIAL')
})
const CH = [{ chunk_id: 'c1', doc: 'PX4', heading: 'Return Mode', version: 'v1.17.0', text: 'Return mode causes the vehicle to fly to a safe location. RTL_RETURN_ALT sets the return altitude.' },
            { chunk_id: 'c2', doc: 'QGC', heading: 'Fly View', version: 'v5.0', text: 'The Fly View is used to command and monitor the vehicle when flying.' },
            { chunk_id: 'c3', doc: 'PX4', heading: 'Battery', version: 'v1.17.0', text: 'Battery failsafe triggers when the battery level is low.' }]
t('手冊檢索：中英對照補詞、標降級、查不到', () => {
  const r = Tools.manualSearch(CH, '返航高度怎麼設定', { '返航': ['return', 'rtl'], '高度': ['altitude'] })
  assert.strictEqual(r.status, 'OK'); assert.strictEqual(r.degraded, true); assert.strictEqual(r.facts[0].chunk_id, 'c1')
  assert.strictEqual(Tools.manualSearch(CH, '返航高度怎麼設定', {}).status, 'EMPTY_COMPLETE')
})

// ---------------- claim：v3 §D
const okE = E(ramp(61, 1, -1)), stale = Tools.telemetryLatest('alt', 'm', [{ t: 1, value: 10 }], 9)
const partialA = Tools.alertHistory(EV, { t0: 0, t1: 60 }, [{ t0: 20, t1: 25 }]), noneA = Tools.alertHistory(EV, { t0: 100, t1: 200 })
t('必顯示句由程式固定放最前面，順序 過期→不完整', () => {
  const a = Claims.answer([partialA, stale, okE])
  assert.deepStrictEqual(a.lines.slice(0, 2).map(l => l.template_id), ['T-STALE', 'T-PARTIAL']); assert(a.lines[0].mandatory && a.lines[1].mandatory)
})
t('模型只選好消息：必顯示句照樣出現', () => {
  const c = Claims.generate([partialA, okE]), good = c.optional.find(x => x.template_id === 'T-TREND').claim_id
  const a = Claims.answer([partialA, okE], {}, { schema: 'qa.claims/1', selected_claim_ids: [good] })
  assert.strictEqual(a.source, 'model'); assert.deepStrictEqual(a.lines.map(l => l.template_id), ['T-PARTIAL', 'T-TREND'])
})
t('PARTIAL 不產生趨勢與「沒有」，數值句加（資料不完整）', () => {
  const c = Claims.generate([partialA]); assert(!c.optional.some(x => x.template_id === 'T-NONE' || x.template_id === 'T-TREND'))
  assert(c.optional.find(x => x.template_id === 'T-COUNT').text.endsWith('（資料不完整）'))
})
t('只有完整且為 0 的告警計數才說沒有告警', () => assert.deepStrictEqual(Claims.answer([noneA]).lines.map(l => l.template_id), ['T-NONE']))
t('手冊查不到用 T-DOC-NONE，不說沒有告警', () => { const a = Claims.answer([Tools.manualSearch(CH, 'zzz', {})]); assert.strictEqual(a.lines[0].template_id, 'T-DOC-NONE'); assert.strictEqual(a.lines[0].text, '手冊裡查不到相關內容') })
const c0 = Claims.generate([okE]), ids0 = c0.optional.map(x => x.claim_id)
const sel = x => Claims.validateSelection(x, c0)
t('D-3 合法選擇照模型順序', () => { const v = sel({ schema: 'qa.claims/1', selected_claim_ids: [ids0[1], ids0[0]] }); assert(v.ok); assert.deepStrictEqual(v.ids, [ids0[1], ids0[0]]) })
t('D-3 重複去重', () => { const v = sel({ schema: 'qa.claims/1', selected_claim_ids: [ids0[0], ids0[0]] }); assert(v.ok && v.dedup); assert.deepStrictEqual(v.ids, [ids0[0]]) })
for (const [name, raw, reason] of [
  ['空集合', { schema: 'qa.claims/1', selected_claim_ids: [] }, 'empty'], ['未知 ID', { schema: 'qa.claims/1', selected_claim_ids: ['C99'] }, 'unknown_id'],
  ['多餘欄位', { schema: 'qa.claims/1', selected_claim_ids: [ids0[0]], note: '電量上升' }, 'extra_field'], ['JSON 壞掉', '{"schema":', 'json_parse'],
  ['ID 不是字串', { schema: 'qa.claims/1', selected_claim_ids: [1] }, 'id_type'], ['schema 錯', { schema: 'x', selected_claim_ids: [ids0[0]] }, 'schema']])
  t('D-3 ' + name + ' 整份退回規則', () => {
    assert.strictEqual(sel(raw).fallback_reason, reason)
    const a = Claims.answer([okE], {}, raw); assert.strictEqual(a.source, 'rule'); assert.strictEqual(a.fallback_reason, reason)
  })
t('D-3 選了必顯示句：整份退回', () => { const c = Claims.generate([partialA]); assert.strictEqual(Claims.validateSelection({ schema: 'qa.claims/1', selected_claim_ids: [c.mandatory[0].claim_id] }, c).fallback_reason, 'selected_mandatory') })
t('名額 = 8 − 必顯示句數；超過整份退回；規則版記 claims_truncated', () => {
  const many = Tools.manualSearch(Array.from({ length: 5 }, (_, i) => ({ chunk_id: 'k' + i, doc: 'D', heading: 'H' + i, version: 'v', text: 'battery level ' + i })), 'battery', {})
  const tr = [many, Tools.flightlogSeries('alt', 'm', Array.from({ length: 20 }, (_, i) => ({ t: i, value: i })), 0, 19), stale], c = Claims.generate(tr)
  assert.strictEqual(Claims.quota(c), 7); assert.strictEqual(c.optional.length, 9)
  assert.strictEqual(Claims.validateSelection({ schema: 'qa.claims/1', selected_claim_ids: c.optional.map(x => x.claim_id).slice(0, 8) }, c).fallback_reason, 'over_quota')
  const a = Claims.answer(tr); assert.strictEqual(a.lines.length, 8); assert.strictEqual(a.claims_truncated, 2); assert.strictEqual(a.lines[0].template_id, 'T-STALE')
})
t('E# 依第一次出現編號', () => { const a = Claims.answer([okE]); assert.deepStrictEqual(a.evidence.map(e => e.id), ['E1', 'E2']); assert.strictEqual(a.lines[0].evidence_ids[0], 'E1') })
t('句子的數字來自事實', () => { const a = Claims.answer([okE]); assert(a.lines.some(l => l.text === '照目前趨勢，約 59 分鐘後到保留電量')); assert(a.lines.some(l => l.text.startsWith('電量 目前是 79%'))) })
t('門檻比較：單位不同不產生', () => {
  const tr = [Tools.telemetryLatest('soc', '%', [{ t: 1, value: 30 }], 1)]
  assert(Claims.generate(tr, { thresholds: [{ subject: 'soc', value: 20, unit: '%', label: '保留電量' }] }).optional.some(x => x.text === '電量 高於保留電量 20%'))
  assert(!Claims.generate(tr, { thresholds: [{ subject: 'soc', value: 20, unit: 'V' }] }).optional.some(x => x.template_id === 'T-THRESH'))
})

// ---------------- UiPlanner、LayoutEngine、Validator：候選 ADR §4 固定案例
const VP = { width: 1920, height: 1080, revision: 7 }
const ansE = Claims.answer([okE]), planE = Layout.plan('req1', ansE, [okE])
const trAll = [okE, Tools.alertHistory(EV, { t0: 0, t1: 60 }), Tools.manualSearch(CH, 'battery', {})]
const planAll = Layout.plan('req2', Claims.answer(trAll), trAll)
t('只有 W1：不用確認', () => { const p = Layout.plan('r', Claims.answer([noneA]), [noneA]); assert.deepStrictEqual(p.nodes.map(n => n.component_id), ['W1_FACT']); assert.strictEqual(Layout.needsConfirm(p), false) })
t('趨勢答案：W1＋W2＋W4，要按套用', () => { assert.deepStrictEqual(planE.nodes.map(n => n.component_id), ['W1_FACT', 'W2_SERIES', 'W4_DIAG']); assert.strictEqual(Layout.needsConfirm(planE), true) })
t('含嚴重告警的表格不可省略', () => { const w3 = planAll.nodes.find(n => n.component_id === 'W3_TABLE'); assert.strictEqual(w3.required, true); assert.strictEqual(w3.priority, 90) })
t('1920×1080 排版：幾何固定', () => {
  const r = Layout.layout(planAll, VP); assert(r.ok, r.error)
  // 欄寬 145、間距 16：6 欄 = 950；第 7 欄起點 = 966。W3 建議 12 欄放不下第一列剩下的 6 欄，改用最小 6 欄。
  assert.deepStrictEqual(r.layout.rects.map(x => [x.node_id, x.x, x.y, x.width, x.height]),
    [['n1', 0, 0, 950, 240], ['n4', 966, 0, 950, 240], ['n3', 0, 256, 950, 240], ['n2', 966, 256, 950, 240], ['n5', 0, 512, 1916, 160]])
  assert.strictEqual(r.layout.total_height, 672)
  assert.strictEqual(Layout.validateLayout(planAll, r.layout, VP).ok, true)
})
t('同一輸入跑兩次幾何完全相同', () => assert.deepStrictEqual(Layout.layout(planAll, VP), Layout.layout(planAll, VP)))
t('內容區變矮：先縮到最小高度，再刪可省略的', () => {
  const a = Layout.layout(planAll, { width: 1920, height: 600, revision: 1 }); assert(a.ok); assert.strictEqual(a.layout.compact, true); assert.deepStrictEqual(a.layout.dropped, [])
  const b = Layout.layout(planAll, { width: 1920, height: 400, revision: 1 }); assert(b.ok); assert.deepStrictEqual(b.layout.dropped, ['n5'])
  const c = Layout.layout(planAll, { width: 1920, height: 200, revision: 1 }); assert(c.ok); assert.deepStrictEqual(c.layout.dropped, ['n5', 'n2', 'n3'])
  assert.deepStrictEqual(c.layout.rects.map(x => x.node_id), ['n1', 'n4'])
})
t('必要元件放不下：拒絕整份', () => assert.strictEqual(Layout.layout(planAll, { width: 1920, height: 120, revision: 1 }).error, 'REQUIRED_OVERFLOW'))
t('模型輸出座標被拒', () => { const p = JSON.parse(JSON.stringify(planE)); p.nodes[1].x = 10; assert.strictEqual(Layout.layout(p, VP).error, 'NODE_UNKNOWN_FIELD') })
for (const [name, mut, code] of [
  ['白名單外的元件', p => { p.nodes[1].component_id = 'W9_MAP' }, 'NOT_IN_CATALOG'], ['重複 order', p => { p.order[1] = p.order[0] }, 'ORDER_MISMATCH'],
  ['缺節點', p => { p.order.pop() }, 'ORDER_LENGTH'], ['非法 size_class', p => { p.nodes[1].size_class = 'XL' }, 'SIZE_CLASS'],
  ['別的請求的資料', p => { p.nodes[1].binding_ref.request_id = 'other' }, 'BINDING_FOREIGN'], ['沒有 W1', p => { p.nodes[0].component_id = 'W2_SERIES' }, 'W1_MISSING'],
  ['超過 5 個', p => { for (let i = 0; i < 4; ++i) p.nodes.push(Object.assign({}, p.nodes[1], { node_id: 'x' + i })) }, 'NODE_COUNT'],
  ['計畫多餘欄位', p => { p.note = 'x' }, 'PLAN_UNKNOWN_FIELD'], ['目錄版本不符', p => { p.catalog_id = 'old' }, 'CATALOG_VERSION']])
  t('預檢拒絕：' + name, () => { const p = JSON.parse(JSON.stringify(planE)); mut(p); assert.strictEqual(Layout.validatePlan(p).error, code) })
t('幾何檢查：重疊、出界、小於最小尺寸、遮到告警區、版本不符', () => {
  const base = () => JSON.parse(JSON.stringify(Layout.layout(planE, VP).layout)), chk = (l, vp, ar) => Layout.validateLayout(planE, l, vp || VP, ar).error
  let l = base(); l.rects[1].y = 0; l.rects[1].x = 0; assert.strictEqual(chk(l), 'OVERLAP')
  l = base(); l.rects[0].width = 5000; assert.strictEqual(chk(l), 'OUT_OF_BOUNDS')
  l = base(); l.rects[0].height = 10; assert.strictEqual(chk(l), 'BELOW_MIN_SIZE')
  l = base(); l.rects[0].x = NaN; assert.strictEqual(chk(l), 'RECT_NOT_FINITE')
  assert.strictEqual(chk(base(), VP, { x: 100, y: 100, width: 50, height: 50 }), 'ALERT_OCCLUDED')
  assert.strictEqual(chk(base(), { width: 1920, height: 1080, revision: 8 }), 'VIEWPORT_REVISION')
  l = base(); l.rects.shift(); assert.strictEqual(chk(l), 'REQUIRED_MISSING')
})
t('規則全路徑（backend=none）：問句到版面一路跑完', () => {
  const r = Gate.route('最近一趟電量掉多快', { request_id: 'q1', sha256Hex: Hash.sha256Hex }); assert.strictEqual(r.handler, 'qa_pipeline'); assert(r.tools.includes('T_ENERGY'))
  const tr = [E(ramp(61, 1, -1))], a = Claims.answer(tr), p = Layout.plan('q1', a, tr), l = Layout.layout(p, VP)
  assert.strictEqual(a.source, 'rule'); assert(l.ok); assert.strictEqual(Layout.validateLayout(p, l.layout, VP).ok, true)
})
console.log('pass ' + pass + ' / fail ' + fail)
process.exit(fail ? 1 : 0)
