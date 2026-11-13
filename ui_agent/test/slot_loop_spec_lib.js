// Declarative method library used only by the conformance vectors (same logic as gcs_demo/test_agent_loop.py SpecLib).
function build(spec) {
  let h = null
  function act(a) {
    if (a.set) for (const k of Object.keys(a.set)) { if (k === 'kind') h.st.kind = a.set[k]; else h.st.slots[k] = a.set[k] }
    if (a.go) { h.go(a.go, a.obs); return '' }
    if (a.finish) { h.finish(a.finish, a.source, a.why); return '' }
    if (a.escalate) { h.escalate(a.escalate); return '' }
    if (a.rule) { h.ruleFallback(a.rule, a.source); return '' }
    if (a.problem) return a.problem
    throw Error('bad action')
  }
  return {
    begin(helper) { h = helper; act(spec.start) },
    options(st) { const s = spec.states[st.state]; return {need: s.need, allowed: s.allowed.map(([code, zh]) => ({code, zh}))} },
    header(st) {
      const l = spec.header.slice(); l.push('目前步驟：' + st.state)
      if (st.kind) l.push('已知：類別=' + st.kind)
      if (st.last_observation) l.push('觀察：' + st.last_observation)
      return l
    },
    transition(code) { return act(spec.states[h.st.state].on[code]) },
    ruleDecision() { return JSON.parse(JSON.stringify(spec.rule)) }
  }
}
module.exports = {build}
