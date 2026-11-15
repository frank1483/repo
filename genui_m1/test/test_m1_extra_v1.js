// 追加固定案例 v1：預期值一律由契約條文推導（註明節次），不是照程式輸出抄的。
// 來源：Codex 第一次補核（沒讀到材料）列出的待驗證方向 C-01～C-05、C-09，以及 Gate 校準基準線看到的現象。
// 執行：node genui_m1/test/test_m1_extra_v1.js
const assert = require('assert')
const { Gate, Tools } = require('./load.js')
let pass = 0, fail = 0
function t(name, basis, fn) { try { fn(); pass++; console.log('PASS ' + name) } catch (e) { fail++; console.log('FAIL ' + name + '\n  依據：' + basis + '\n  ' + String(e.message).split('\n').join('\n  ')) } }
const cls = s => Gate.gate(s)['class']
const ramp = (n, dt, slope, soc0 = 80) => Array.from({ length: n }, (_, i) => ({ t: i * dt, soc: soc0 + slope * (i * dt) / 60 }))

// C-02 切句：詞內的「後、並、再」不該改變結果
t('後備電池的電量是多少？', 'v3-1 §A-2 第 5、8～10 條：有領域詞（電池、電量），沒有飛控動詞，QA 得 2 分', () => assert.strictEqual(cls('後備電池的電量是多少？'), 'QA'))
t('並聯電池的電壓是多少？', '同上（電池、電壓）', () => assert.strictEqual(cls('並聯電池的電壓是多少？'), 'QA'))
t('再生能源的定義是什麼？', 'v3-1 §A-2 第 6 條：沒有任何領域證據', () => assert.strictEqual(cls('再生能源的定義是什麼？'), 'OUT_OF_DOMAIN'))
t('最後一次告警是什麼', 'v3-1 §A-2 第 8、10 條：告警 2 分', () => assert.strictEqual(cls('最後一次告警是什麼'), 'ALERT_Q'))
// 切句造成的保守誤擋：依條文字面，「返航」「後」切開後，前一個子句是沒有問句標記的飛控動詞
t('返航後電量會剩多少（依條文字面）', 'v3-1 §A-2b 用「後」切句＋第 4 條：子句「返航」不是問句 → FLIGHT_CMD。語意上這是問句，屬於條文造成的誤擋，另記為發現', () => assert.strictEqual(cls('返航後電量會剩多少'), 'FLIGHT_CMD'))
t('降落之後告訴我電量', 'v3-1 §A-3 混合句：任一子句是飛控命令句', () => assert.strictEqual(cls('降落之後告訴我電量'), 'FLIGHT_CMD'))
// C-01 單類弱證據：依條文字面是 CLARIFY，且第二個候選是 0 分的類別
t('高度多少（依條文字面）', 'v3-1 §A-2 第 10、11 條：QA 1 分 < T=2 → CLARIFY，列分數最高的 2 類', () => { const g = Gate.gate('高度多少'); assert.strictEqual(g['class'], 'CLARIFY'); assert.strictEqual(g.clarify.length, 2) })
// C-03、C-04 剩餘時間
t('C-03 ETA 算術', 'v1 §C-2 第 5、7 步：斜率 −1 %/分、最新 79%、保留 20% → 59 分鐘', () => { const r = Tools.energyTrend(ramp(61, 1, -1), { reservePct: 20 }); assert(Math.abs(r.detail.slope_pct_per_min + 1) < 1e-9); assert(Math.abs(r.detail.eta_min - 59) < 1e-6) })
t('C-04 已達保留值', 'v1 §C-2 第 7 步：目前電量 > 保留值才算 ETA；等於時不算，也不得為負', () => { const r = Tools.energyTrend(ramp(61, 1, -1), { reservePct: 79 }); assert.strictEqual(r.status, 'OK'); assert.strictEqual(r.detail.eta_min, null); assert.strictEqual(r.detail.reserve_invalid, false) })
// C-05 保留值上界
t('C-05 保留值 = 100', 'v3-1 §C 新增邊界原文：「不是有限數字或不在 0～100 時…記 reserve_invalid」。100 在 0～100 之內，所以不該標無效', () => { const r = Tools.energyTrend(ramp(61, 1, -1), { reservePct: 100 }); assert.strictEqual(r.detail.reserve_invalid, false); assert.strictEqual(r.detail.eta_min, null) })
t('保留值 = 0', '同上：0 在範圍內', () => { const r = Tools.energyTrend(ramp(61, 1, -1), { reservePct: 0 }); assert.strictEqual(r.detail.reserve_invalid, false); assert(Math.abs(r.detail.eta_min - 79) < 1e-6) })
// C-09 多重不合格的先後
t('C-09 同時過期且樣本不足', 'v1 §C-3 狀態表把 STALE 與 INSUFFICIENT 並列，條文沒有寫先後。本案只記錄現況：程式先判過期', () => { const r = Tools.energyTrend(ramp(5, 1, -1), { reservePct: 20, now: 10, checkStale: true }); assert.strictEqual(r.status, 'STALE') })
console.log('pass ' + pass + ' / fail ' + fail)
process.exit(fail ? 1 : 0)
