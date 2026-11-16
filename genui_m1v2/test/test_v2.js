// GenUI m1v2 固定案例。執行：node genui_m1v2/test/test_v2.js
// 案例來源：契約附件 v3 §A-5、v3.1 草案 §A-3' 固定案例、Codex run2b §4-4、§4-5、§4-6、§4-1 E07、K-6。
// 預期值都由條文推導，在第一次執行前提交；執行一次，輸出原樣存進 runs/。
const assert = require('assert')
const { Gate, Tools, Claims, Layout } = require('./load.js')
let pass = 0, fail = 0
function t(name, fn) { try { fn(); pass++ } catch (e) { fail++; console.log('FAIL ' + name + '\n  ' + String(e.message).split('\n').join('\n  ')) } }
const cls = s => Gate.gate(s)['class']

// ---------------- Gate：v3 §A-5（保留）與 v3.1 §A-3'（新增）
for (const [input, want] of [
  ['今天天氣如何', 'OUT_OF_DOMAIN'], ['如何', 'OUT_OF_DOMAIN'], ['那現在呢', 'OUT_OF_DOMAIN'], ['電量現在多少', 'QA'], ['返航點在哪裡', 'QA'],
  ['顯示返航點後立即返航', 'FLIGHT_CMD'], ['返航，然後告訴我電量', 'FLIGHT_CMD'], ['不要返航', 'FLIGHT_CMD'], ['能不能返航', 'QA'],
  ['為什麼電量掉這麼快', 'NO_CAUSE_ANALYSIS'],
  ['能不能再次返航', 'QA'], ['電量多少再返航', 'FLIGHT_CMD'], ['現在電量多少？立即返航', 'FLIGHT_CMD'], ['現在電量多少\n立即返航', 'FLIGHT_CMD'],
  ['為什麼返航', 'NO_CAUSE_ANALYSIS'], ['㐀', 'OUT_OF_DOMAIN'], ['起飛', 'FLIGHT_CMD'], ['land', 'FLIGHT_CMD'], ['island 的地圖', 'QA'],
  ['', 'INVALID_INPUT'], ['？？！！', 'INVALID_INPUT']
]) t('gate ' + JSON.stringify(input), () => assert.strictEqual(cls(input), want))
for (const s of ['返航後電量會剩多少', '返航高度設多少', '返航？', '可以返航嗎'])
  t('gate 不是飛控命令 ' + s, () => assert.notStrictEqual(cls(s), 'FLIGHT_CMD'))
t('gate 200 字（擴充 B 字）不算過長', () => assert.notStrictEqual(cls('電量' + '𠀀'.repeat(198)), 'INPUT_TOO_LONG'))
t('gate 201 字（擴充 B 字）過長', () => assert.strictEqual(cls('電量' + '𠀀'.repeat(199)), 'INPUT_TOO_LONG'))
t('normalize 全形與全形空白', () => assert.strictEqual(Gate.normalize('Ａ　Ｂ'), 'a b'))
t('能力檢查在 node 通過', () => assert.strictEqual(Gate.capabilityOk(), true))
t('單一正分未達 T：只問這一類', () => { const g = Gate.gate('異常'); assert.strictEqual(g['class'], 'CLARIFY_ONE'); assert.deepStrictEqual(g.clarify, ['ALERT_Q']) })
t('兩類同分：列兩個正分類別', () => { const g = Gate.gate('告警報告'); assert.strictEqual(g['class'], 'CLARIFY'); assert.deepStrictEqual(g.clarify, ['ALERT_Q', 'REPORT']) })
t('CLARIFY 不含零分類別', () => {
  for (const s of ['異常', '告警報告', '電量', '高度']) { const g = Gate.gate(s); for (const c of g.clarify) assert(g.scores[c] > 0, s + ' ' + c) }
})
t('router 截掉的工具回傳 omitted_tools', () => {
  const r = Gate.route('目前電量 上一趟紀錄 告警 手冊')
  assert.deepStrictEqual(r.tools, ['T_TELEMETRY', 'T_FLIGHTLOG', 'T_ENERGY']); assert.deepStrictEqual(r.omitted_tools, ['T_ALERT_HISTORY', 'T_MANUAL_SEARCH'])
})

