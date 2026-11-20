// bind-m1-0.4／layout-m1-0.5：使用者 11/20 16:40 D1（W4 卡片）、D2（W1 排列與矮畫面空間規則）。舊測試不動。
const { Tools, Claims, Bind, Layout } = require('./load.js')
let pass = 0, fail = 0; const log = []
function ok(n, c, i) { if (c) pass++; else { fail++; log.push('FAIL ' + n + ' :: ' + JSON.stringify(i)) } }
const R = (a, b, j) => { const s = []; for (let t = 0; t <= 60; ++t) s.push({ t, soc: a + b * t / 60 + (j ? (t % 2 ? j : -j) : 0) }); return s }
const al = [{ t: 10, level: "critical", predictor: "電池", text: "電壓過低" }]
const man = [{ chunk_id: "k1", doc: "PX4 使用手冊", heading: "返航（RTL）", version: "v1.15", text: "返航保留電量的設定方式：在電池故障保護頁設定低電量門檻，到達門檻時飛機會自動返航。" }]
function scen(ea, eb, j) {
  const res = [Tools.energyTrend(R(ea, eb, j), { now: 60, reservePct: 20, vehicleType: "multirotor" }), Tools.alertHistory(al, { t0: 0, t1: 70 }, []), Tools.manualSearch(man, "返航保留電量", {})]
  const a = Claims.answer(res, { omitted_tools: ["T_FLIGHTLOG"] }); return { res, a, p: Layout.plan("r1", a, res), cm: (n, w) => Bind.contentMinH(n, res, a, w) }
}
const node = (s, id) => s.p.nodes.find(n => n.component_id === id)
// --- 縮短「未查」
ok('shortOmitted', Bind.shortOmitted("本次未執行：飛行紀錄（一次最多查三項）") === "未查：飛行紀錄", Bind.shortOmitted("本次未執行：飛行紀錄（一次最多查三項）"))
ok('shortOmitted two', Bind.shortOmitted("本次未執行：飛行紀錄、告警紀錄（一次最多查三項）") === "未查：飛行紀錄、告警紀錄")
// --- 安全情境：電量樣本不足（R² 低）→ T-CANNOT
const S = scen(80, -1, 0.2)
ok('safety scenario has T-CANNOT', S.a.lines.some(l => l.template_id === "T-CANNOT"), S.a.lines.map(l => l.template_id))
const w1 = Bind.resolve(node(S, "W1_FACT"), S.res, S.a)
ok('row roles', JSON.stringify(w1.data.lines.map(r => r.role)) === JSON.stringify(["safety", "omitted", "fact", "fact"]), w1.data.lines.map(r => r.role))
ok('answer lines keep original text', w1.data.lines[1].text === "本次未執行：飛行紀錄（一次最多查三項）" && w1.data.lines[1].short === "未查：飛行紀錄")
ok('Claims answer unchanged', S.a.lines[1].text === "本次未執行：飛行紀錄（一次最多查三項）")
const lowH = Bind.w1MinH(w1.data.lines, 950)
const arL = Bind.w1Arrange(w1.data.lines, lowH - Bind.W1M.padH, 950 - Bind.W1M.padW)
ok('low: order safety→main→(more)→omitted', arL.rows.map(r => r.role).join() === "safety,fact" && arL.tail.map(r => r.role).join() === "omitted" && arL.hidden === 1, arL)
ok('low: main fact is first fact', arL.rows[1].text === S.a.lines[2].text, arL.rows[1])
ok('low: omitted uses short text', arL.tail[0].text === "未查：飛行紀錄")
ok('low: min = pad + 4 lines', lowH === Bind.W1M.padH + 4 * Bind.W1M.lineH, lowH)
const total = arL.rows.concat(arL.tail).reduce((s, r) => s + r.h, 0) + (arL.hidden ? Bind.W1M.lineH : 0)
ok('low: fits', total <= lowH - Bind.W1M.padH, total)
const arH = Bind.w1Arrange(w1.data.lines, 1000, 950 - Bind.W1M.padW)
ok('high: everything shown', arH.hidden === 0 && arH.rows.length === 3 && arH.tail.length === 1, arH)
ok('high: doc row last before omitted', arH.rows[2].kind === "doc")
// 兩條安全提示＋必顯示事實
const two = [{ kind: "text", role: "safety", text: "電量趨勢的資料已過期", mandatory: true }, { kind: "text", role: "safety", text: "告警紀錄的資料不完整", mandatory: true },
             { kind: "text", role: "mandatory_fact", text: "查不到飛行紀錄的資料", mandatory: true }, { kind: "text", role: "fact", text: "電量 50%" },
             { kind: "text", role: "fact", text: "補充一" }, { kind: "text", role: "fact", text: "補充二" }, { kind: "text", role: "omitted", text: "本次未執行：飛行紀錄（一次最多查三項）", short: "未查：飛行紀錄" }]
