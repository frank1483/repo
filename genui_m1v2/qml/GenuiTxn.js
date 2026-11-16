.pragma library
// 「套用」提交點（附件 §E、v3.1b §E'；M1 演算法說明 v3 補充第 2 節，使用者 11/16 13:58「五塊照說明」）。
// 純邏輯：狀態只存在 txn.state 一處；cas() 代表在同一把 QMutex 內的比較並交換，宿主負責上鎖。
var TXN_VERSION = "txn-m1-0.1"
var T = { PREPARING: "PREPARING", COMMITTING: "COMMITTING", INVALIDATED: "INVALIDATED",
          SWITCHED: "SWITCHED", ROLLED_BACK: "ROLLED_BACK", IGNORED: "IGNORED" }
var seq = 0
function create(prefix, oldPtr, newPtr, snapshotHash) {
  seq++
  return { id: prefix + "-" + seq, state: T.PREPARING, old_ptr: oldPtr, new_ptr: newPtr,
           snapshot_hash: snapshotHash, late_invalidate: false, log: [] }
}
function cas(txn, from, to) { if (txn.state !== from) return false; txn.state = to; return true }
function intent(txn, note) {
  var r = { txn_id: txn.id, old_ptr: txn.old_ptr, new_ptr: txn.new_ptr, snapshot_hash: txn.snapshot_hash, state: txn.state, note: note }
  txn.log.push(r); return r
}
// 按「套用」：按鈕帶的編號要和目前待確認提案一致
function apply(pending, buttonTxnId) {
  if (!pending || pending.id !== buttonTxnId) return { ok: false, result: T.IGNORED }
  return { ok: true }
}
// I/O 執行緒：寫指標前
function beginCommit(txn) { var ok = cas(txn, T.PREPARING, T.COMMITTING); intent(txn, ok ? "begin_commit" : "commit_refused"); return ok }
// GUI 執行緒：視窗大小改變或安全事件
function invalidate(txn, reason) {
  if (cas(txn, T.PREPARING, T.INVALIDATED)) { intent(txn, "invalidated:" + reason); return "INVALIDATED" }
  if (txn.state === T.COMMITTING) { txn.late_invalidate = true; intent(txn, "late_invalidate:" + reason); return "DEFERRED" }
  return "NOOP"
}
// 指標寫完之後：若提交中又失效，用新視窗大小重新驗證（revalidate 由呼叫端提供，回傳 bool）
function finishCommit(txn, writeOk, revalidate) {
  if (txn.state !== T.COMMITTING) return txn.state
  if (!writeOk) { txn.state = T.ROLLED_BACK; intent(txn, "write_failed"); return txn.state }
  if (txn.late_invalidate && !revalidate()) { txn.state = T.ROLLED_BACK; intent(txn, "revalidate_failed"); return txn.state }
  txn.state = T.SWITCHED; intent(txn, txn.late_invalidate ? "revalidated" : "committed"); return txn.state
}
