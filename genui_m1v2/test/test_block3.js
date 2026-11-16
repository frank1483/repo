// 第 3 塊模型更新租約固定案例，預期值手算。
const fs = require('fs'), path = require('path')
const src = fs.readFileSync(path.join(__dirname, '../qml/GenuiLease.js'), 'utf8').replace(/^\.pragma library/m, '')
const M = new Function(src + '\nreturn {init,admit,flag,beginUpdate,tick,onResult,remount,startup,LEASE_VERSION}')()
let pass = 0, fail = 0
function ok(id, c, m) { if (c) pass++; else { fail++; console.log('FAIL', id, m || '') } }
const files = [{ name: 'gemma.litertlm', sha: 'aa' }, { name: 'embed.litertlm', sha: 'bb' }]
const allow = { 'gemma.litertlm': ['aa'], 'embed.litertlm': ['bb', 'b0'] }
const all3 = (st, id) => ['result_routed', 'stop_evidence', 'slot_returned'].forEach(n => M.flag(st, id, n))
// M1 排水中新請求走規則版並標「規則」
let st = M.init(3, { drain_timeout_ms: 10000 }); M.admit(st, 'r1'); M.beginUpdate(st, 0)
let a = M.admit(st, 'r2'); ok('M1', a.path === 'rules' && a.label === '規則')
// M2 三旗標未齊（少停止證據）→ 等；齊了 → 發布世代 4，先發布再寫指標
M.flag(st, 'r1', 'result_routed'); M.flag(st, 'r1', 'slot_returned')
ok('M2a', M.tick(st, 100, files, allow, true).action === 'WAIT')
M.flag(st, 'r1', 'stop_evidence'); let t = M.tick(st, 200, files, allow, true)
ok('M2b', t.action === 'PUBLISH_THEN_WRITE_POINTER' && t.gen === 4 && st.state === 'SERVING')
// M3 舊世代結果 → late_discard；新世代 → show
ok('M3', M.onResult(st, 3) === 'late_discard' && M.onResult(st, 4) === 'show')
// M4 等太久 → 放棄，世代不變，恢復准入
st = M.init(3, { drain_timeout_ms: 10000 }); M.admit(st, 'r1'); M.beginUpdate(st, 0)
t = M.tick(st, 10000, files, allow, true); ok('M4', t.action === 'ABORT' && t.reason === 'drain_timeout' && st.gen === 3 && M.admit(st, 'r3').path === 'model')
// M5 雜湊不在允許清單 → 放棄；版本對不上 → 放棄
st = M.init(3, { drain_timeout_ms: 10000 }); M.beginUpdate(st, 0)
t = M.tick(st, 1, [{ name: 'gemma.litertlm', sha: 'zz' }], allow, true); ok('M5a', t.action === 'ABORT' && st.gen === 3)
M.beginUpdate(st, 2); t = M.tick(st, 3, files, allow, false); ok('M5b', t.reason === 'version_mismatch' && st.gen === 3)
// M6 沒有使用中工作 → 直接驗證發布
st = M.init(0, { drain_timeout_ms: 10000 }); M.beginUpdate(st, 0); ok('M6', M.tick(st, 0, files, allow, true).gen === 1)
// M7 排水中不能再開第二次更新
st = M.init(0, { drain_timeout_ms: 10000 }); M.beginUpdate(st, 0); ok('M7', M.beginUpdate(st, 1) === false)
// M8 舊元件重排
ok('M8', M.remount(true)[0] === 'SWAP_DATA' && M.remount(false).join() === 'SAFE_SCREEN,RECOVERY_PROPOSAL')
// M9 啟動讀回
ok('M9a', M.startup(false, () => false, () => true) === 'PREVIOUS'); ok('M9b', M.startup(false, () => false, () => false) === 'RULES_ONLY')
ok('M9c', M.startup(false, () => true, () => false) === 'CURRENT')
console.log(M.LEASE_VERSION, 'pass', pass, 'fail', fail); process.exit(fail ? 1 : 0)