const a2 = Bind.w1Arrange(two, Bind.w1MinH(two, 950) - Bind.W1M.padH, 950 - Bind.W1M.padW)
ok('two safety first in order', a2.rows[0].text === "電量趨勢的資料已過期" && a2.rows[1].text === "告警紀錄的資料不完整", a2.rows.map(r => r.text))
ok('main fact before other mandatory', a2.rows[2].text === "電量 50%" && a2.rows[3].text === "查不到飛行紀錄的資料", a2.rows.map(r => r.text))
ok('supplements folded into 還有 N 行', a2.hidden === 2 && a2.tail[0].text === "未查：飛行紀錄", a2)
// 窄寬度：長句換行，最小高度跟著變高
const longL = two.concat([{ kind: "text", role: "fact", text: "電量在最近十分鐘內持續下降，告警紀錄顯示電壓過低兩次" }])
const narrow = Bind.w1MinH([two[0], longL[longL.length - 1], two[6]], 300), wide = Bind.w1MinH([two[0], longL[longL.length - 1], two[6]], 1900)
ok('narrow needs more height', narrow > wide, [narrow, wide])
// --- 排版掛鉤
const Lo = Layout.layout(S.p, { width: 1920, height: lowH, revision: 1 }, S.res, { request_id: "r1", answer: S.a }, S.cm)
ok('layout ok at lowest height', Lo.ok, Lo.error)
const Lb = Layout.layout(S.p, { width: 1920, height: lowH - 1, revision: 1 }, S.res, { request_id: "r1", answer: S.a }, S.cm)
ok('layout fails 1 px lower (required W1)', !Lb.ok && Lb.error === "REQUIRED_OVERFLOW", Lb.error)
const Lnc = Layout.layout(S.p, { width: 1920, height: 130, revision: 1 }, S.res, { request_id: "r1", answer: S.a })
ok('no hook: same as 0.4 (catalog min W1 96／W3 128 fits 130)', Lnc.ok, Lnc.error)
const r1 = Lo.layout.rects.find(r => r.node_id === node(S, "W1_FACT").node_id)
ok('validate with hook ok', Layout.validateLayout(S.p, Lo.layout, { width: 1920, height: lowH, revision: 1 }, null, S.cm).ok, Layout.validateLayout(S.p, Lo.layout, { width: 1920, height: lowH, revision: 1 }, null, S.cm))
const shrunk = JSON.parse(JSON.stringify(Lo.layout)); shrunk.rects.forEach(r => { if (r.node_id === r1.node_id) r.height = 120 })
const vb = Layout.validateLayout(S.p, shrunk, { width: 1920, height: lowH, revision: 1 }, null, S.cm)
ok('validate catches below content min', !vb.ok && vb.error === "BELOW_CONTENT_MIN", vb)
ok('validate without hook accepts 120', Layout.validateLayout(S.p, shrunk, { width: 1920, height: lowH, revision: 1 }, null).ok)
// --- D1：W4 卡片
const E = scen(30, -15)
const d = Bind.resolve(node(E, "W4_DIAG"), E.res, E.a)
ok('R1 full sentence label', d.data.cards.some(c => c.label === Bind.ETA_NA_LABEL), d.data.cards)
const c308 = Bind.w4CardLayout(d.data.cards, 308), c632 = Bind.w4CardLayout(d.data.cards, 632), c1916 = Bind.w4CardLayout(d.data.cards, 1916)
const eta = i => d.data.cards.findIndex(c => c.label === Bind.ETA_NA_LABEL)
ok('wide: label 1 line', c1916.cards[eta()].labelLines === 1, c1916)
ok('632: label 2 lines', c632.cards[eta()].labelLines === 2, c632)
ok('308 (W4 min 3 cols at 1280): label > 2 lines, card grows', c308.cards[eta()].labelLines > 2 && c308.minH > c632.minH, c308)
ok('label lines cover text width', d.data.cards.every((c, i) => c308.cards[i].labelLines * (c308.cardW - 2 * Bind.W4M.padCard - Bind.W4M.dot) * 0.95 >= Bind.textWidth(c.label, Bind.W4M.labelPx)))
ok('value font >= 28, label 18', Bind.W4M.valuePx >= 28 && Bind.W4M.labelPx === 18 && Bind.W4M.unitPx === 18)
for (const W of [1280, 1920]) for (const H of [1080, 600, 400, 300]) {
  const L = Layout.layout(E.p, { width: W, height: H, revision: 1 }, E.res, { request_id: "r1", answer: E.a }, E.cm)
  const r4 = L.ok && L.layout.rects.find(r => r.node_id === node(E, "W4_DIAG").node_id)
  ok('W4 never below content min ' + W + 'x' + H, !r4 || r4.height >= Bind.w4CardLayout(d.data.cards, r4.width).minH, r4)
}
ok('textWidth CJK vs ASCII', Bind.textWidth("電量", 18) === 36 && Math.abs(Bind.textWidth("ab", 10) - 12) < 1e-9)
ok('versions', Bind.BIND_VERSION === "bind-m1-0.4.1" && Layout.LAYOUT_VERSION === "layout-m1-0.5", [Bind.BIND_VERSION, Layout.LAYOUT_VERSION])
console.log(log.join('\n')); console.log(`test_bind_v4 (${Bind.BIND_VERSION}, ${Layout.LAYOUT_VERSION}): pass ${pass} fail ${fail}`); process.exit(fail ? 1 : 0)