// ---------------- 工具資料
const R = (a, b) => Array.from({ length: 61 }, (_, t) => ({ t, soc: a + b * t / 60 }))
const O = x => Object.assign({ now: 60, reservePct: 20, vehicleType: 'multirotor' }, x || {})
const e01 = () => Tools.energyTrend(R(80, -1), O())
t('E07 非有限保留值（下降）', () => { for (const v of [NaN, Infinity, -Infinity]) { const d = Tools.energyTrend(R(80, -1), O({ reservePct: v })).detail
  assert.strictEqual(d.reserve_invalid, true); assert.strictEqual(d.eta_min, null); assert.strictEqual(d.eta_reason, 'reserve_invalid'); assert(Math.abs(d.slope_pct_per_min + 1) < 1e-9) } })
t('E07 非有限保留值（持平）', () => { for (const v of [NaN, Infinity]) { const r = Tools.energyTrend(R(80, 0), O({ reservePct: v }))
  assert.strictEqual(r.status, 'OK'); assert.strictEqual(r.detail.direction, '持平'); assert.strictEqual(r.detail.reserve_invalid, true) } })
const tel = (v, t, now) => Tools.telemetryLatest('soc', '%', [{ t, value: v }], now)
const fl = Tools.flightlogSeries('alt', 'm', Array.from({ length: 61 }, (_, i) => ({ t: i, value: 10 + i })), 0, 60, [])
const alerts3 = Tools.alertHistory([{ t: 10, level: 'critical', predictor: 'p', text: 'a' }, { t: 20, level: 'warning', predictor: 'p', text: 'b' }, { t: 30, level: 'info', predictor: 'p', text: 'c' }], { t0: 0, t1: 60 }, [])
const man = Tools.manualSearch([{ chunk_id: 'k1', doc: 'D', heading: 'RTL', version: 'v1', text: '返航保留電量的設定方式：在參數頁設定 RTL 保留電量' },
                                { chunk_id: 'k2', doc: 'D', heading: '電池', version: 'v1', text: '電池廢棄處理：電量耗盡的電池請回收' }], '如何設定返航保留電量', {})
t('手冊：只中一個內容詞的片段不合格', () => { assert.strictEqual(man.status, 'OK'); assert.deepStrictEqual(man.facts.map(f => f.chunk_id), ['k1']) })
t('手冊：無關問題查不到', () => assert.strictEqual(Tools.manualSearch([{ chunk_id: 'k1', doc: 'D', heading: 'h', version: 'v1', text: '返航保留電量' }], '今天午餐吃什麼', {}).status, 'EMPTY_COMPLETE'))
t('手冊：chunk_id 是 constructor 之類的字也不出錯', () => assert.strictEqual(Tools.manualSearch([{ chunk_id: 'constructor', doc: 'D', heading: 'h', version: 'v1', text: 'constructor battery' }], 'toString', {}).status, 'EMPTY_COMPLETE'))

// ---------------- 答案句（§4-4）
t('4-4-1 PARTIAL 零筆告警：T-PARTIAL＋0 筆 T-COUNT，沒有 T-NONE', () => {
  const r = Tools.alertHistory([], { t0: 0, t1: 60 }, [{ t0: 20, t1: 25 }]), c = Claims.generate([r], {})
  assert.strictEqual(r.status, 'PARTIAL')
  assert.deepStrictEqual(c.mandatory.map(x => x.template_id), ['T-PARTIAL'])
  const cnt = c.optional.filter(x => x.template_id === 'T-COUNT'); assert.strictEqual(cnt.length, 1)
  assert(cnt[0].text.includes(' 0 筆') && cnt[0].text.endsWith('（資料不完整）'), cnt[0].text)
  assert(!c.optional.some(x => x.template_id === 'T-NONE'))
})
t('4-4-2 被截掉的工具固定揭露，模型只選一句也保留', () => {
  const res = [tel(79, 60, 60), fl, e01()], ctx = { omitted_tools: ['T_ALERT_HISTORY', 'T_MANUAL_SEARCH'] }
  const c = Claims.generate(res, ctx), first = c.optional[0].claim_id
  const a = Claims.answer(res, ctx, JSON.stringify({ schema: 'qa.claims/1', selected_claim_ids: [first] }))
  assert.strictEqual(a.source, 'model')
  assert.strictEqual(a.lines[0].template_id, 'T-OMITTED'); assert.strictEqual(a.lines[0].text, '本次未執行：告警紀錄、手冊（一次最多查三項）')
  assert.strictEqual(a.lines.length, 2)
})
t('4-4-3 模型多帶自由文字欄位：整份退回規則版，不出現 999', () => {
  const a = Claims.answer([e01()], {}, '{"schema":"qa.claims/1","selected_claim_ids":["C1"],"text":"電量999%"}')
  assert.strictEqual(a.source, 'rule'); assert.strictEqual(a.fallback_reason, 'extra_field'); assert(!JSON.stringify(a).includes('999'))
})
t('4-4-3 合法 JSON 後面多一段文字：json_parse', () => {
  const a = Claims.answer([e01()], {}, '{"schema":"qa.claims/1","selected_claim_ids":["C1"]} 電量999%')
  assert.strictEqual(a.fallback_reason, 'json_parse'); assert(!JSON.stringify(a).includes('999'))
})
const mixed = () => [tel(79, 50, 60), Tools.alertHistory([{ t: 10, level: 'warning', predictor: 'p', text: 'x' }], { t0: 0, t1: 60 }, [{ t0: 20, t1: 25 }]),
                     Tools.energyTrend(R(80, -1).slice(0, 5), O())]
