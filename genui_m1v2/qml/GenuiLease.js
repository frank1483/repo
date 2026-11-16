.pragma library
// 模型檔更新租約（附件 §M、v3.1b §M'；M1 演算法說明 v3 補充第 3 節，使用者 11/16 13:58「五塊照說明」）。
// 純邏輯；複製檔案、算雜湊、寫指標由宿主做。drain_timeout_ms 為候選值〔待凍結〕。
var LEASE_VERSION = "lease-m1-0.1"
var L = { SERVING: "SERVING", DRAINING: "DRAINING" }
function init(gen, cfg) { return { gen: gen, state: L.SERVING, inflight: {}, drainStart: -1, timeout: cfg.drain_timeout_ms, log: [] } }
// 准入：排水中新的模型／向量／GenUI 請求改走規則版
function admit(st, reqId) {
  if (st.state === L.DRAINING) return { path: "rules", label: "規則" }
  st.inflight[reqId] = { gen: st.gen, result_routed: false, stop_evidence: false, slot_returned: false }
  return { path: "model", gen: st.gen }
}
function flag(st, reqId, name) { if (st.inflight[reqId]) st.inflight[reqId][name] = true }
function settled(r) { return r.result_routed && r.stop_evidence && r.slot_returned }
function drained(st) { for (var k in st.inflight) if (Object.prototype.hasOwnProperty.call(st.inflight, k) && !settled(st.inflight[k])) return false; return true }
// 新檔複製完、雜湊驗證通過
function beginUpdate(st, now) { if (st.state !== L.SERVING) return false; st.state = L.DRAINING; st.drainStart = now; st.log.push("begin"); return true }
// 每次輪詢：files=[{name, sha}]，allow={name: [sha...]}，versionsMatch：版本彼此對得上
function tick(st, now, files, allow, versionsMatch) {
  if (st.state !== L.DRAINING) return { action: "NONE" }
  for (var k in st.inflight) if (Object.prototype.hasOwnProperty.call(st.inflight, k) && settled(st.inflight[k])) delete st.inflight[k]
  if (!drained(st)) {
    if (now - st.drainStart >= st.timeout) { st.state = L.SERVING; st.log.push("abort_timeout"); return { action: "ABORT", reason: "drain_timeout", gen: st.gen } }
    return { action: "WAIT" }
  }
  for (var i = 0; i < files.length; i++) {
    var a = allow[files[i].name]
    if (!a || a.indexOf(files[i].sha) < 0) { st.state = L.SERVING; st.log.push("abort_hash"); return { action: "ABORT", reason: "hash_not_allowed:" + files[i].name, gen: st.gen } }
  }
  if (!versionsMatch) { st.state = L.SERVING; st.log.push("abort_version"); return { action: "ABORT", reason: "version_mismatch", gen: st.gen } }
  st.gen += 1; st.state = L.SERVING; st.log.push("publish:" + st.gen)
  return { action: "PUBLISH_THEN_WRITE_POINTER", gen: st.gen }   // 先在 GUI 執行緒發布世代，再寫指標
}
// GUI 執行緒要把結果放上畫面時，當下比對世代
function onResult(st, reqGen) { if (reqGen !== st.gen) { st.log.push("late_discard"); return "late_discard" } return "show" }
// 已掛在畫面上的舊元件：重排後是否同一版面
function remount(sameLayout) { return sameLayout ? ["SWAP_DATA"] : ["SAFE_SCREEN", "RECOVERY_PROPOSAL"] }
// 啟動：指標寫入結果不確定時先讀回驗證
function startup(pointerCertain, verifyCurrent, verifyPrevious) {
  if (pointerCertain) return "CURRENT"
  if (verifyCurrent()) return "CURRENT"
  if (verifyPrevious()) return "PREVIOUS"
  return "RULES_ONLY"
}
