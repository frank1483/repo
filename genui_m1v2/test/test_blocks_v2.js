// 五塊功能第 1、2、3 塊在 0.4 的新案例（v3.1c I1～I3、X1～X2、M1～M2），並沿用 test_blocks12.js、test_block3.js 的案例。預期值手算。
const fs = require('fs'), path = require('path')
function load(file, names) {
  const src = fs.readFileSync(path.join(__dirname, '../qml', file), 'utf8').replace(/^\.pragma library/m, '')
  return new Function(src + '\nreturn {' + names.join(',') + '}')()
}
const O = load('GenuiOverrun.js', ['init', 'step', 'slotPublish', 'slotConsume', 'OVERRUN_VERSION'])
const X = load('GenuiTxn.js', ['create', 'beginCommit', 'invalidate', 'finishCommit', 'TXN_VERSION'])
const M = load('GenuiLease.js', ['remount', 'acquire', 'release', 'switchOrder', 'LEASE_VERSION'])
let pass = 0, fail = 0
function ok(id, c, m) { if (c) pass++; else { fail++; console.log('FAIL', id, m || '') } }
const cfg = { q_gui: 4, order: ['n1', 'n2'], kinds: { n1: 'W1_FACT', n2: 'W2_SERIES' }, required_kinds: [] }
const F = (t, ms, x) => Object.assign({ t_ms: t, gui_ms: ms, active_kinds: ['W2_SERIES'], alert_pending: false, alert_shown: false }, x || {})
function run(frames) { let st = O.init(cfg), log = []; for (const f of frames) { const r = O.step(st, f); st = r.st; log.push({ s: st.state, a: r.actions }) } return { st, log } }
// I1a 擷取在預算內完成 → 不改固定文字
let r = run([F(0, 9), F(16, 0, { capture_done: true }), F(33, 0)])
ok('I1a', !r.log.some(x => x.a.includes('CAPTURE_ABORT_SHOW_TEXT')))
// I1b 擷取超過 1 格沒完成 → 第 2 個凍結格改顯示固定文字（只發一次）
r = run([F(0, 9), F(16, 0), F(33, 0), F(50, 0)])
ok('I1b', r.log[2].a.includes('CAPTURE_ABORT_SHOW_TEXT') && r.log.filter(x => x.a.includes('CAPTURE_ABORT_SHOW_TEXT')).length === 1, JSON.stringify(r.log))
// I2 恢復途中有告警：恢復暫停、索引保留；告警顯示的那一格就從下一個元件接著恢復（step 先清告警暫停再走狀態）
r = run([F(0, 9), F(5000, 0, { capture_done: true }), F(5016, 0), F(5033, 0, { alert_pending: true }), F(5050, 0, { alert_shown: true }), F(5066, 0)])
ok('I2', r.log[2].a.includes('RESTORE:n1') && !r.log[3].a.some(a => a.startsWith('RESTORE')) && r.log[3].a.includes('SHOW_ALERT')
   && r.log[4].a.includes('RESTORE:n2'), JSON.stringify(r.log.map(x => x.a)))
// I3 值槽：消費端清旗標後、讀值前生產端寫 v2 → 最後拿到 v2；讀完 v1 後才寫 v2 → 不需要第三次寫入也拿到 v2
let slot = { value: 'v1', flag: true }, seen = []
O.slotConsume(slot, v => { seen.push(v); if (v === 'v1' && seen.length === 1) O.slotPublish(slot, 'v2') })
ok('I3a', seen.join() === 'v1,v2' && slot.flag === false, seen)
slot = { value: 'v1', flag: true }; seen = []
O.slotConsume(slot, v => seen.push(v)); O.slotPublish(slot, 'v2'); O.slotConsume(slot, v => seen.push(v))
ok('I3b', seen.join() === 'v1,v2')
// X1 提交中又失效，寫入結果三種
let a = X.create('tx', 'p0', 'p1', 'h'); X.beginCommit(a); X.invalidate(a, 'safety')
ok('X1ok', X.finishCommit(a, 'ok', () => true) === 'SWITCHED')
a = X.create('tx', 'p0', 'p1', 'h'); X.beginCommit(a); X.invalidate(a, 'safety')
ok('X1failed', X.finishCommit(a, 'failed', () => true) === 'ROLLED_BACK')
a = X.create('tx', 'p0', 'p1', 'h'); X.beginCommit(a); X.invalidate(a, 'safety')
ok('X1uncertain', X.finishCommit(a, 'uncertain', () => true) === 'UNCERTAIN' && a.log.some(l => l.note === 'write_uncertain_readback_on_startup'))
// X2 意圖沒落盤就不寫指標；切換當下重新核對失敗 → 回滾
a = X.create('tx', 'p0', 'p1', 'h')
ok('X2a', X.beginCommit(a, () => false) === false && a.state === 'ROLLED_BACK')
a = X.create('tx', 'p0', 'p1', 'h'); X.beginCommit(a, () => true)
ok('X2b', X.finishCommit(a, 'ok', null, () => false) === 'ROLLED_BACK')
// M1 切換順序：先發布新世代、再換資料或安全畫面、最後卸載舊畫面並釋放
ok('M1', M.switchOrder().join() === 'PUBLISH_NEW_GEN,SWAP_OR_SAFE_SCREEN,UNMOUNT_OLD_AND_RELEASE')
const refs = {}; M.acquire(refs, 'req1', 3); M.acquire(refs, 'w5', 3); M.release(refs, 'req1')
ok('M1b', JSON.stringify(refs) === '{"w5":3}')
// M2 同一版面但新世代 binding 沒驗過（或 W5 片段不在）→ 安全畫面
ok('M2a', M.remount(true, true).join() === 'SWAP_DATA')
ok('M2b', M.remount(true, false).join() === 'SAFE_SCREEN,RECOVERY_PROPOSAL' && M.remount(true).join() === 'SAFE_SCREEN,RECOVERY_PROPOSAL')
console.log(O.OVERRUN_VERSION, X.TXN_VERSION, M.LEASE_VERSION, 'pass', pass, 'fail', fail)
process.exit(fail ? 1 : 0)
