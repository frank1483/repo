// 用 node 算同一組排版，給 collect_gui.py 比對 Qt 端引擎輸出。用法：node make_expect.js > expect_gui.json
const L = require('../test/load.js'), { Tools, Claims, Layout } = L
const R = (a, b) => { const s = []; for (let t = 0; t <= 60; ++t) s.push({ t, soc: a + b * t / 60 }); return s }
const res = [Tools.energyTrend(R(80, -1), { now: 60, reservePct: 20, vehicleType: 'multirotor' }),
  Tools.alertHistory([{ t: 10, level: 'critical', predictor: 'p', text: 'a' }, { t: 20, level: 'warning', predictor: 'p', text: 'b' }, { t: 30, level: 'info', predictor: 'p', text: 'c' }], { t0: 0, t1: 60 }, []),
  Tools.manualSearch([{ chunk_id: 'k1', doc: 'D', heading: 'RTL', version: 'v1', text: '返航保留電量的設定方式' }], '返航保留電量', {})]
const answer = Claims.answer(res, { omitted_tools: ['T_FLIGHTLOG'] }), plan = Layout.plan('r1', answer, res), out = {}
for (const h of [1080, 600, 500, 400, 200, 120]) {
  const c = Layout.layout(plan, { width: 1920, height: h, revision: 1 }, res, { request_id: 'r1', answer })
  out['h' + h] = { ok: c.ok, error: c.error, rects: c.layout ? c.layout.rects : [], dropped: c.layout ? c.layout.dropped : null, compact: c.layout ? c.layout.compact : null }
}
process.stdout.write(JSON.stringify(out))
