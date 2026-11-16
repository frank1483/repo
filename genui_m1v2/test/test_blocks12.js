// 五塊功能第 1（超支）、2（提交點）塊的固定案例。預期值為手算。
const fs = require('fs'), path = require('path')
function load(file, names) {
  const src = fs.readFileSync(path.join(__dirname, '../qml', file), 'utf8').replace(/^\.pragma library/m, '')
  return new Function(src + '\nreturn {' + names.join(',') + '}')()
}
const O = load('GenuiOverrun.js', ['init', 'step', 'S', 'P', 'OVERRUN_VERSION'])
const X = load('GenuiTxn.js', ['create', 'apply', 'beginCommit', 'invalidate', 'finishCommit', 'T', 'TXN_VERSION'])
let pass = 0, fail = 0
function ok(id, cond, msg) { if (cond) pass++; else { fail++; console.log('FAIL', id, msg || '') } }
const cfg = { q_gui: 4, order: ['n1', 'n2'], kinds: { n1: 'W1_FACT', n2: 'W2_SERIES' }, required_kinds: [] }
function run(frames, c) { let st = O.init(c || cfg), log = []; for (const f of frames) { const r = O.step(st, f); st = r.st; log.push({ s: st.state, a: r.actions }) } return { st, log } }
const F = (t, ms, k, ap, as) => ({ t_ms: t, gui_ms: ms, active_kinds: k || ['W2_SERIES'], alert_pending: !!ap, alert_shown: !!as })

// O1 連續 2 格超支不凍結，第 3 格凍結
let r = run([F(0, 5), F(16, 5), F(33, 5)])
ok('O1a', r.log[1].s === 'NORMAL'); ok('O1b', r.log[2].s === 'FROZEN' && r.log[2].a.includes('CAPTURE_AND_HIDE'))
// O2 單格 > 2q（8.1 > 8）立即凍結；剛好 8 不凍結
ok('O2a', run([F(0, 8.1)]).log[0].s === 'FROZEN'); ok('O2b', run([F(0, 8)]).log[0].s === 'NORMAL')
// O3 中間一格不超支會重算
ok('O3', run([F(0, 5), F(16, 5), F(33, 3), F(50, 5)]).log[3].s === 'NORMAL')
// O4 凍結未滿 5 秒不恢復；滿 5 秒恢復，之後每格恢復一個，最後進入觀察期
r = run([F(0, 9), F(4999, 0), F(5000, 0), F(5016, 0), F(5033, 0)])
ok('O4a', r.log[1].s === 'FROZEN'); ok('O4b', r.log[2].s === 'RESTORING')
ok('O4c', r.log[3].a.includes('RESTORE:n1') && r.log[4].a.includes('RESTORE:n2') && r.log[4].s === 'PROBATION')
// O5 滿 5 秒但有告警等待 → 不恢復；告警顯示後才恢復
r = run([F(0, 9), F(5000, 0, null, true), F(5100, 0, null, false, true), F(5116, 0)])
ok('O5a', r.log[1].s === 'FROZEN' && r.log[1].a.includes('SHOW_ALERT')); ok('O5b', r.log[3].s === 'RESTORING', r.log.map(x => x.s))
// O6 觀察期 30 秒內又超支 → 停用記下的種類並重新凍結、要求重排
r = run([F(0, 9, ['W2_SERIES']), F(5000, 0), F(5016, 0), F(5033, 0), F(6000, 9, ['W2_SERIES'])])
ok('O6', r.log[4].s === 'FROZEN' && r.log[4].a.includes('DISABLE_KINDS:W2_SERIES') && r.log[4].a.includes('REPLAN_WITHOUT_DISABLED'), JSON.stringify(r.log[4]))
// O7 停用種類含答案區 → 整個工作區停用
r = run([F(0, 9, ['W1_FACT']), F(5000, 0), F(5016, 0), F(5033, 0), F(6000, 9, ['W1_FACT'])])
ok('O7', r.log[4].s === 'WORKSPACE_OFF' && r.log[4].a.includes('ANSWER_TO_SKELETON_TEXT'))
// O8 停用種類含必要元件 → 整個工作區停用
r = run([F(0, 9, ['W4_DIAG']), F(5000, 0), F(5016, 0), F(5033, 0), F(6000, 9, ['W4_DIAG'])], Object.assign({}, cfg, { required_kinds: ['W4_DIAG'] }))
ok('O8', r.log[4].s === 'WORKSPACE_OFF')
// O9 觀察期滿 30 秒 → 回到 NORMAL
r = run([F(0, 9), F(5000, 0), F(5016, 0), F(5033, 0), F(35033, 0)])
ok('O9', r.log[4].s === 'NORMAL')
// O10 凍結中骨架以外仍連續 3 格超支 → 規則安全畫面（唯一銷毀工作區）
r = run([F(0, 9), F(16, 5), F(33, 5), F(50, 5)])
ok('O10', r.log[3].s === 'SAFE_RULES' && r.log[3].a.includes('DESTROY_WORKSPACE'))
// O11 同上但有告警等待 → 等告警顯示完才進安全畫面
r = run([F(0, 9), F(16, 5), F(33, 5), F(50, 5, null, true), F(66, 0, null, false, true), F(83, 0)])
ok('O11a', r.log[3].s === 'FROZEN'); ok('O11b', r.log[5].s === 'SAFE_RULES', r.log.map(x => x.s))
// O12 記下的種類可不只一種
r = run([F(0, 5, ['W2_SERIES']), F(16, 5, ['W3_TABLE']), F(33, 5, ['W2_SERIES'])])
ok('O12', r.st.recorded.length === 2 && r.st.recorded.includes('W3_TABLE'))

