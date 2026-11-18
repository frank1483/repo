.pragma library
// 「套用」提交點（附件 §E、v3.1b §E'；M1 演算法說明 v3 補充第 2 節，使用者 11/16 13:58「五塊照說明」）。
// 純邏輯：狀態只存在 txn.state 一處；cas() 代表在同一把 QMutex 內的比較並交換，宿主負責上鎖。
var TXN_VERSION = "txn-m1-0.2"
var T = { PREPARING: "PREPARING", COMMITTING: "COMMITTING", INVALIDATED: "INVALIDATED",
          SWITCHED: "SWITCHED", ROLLED_BACK: "ROLLED_BACK", IGNORED: "IGNORED", UNCERTAIN: "UNCERTAIN" }
// 0.2（v3.1c X1～X2）：寫入結果三種（ok／failed／uncertain）；commit_intent 要先落盤（persistIntent 回 true）才寫指標；
//   GUI 真正切換時（序列化點）用 recheck() 重新核對最新的告警與必要元件條件。
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
function beginCommit(txn, persistIntent) {
  var ok = cas(txn, T.PREPARING, T.COMMITTING); var rec = intent(txn, ok ? "begin_commit" : "commit_refused")
  if (!ok) return false
  if (persistIntent && !persistIntent(rec)) { txn.state = T.ROLLED_BACK; intent(txn, "intent_not_persisted"); return false }   // 意圖沒落盤就不寫指標
  return true
}
// GUI 執行緒：視窗大小改變或安全事件
function invalidate(txn, reason) {
  if (cas(txn, T.PREPARING, T.INVALIDATED)) { intent(txn, "invalidated:" + reason); return "INVALIDATED" }
  if (txn.state === T.COMMITTING) { txn.late_invalidate = true; intent(txn, "late_invalidate:" + reason); return "DEFERRED" }
  return "NOOP"
}
// 指標寫完之後：writeResult 是 "ok"／"failed"／"uncertain"（舊版傳 true/false 也接受）。
// revalidate：提交中又失效時，用新視窗大小重新驗證；recheck：切換當下重新核對告警與必要元件。兩者都回 bool，可省略。
function finishCommit(txn, writeResult, revalidate, recheck) {
  if (txn.state !== T.COMMITTING) return txn.state
  var w = writeResult === true ? "ok" : (writeResult === false ? "failed" : writeResult)
  if (w === "failed") { txn.state = T.ROLLED_BACK; intent(txn, "write_failed"); return txn.state }
  if (w === "uncertain") { txn.state = T.UNCERTAIN; intent(txn, "write_uncertain_readback_on_startup"); return txn.state }
  if (txn.late_invalidate && revalidate && !revalidate()) { txn.state = T.ROLLED_BACK; intent(txn, "revalidate_failed"); return txn.state }
  if (recheck && !recheck()) { txn.state = T.ROLLED_BACK; intent(txn, "recheck_failed"); return txn.state }
  txn.state = T.SWITCHED; intent(txn, txn.late_invalidate ? "revalidated" : "committed"); return txn.state
}