t('4-4-4 必顯示組依 過期→不完整→樣本不足', () => assert.deepStrictEqual(Claims.generate(mixed(), {}).mandatory.map(x => x.template_id), ['T-STALE', 'T-PARTIAL', 'T-CANNOT']))
t('4-4-4 選中必顯示 ID 整份退回', () => {
  const c = Claims.generate(mixed(), {}), a = Claims.answer(mixed(), {}, { schema: 'qa.claims/1', selected_claim_ids: [c.mandatory[0].claim_id] })
  assert.strictEqual(a.fallback_reason, 'selected_mandatory')
})
t('4-4-4 只選可選句時三句必顯示仍在最前', () => {
  const c = Claims.generate(mixed(), {}), a = Claims.answer(mixed(), {}, { schema: 'qa.claims/1', selected_claim_ids: [c.optional[0].claim_id] })
  assert.strictEqual(a.source, 'model'); assert.deepStrictEqual(a.lines.slice(0, 3).map(l => l.template_id), ['T-STALE', 'T-PARTIAL', 'T-CANNOT'])
})
t('4-4-5 九個可選、一個必顯示：規則版 8 句、截掉 2、顯示告知', () => {
  const res = [tel(79, 50, 60), fl, alerts3], ctx = { thresholds: [{ subject: 'alt.max', value: 50, unit: 'm' }, { subject: 'alt.min', value: 50, unit: 'm' }] }
  const c = Claims.generate(res, ctx); assert.strictEqual(c.mandatory.length, 1); assert.strictEqual(c.optional.length, 9)
  const a = Claims.answer(res, ctx); assert.strictEqual(a.lines.length, 8); assert.strictEqual(a.claims_truncated, 2); assert.strictEqual(a.truncation_notice, '還有 2 項，見資料表')
})
t('過期又樣本不足：一句合併句', () => {
  const r = Tools.energyTrend([{ t: 0, soc: 80 }], { now: 10, checkStale: true, reservePct: 20 }), c = Claims.generate([r], {})
  assert.strictEqual(c.mandatory.length, 1); assert(c.mandatory[0].text.includes('已過期') && c.mandatory[0].text.includes('且樣本不足'), c.mandatory[0].text)
})
t('保留值 100：有「不估計剩餘時間」句，沒有 T-ETA', () => {
  const c = Claims.generate([Tools.energyTrend(R(80, -1), O({ reservePct: 100 }))], {})
  assert(c.optional.some(x => x.template_id === 'T-ETA-NA' && x.text === '目前電量已不高於保留電量，不估計剩餘時間')); assert(!c.optional.some(x => x.template_id === 'T-ETA'))
})
t('飛行紀錄數值用「該趟紀錄中」', () => assert(Claims.generate([fl], {}).optional.every(x => x.text.startsWith('該趟紀錄中'))))

