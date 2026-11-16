.pragma library
// 畫面超支狀態機（附件 §I、v3.1b §I'；M1 演算法說明 v3 補充第 1 節，使用者 11/16 13:58「五塊照說明」）。
// 純邏輯：輸入每一格的量測，輸出新狀態與動作清單。真正擷取（grabToImage）、設不可見由宿主照動作執行。
// 數值 q_gui 為候選值〔待凍結〕，由呼叫端傳入。
var OVERRUN_VERSION = "overrun-m1-0.1"
var S = { NORMAL: "NORMAL", FROZEN: "FROZEN", RESTORING: "RESTORING", PROBATION: "PROBATION",
          SAFE_RULES: "SAFE_RULES", WORKSPACE_OFF: "WORKSPACE_OFF" }
var P = { CONSEC: 3, SPIKE_X: 2, FREEZE_MIN_MS: 5000, PROBATION_MS: 30000, ANSWER_KIND: "W1_FACT" }

function init(cfg) {
  // cfg: { q_gui, order: [元件 id，依排版順序], kinds: {id: kind}, required_kinds: [kind] }
  return { state: S.NORMAL, q: cfg.q_gui, order: cfg.order.slice(), kinds: cfg.kinds,
           required: cfg.required_kinds.slice(), consec: 0, consecKinds: [], recorded: [],
           frozenAt: -1, skelConsec: 0, pendingSafe: false, restoreIdx: 0, probationAt: -1,
           disabled: [], alertHold: false }
}
function union(a, b) { var o = a.slice(); for (var i = 0; i < b.length; i++) if (o.indexOf(b[i]) < 0) o.push(b[i]); return o }
function copy(st) { var o = {}; for (var k in st) if (Object.prototype.hasOwnProperty.call(st, k)) o[k] = Array.isArray(st[k]) ? st[k].slice() : st[k]; return o }

// 這一格是否觸發超支：連續 3 格 > q，或單格 > 2q。回傳 [觸發, 新連續數, 累積種類]
function overrunCheck(st, ms, kinds) {
  var over = ms > st.q
  var c = over ? st.consec + 1 : 0
  var ck = over ? union(st.consecKinds, kinds) : []
  var hit = (c >= P.CONSEC) || (ms > P.SPIKE_X * st.q)
  if (hit && !over) ck = union(ck, kinds)
  return [hit, c, hit ? union(ck, kinds) : ck]
}

// f: { t_ms, gui_ms（非骨架工作毫秒）, active_kinds: [kind], alert_pending: bool, alert_shown: bool }
function step(st0, f) {
  var st = copy(st0), acts = []
  // 告警插隊：有告警等待時先顯示告警，狀態轉移暫停（計時照走）；告警出現在畫面上之後回到原狀態。
  if (f.alert_pending && !f.alert_shown) { if (!st.alertHold) acts.push("SHOW_ALERT"); st.alertHold = true }
  if (f.alert_shown) st.alertHold = false
  var r = overrunCheck(st, f.gui_ms, f.active_kinds)
  st.consec = r[1]; st.consecKinds = r[2]
  switch (st.state) {
  case S.NORMAL:
    // 實作選擇：凍結不會擋告警，所以 NORMAL 觸發超支時即使有告警等待也立刻凍結
    if (r[0]) {
      st.state = S.FROZEN; st.frozenAt = f.t_ms; st.recorded = r[2]; st.consec = 0; st.consecKinds = []; st.skelConsec = 0
      acts.push("CAPTURE_AND_HIDE", "STOP_FRAMES", "SHOW_PAUSED_BANNER")
    }
    break
  case S.FROZEN:
    // 凍結中工作區已停畫格；gui_ms 此時只量骨架以外仍在花的時間
    st.skelConsec = (f.gui_ms > st.q) ? st.skelConsec + 1 : 0
    if (st.skelConsec >= P.CONSEC) st.pendingSafe = true
    if (st.pendingSafe) {
      if (!st.alertHold && !f.alert_pending) { st.state = S.SAFE_RULES; st.pendingSafe = false; acts.push("DESTROY_WORKSPACE", "SAFE_SCREEN") }
    } else if (f.t_ms - st.frozenAt >= P.FREEZE_MIN_MS && !f.alert_pending && !st.alertHold) {
      st.state = S.RESTORING; st.restoreIdx = 0; st.consec = 0; st.consecKinds = []
      acts.push("HIDE_PAUSED_BANNER", "RESUME_FRAMES")
    }
    break
  case S.RESTORING:
  case S.PROBATION:
    if (r[0]) {
      var dis = union(st.recorded, r[2]); st.disabled = union(st.disabled, dis)
      acts.push("DISABLE_KINDS:" + dis.join(","))
      var off = st.disabled.indexOf(P.ANSWER_KIND) >= 0
      for (var i = 0; i < st.required.length; i++) if (st.disabled.indexOf(st.required[i]) >= 0) off = true
      if (off) { st.state = S.WORKSPACE_OFF; acts.push("WORKSPACE_OFF", "ANSWER_TO_SKELETON_TEXT") }
      else { st.state = S.FROZEN; st.frozenAt = f.t_ms; st.recorded = []; st.skelConsec = 0
             acts.push("CAPTURE_AND_HIDE", "STOP_FRAMES", "SHOW_PAUSED_BANNER", "REPLAN_WITHOUT_DISABLED") }
      break
    }
    if (st.state === S.RESTORING) {
      if (st.alertHold) break
      if (st.restoreIdx < st.order.length) { acts.push("RESTORE:" + st.order[st.restoreIdx]); st.restoreIdx++ }
      if (st.restoreIdx >= st.order.length) { st.state = S.PROBATION; st.probationAt = f.t_ms }
    } else if (f.t_ms - st.probationAt >= P.PROBATION_MS) {
      st.state = S.NORMAL; st.recorded = []
    }
    break
  default: break   // SAFE_RULES、WORKSPACE_OFF 為終態，直到重新啟動
  }
  return { st: st, actions: acts }
}
