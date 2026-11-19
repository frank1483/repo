.pragma library
// 換介面模糊轉場狀態機（轉場說明 v1，使用者 11/19 23:02「轉場照建議」）。純邏輯：宿主每格呼叫 tick，依回傳的 blur（0～1）與 swap 動作執行。
// 版本 trans-m1-0.1。轉場只是外觀：不延後、不改變交易結果；交易仍照 txn-m1-0.2。
var TRANS_VERSION = "trans-m1-0.1"
var S = { IDLE: "IDLE", BLUR_IN: "BLUR_IN", SWAP: "SWAP", BLUR_OUT: "BLUR_OUT" }
var P = { IN_MS: 120, OUT_MS: 180 }                     // T1
function init() { return { state: S.IDLE, t0: 0, disabled: false, swapped: false, log: [] } }
function copy(st) { return { state: st.state, t0: st.t0, disabled: st.disabled, swapped: st.swapped, log: st.log.slice() } }

// 交易結果到來。只有 SWITCHED 會換介面。ctx: {overrun_state, reduced_motion, effect_ok}
// 回傳 {st, actions}；actions 可能含 "swap_now"（不做轉場直接換）、"start"、"apply_lock"
function onTxn(st0, result, now, ctx) {
    var st = copy(st0), a = []
    if (result !== "SWITCHED") return { st: st, actions: a }
    var skip = st.disabled ? "disabled" : (ctx.overrun_state !== "NORMAL" ? "overrun_" + ctx.overrun_state : (ctx.reduced_motion ? "reduced_motion" : (!ctx.effect_ok ? "effect_unavailable" : "")))
    if (st.state !== S.IDLE) skip = skip || "busy"   // 不該發生（轉場中套用鍵鎖住）；保守直接換
    if (skip) { st.log.push({ t: now, ev: "skip", why: skip }); a.push("swap_now"); return { st: st, actions: a } }
    st.state = S.BLUR_IN; st.t0 = now; st.swapped = false; st.log.push({ t: now, ev: "start" })
    a.push("start", "apply_lock")
    return { st: st, actions: a }
}
// 每格呼叫。回傳 {st, blur, actions}；actions 可能含 "swap"（換成新排版，只會出現一次）、"apply_unlock"
function tick(st0, now) {
    var st = copy(st0), a = [], blur = 0, dt = now - st.t0
    if (st.state === S.IDLE) return { st: st, blur: 0, actions: a }
    if (st.state === S.BLUR_IN) {
        if (dt < P.IN_MS) return { st: st, blur: dt / P.IN_MS, actions: a }
        st.state = S.SWAP
    }
    if (st.state === S.SWAP) {
        a.push("swap"); st.swapped = true; st.state = S.BLUR_OUT; st.t0 = now
        return { st: st, blur: 1, actions: a }
    }
    // BLUR_OUT
    if (dt < P.OUT_MS) return { st: st, blur: 1 - dt / P.OUT_MS, actions: a }
    st.state = S.IDLE; st.log.push({ t: now, ev: "done" }); a.push("apply_unlock")
    return { st: st, blur: 0, actions: a }
}
// 新 critical 告警：立刻結束；還沒換就先換（交易已經 SWITCHED），清楚畫面
function onCritical(st0, now) {
    var st = copy(st0), a = []
    if (st.state === S.IDLE) return { st: st, blur: 0, actions: a }
    if (!st.swapped) { a.push("swap"); st.swapped = true }
    st.state = S.IDLE; st.log.push({ t: now, ev: "abort_critical" }); a.push("apply_unlock")
    return { st: st, blur: 0, actions: a }
}
// 轉場期間觸發畫面超支（T3）：本次開機停用；進行中的轉場照 onCritical 收掉
function onOverrun(st0, now) {
    var r = onCritical(st0, now)
    r.st.disabled = true; r.st.log.push({ t: now, ev: "disabled_overrun" })
    if (r.st.log.length >= 2 && r.st.log[r.st.log.length - 2].ev === "abort_critical") r.st.log[r.st.log.length - 2].ev = "abort_overrun"
    return r
}
// 效果載入失敗等：略過，直接換（說明 §3-1）
function onEffectError(st0, now) {
    var r = onCritical(st0, now); if (r.st.log.length && r.st.log[r.st.log.length - 1].ev === "abort_critical") r.st.log[r.st.log.length - 1].ev = "abort_effect_error"
    return r
}