// ---------------- 排版與 UiPlan 驗證（§4-5、K-6）
const k6res = () => [e01(), alerts3, Tools.manualSearch([{ chunk_id: 'k1', doc: 'D', heading: 'RTL', version: 'v1', text: '返航保留電量的設定方式' }], '返航保留電量', {})]
const k6 = () => { const res = k6res(), a = Claims.answer(res, {}); return { res, a, p: Layout.plan('r1', a, res) } }
t('K-6 計畫：W1、W2、W4、W3（必要 90）、W5', () => {
  const { p } = k6(); assert.deepStrictEqual(p.nodes.map(n => n.component_id), ['W1_FACT', 'W2_SERIES', 'W4_DIAG', 'W3_TABLE', 'W5_DOC'])
  assert.strictEqual(p.nodes[3].required, true); assert.strictEqual(p.nodes[3].priority, 90)
})
t('L05 趨勢圖綁到可畫的序列', () => {
  const { res, p } = k6(), w2 = p.nodes.find(n => n.component_id === 'W2_SERIES')
  assert.deepStrictEqual(w2.binding_ref, { request_id: 'r1', kind: 'series', ref: '0:F3' })
  const f = res[0].facts.find(x => x.fact_id === 'F3'); assert.strictEqual(f.points.length, 61); assert.deepStrictEqual(f.points[0], { t: 0, soc: 80 })
})
const L = (h, w = 1920) => { const { res, p } = k6(); return Layout.layout(p, { width: w, height: h, revision: 1 }, res) }
t('K-6 1920×1080 矩形', () => {
  const r = L(1080); assert(r.ok, r.error)
  const m = Object.fromEntries(r.layout.rects.map(x => [x.node_id, [x.x, x.y, x.width, x.height]]))
  assert.deepStrictEqual(m, { n1: [0, 0, 950, 240], n4: [966, 0, 950, 240], n3: [0, 256, 950, 240], n2: [966, 256, 950, 240], n5: [0, 512, 1916, 160] })
  assert.strictEqual(r.layout.total_height, 672)
})
t('K-6 1920×600 全部最小高度', () => { const r = L(600); assert.deepStrictEqual(r.layout.dropped, []); assert.strictEqual(r.layout.compact, true); assert.strictEqual(r.layout.total_height, 416) })
t('K-6 1920×500（Codex L06 更正）不刪、最小高度', () => { const r = L(500); assert.deepStrictEqual(r.layout.dropped, []); assert.strictEqual(r.layout.compact, true); assert.strictEqual(r.layout.total_height, 416) })
t('K-6 1920×400 拿掉 n5', () => { const r = L(400); assert.deepStrictEqual(r.layout.dropped, ['n5']); assert.strictEqual(r.layout.total_height, 304) })
t('K-6 1920×200 拿掉 n5、n2、n3', () => assert.deepStrictEqual(L(200).layout.dropped, ['n5', 'n2', 'n3']))
t('K-6 1920×120 拒絕', () => assert.strictEqual(L(120).error, 'REQUIRED_OVERFLOW'))
t('K-6 找不到「刪減後回建議高度」的高度（記為現有目錄觸發不到）', () => {
  for (let h = 1; h <= 1100; ++h) { const r = L(h); if (r.ok && r.layout.dropped.length) assert.strictEqual(r.layout.compact, true, 'h=' + h) }
})
const bad = (mut, code) => () => { const { res, p } = k6(); mut(p); const v = Layout.validatePlan(p, res); assert.strictEqual(v.ok, false); assert.strictEqual(v.error, code) }
t('L01 兩個 W2', bad(p => { p.nodes[4].component_id = 'W2_SERIES'; p.nodes[4].binding_ref = Object.assign({}, p.nodes[1].binding_ref) }, 'DUPLICATE_COMPONENT'))
t('L02 自創編號', bad(p => { p.nodes[1].node_id = 'custom'; p.order[1] = 'custom' }, 'NODE_ID'))
t('L03 component_id = toString', bad(p => { p.nodes[1].component_id = 'toString' }, 'NOT_IN_CATALOG'))
t('L03 size_class = toString', bad(p => { p.nodes[1].size_class = 'toString' }, 'SIZE_CLASS'))
t('L04 嚴重告警表改成非必要、0 分', bad(p => { p.nodes[3].required = false; p.nodes[3].priority = 0 }, 'PLAN_TAMPERED'))
t('節點帶 x', bad(p => { p.nodes[1].x = 0 }, 'NODE_UNKNOWN_FIELD'))
t('binding 多一個鍵', bad(p => { p.nodes[1].binding_ref.extra = 1 }, 'BINDING_INVALID'))
t('趨勢圖綁到計數事實', bad(p => { p.nodes[1].binding_ref.ref = '1:F1' }, 'BINDING_INVALID'))
t('只有 request_id 的 binding', bad(p => { p.nodes[1].binding_ref = { request_id: 'r1' } }, 'BINDING_INVALID'))
t('別的請求的資料', bad(p => { p.nodes[1].binding_ref.request_id = 'r2' }, 'BINDING_FOREIGN'))
t('沒給資料就不驗', () => assert.strictEqual(Layout.validatePlan(k6().p).error, 'NO_DATA'))
t('同一輸入兩次結果相同', () => assert.deepStrictEqual(L(1080), L(1080)))

console.log(`pass ${pass} / fail ${fail}`)
process.exit(fail ? 1 : 0)
