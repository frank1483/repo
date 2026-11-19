// 轉場狀態機單元測試（轉場說明 v1 §4 第 1 步）
const fs = require('fs'), path = require('path')
const src = fs.readFileSync(path.join(__dirname, '../qml/GenuiTransition.js'), 'utf8').replace(/^\.pragma library/m, '')
const X = new Function(src + '\nreturn { init, onTxn, tick, onCritical, onOverrun, onEffectError, S, P, TRANS_VERSION }')()
let pass = 0, fail = 0; const log = []
function ok(n, c, i) { if (c) pass++; else { fail++; log.push('FAIL ' + n + (i !== undefined ? ' :: ' + JSON.stringify(i) : '')) } }
const N = { overrun_state: 'NORMAL', reduced_motion: false, effect_ok: true }
// 正常流程：每 16 ms 一格
let r = X.onTxn(X.init(), 'SWITCHED', 0, N), st = r.st, swaps = 0, unlock = -1, maxBlur = 0, blurs = []
ok('start actions', r.actions.join() === 'start,apply_lock', r.actions)
for (let t = 16; t <= 400; t += 16) { const k = X.tick(st, t); st = k.st; blurs.push(k.blur); maxBlur = Math.max(maxBlur, k.blur); if (k.actions.includes('swap')) swaps++; if (k.actions.includes('apply_unlock')) unlock = t }
ok('one swap', swaps === 1, swaps)
ok('peak blur 1', maxBlur === 1)
ok('ends idle', st.state === 'IDLE' && blurs[blurs.length - 1] === 0)
ok('total ~300ms', unlock >= 300 && unlock <= 320, unlock)
ok('blur in monotonic', (() => { const i = blurs.indexOf(1); for (let j = 1; j <= i; ++j) if (blurs[j] < blurs[j - 1]) return false; return true })())
ok('blur out monotonic', (() => { const i = blurs.indexOf(1); for (let j = i + 1; j < blurs.length; ++j) if (blurs[j] > blurs[j - 1]) return false; return true })())
ok('blur in range', blurs.every(b => b >= 0 && b <= 1))
// 非 SWITCHED 不觸發
for (const res of ['ROLLED_BACK', 'INVALIDATED', 'IGNORED', 'UNCERTAIN']) { const q = X.onTxn(X.init(), res, 0, N); ok('no trigger ' + res, q.actions.length === 0 && q.st.state === 'IDLE') }
// 略過條件
const skipCases = [[{ ...N, overrun_state: 'FROZEN' }, 'overrun_FROZEN'], [{ ...N, reduced_motion: true }, 'reduced_motion'], [{ ...N, effect_ok: false }, 'effect_unavailable']]
for (const [c, why] of skipCases) { const q = X.onTxn(X.init(), 'SWITCHED', 5, c); ok('skip ' + why, q.actions.join() === 'swap_now' && q.st.state === 'IDLE' && q.st.log[0].why === why, q) }
// critical 中斷：BLUR_IN 中（還沒換）→ 先換再清楚
let a = X.onTxn(X.init(), 'SWITCHED', 0, N).st; a = X.tick(a, 50).st
let c = X.onCritical(a, 60)
ok('critical before swap swaps', c.actions.join() === 'swap,apply_unlock' && c.st.state === 'IDLE' && c.blur === 0, c)
// critical 在 BLUR_OUT（已換）→ 不再換
let b = X.onTxn(X.init(), 'SWITCHED', 0, N).st; b = X.tick(b, 130).st; b = X.tick(b, 150).st
const c2 = X.onCritical(b, 160)
ok('critical after swap no 2nd swap', c2.actions.join() === 'apply_unlock', c2.actions)
ok('critical idle noop', X.onCritical(X.init(), 0).actions.length === 0)
// 超支：停用，之後的 SWITCHED 直接換
let o = X.onTxn(X.init(), 'SWITCHED', 0, N).st; o = X.tick(o, 50).st
const ov = X.onOverrun(o, 60)
ok('overrun disables', ov.st.disabled && ov.actions.join() === 'swap,apply_unlock' && ov.st.log.some(l => l.ev === 'abort_overrun'), ov.st.log)
const after = X.onTxn(ov.st, 'SWITCHED', 1000, N)
ok('after disable swap_now', after.actions.join() === 'swap_now' && after.st.log[after.st.log.length - 1].why === 'disabled')
// 效果錯誤
let e = X.onTxn(X.init(), 'SWITCHED', 0, N).st; e = X.tick(e, 20).st
const ee = X.onEffectError(e, 30)
ok('effect error swaps', ee.actions.join() === 'swap,apply_unlock' && ee.st.log.some(l => l.ev === 'abort_effect_error') && !ee.st.disabled)
// 純函式：不改輸入
const s0 = X.init(), s0j = JSON.stringify(s0); X.onTxn(s0, 'SWITCHED', 0, N); ok('pure', JSON.stringify(s0) === s0j)
// 大跳格（一次跳過整段）仍只換一次並結束
let j = X.onTxn(X.init(), 'SWITCHED', 0, N).st, jsw = 0
for (const t of [500, 1000]) { const k = X.tick(j, t); j = k.st; if (k.actions.includes('swap')) jsw++ }
ok('big jumps one swap', jsw === 1 && j.state === 'IDLE', j)
console.log(log.join('\n')); console.log(`test_trans_v1 (${X.TRANS_VERSION}): pass ${pass} fail ${fail}`); process.exit(fail ? 1 : 0)