// X1 按鈕帶舊編號 → 忽略
let a = X.create('tx', 'p0', 'p1', 'h'), b = X.create('tx', 'p0', 'p2', 'h')
ok('X1', X.apply(b, a.id).result === 'IGNORED' && X.apply(b, b.id).ok)
// X2 I/O 先改到 → GUI 失效延後，重新驗證合格就切換
a = X.create('tx', 'p0', 'p1', 'h')
ok('X2a', X.beginCommit(a) && X.invalidate(a, 'resize') === 'DEFERRED'); ok('X2b', X.finishCommit(a, true, () => true) === 'SWITCHED')
// X3 同上但重新驗證不合格 → 回滾
a = X.create('tx', 'p0', 'p1', 'h'); X.beginCommit(a); X.invalidate(a, 'resize')
ok('X3', X.finishCommit(a, true, () => false) === 'ROLLED_BACK')
// X4 GUI 先改到 → I/O 停手，不寫指標
a = X.create('tx', 'p0', 'p1', 'h')
ok('X4', X.invalidate(a, 'safety') === 'INVALIDATED' && X.beginCommit(a) === false && a.state === 'INVALIDATED')
// X5 寫入失敗 → 回滾；意圖紀錄有交易編號、新舊指標、快照雜湊
a = X.create('tx', 'p0', 'p1', 'hh'); X.beginCommit(a)
ok('X5', X.finishCommit(a, false, () => true) === 'ROLLED_BACK' && a.log.every(l => l.txn_id === a.id && l.old_ptr === 'p0' && l.new_ptr === 'p1' && l.snapshot_hash === 'hh'))
// X6 沒有提交中失效 → 不呼叫重新驗證
a = X.create('tx', 'p0', 'p1', 'h'); X.beginCommit(a); let called = false
ok('X6', X.finishCommit(a, true, () => { called = true; return false }) === 'SWITCHED' && !called)
console.log(O.OVERRUN_VERSION, X.TXN_VERSION, 'pass', pass, 'fail', fail)
process.exit(fail ? 1 : 0)
