// G4 第 4 版：V3.1-2（跳變規則、R² 0.8）的新案例，預期值由條文手算，先於執行提交。
const R = (a, b, n = 61, t0 = 0) => Array.from({ length: n }, (_, i) => ({ t: t0 + i, soc: a + b * i / 60 }))
const O = x => Object.assign({ now: 60, reservePct: 20, vehicleType: 'multirotor' }, x || {})
const energy = [], E = (id, samples, opts, expect) => energy.push({ id, samples, opts, expect })
// J01 下降 0..60 後在 61 跳到 100，之後 61..120 持平：跳變在 61，視窗 61..120 共 60 筆、覆蓋 59/60 → 持平
E('J01_jump_then_flat', R(80, -1).concat(R(100, 0, 60, 61)), O({ now: 120 }), { status: 'OK', detail: { jump_at: 61, n_valid: 60, direction: '持平' } })
// J02 跳變後只有 10 秒：覆蓋不足
E('J02_jump_recent', R(80, -1).concat(R(100, 0, 11, 61)), O({ now: 71 }), { status: 'INSUFFICIENT', detail: { jump_at: 61, reason: 'coverage' } })
// J03 剛好 5%：不算跳變（> 5 才算）
E('J03_step5', R(80, -1).concat([{ t: 61, soc: 79 - 1 / 60 - 5 }]), O({ now: 61 }), { status: 'OK', detail: { jump_at: null } })
// J04 E01 不受影響
E('J04_E01', R(80, -1), O(), { status: 'OK', detail: { jump_at: null, eta_min: 59, r2: 1 } })
// J05 R² 介於 0.5 與 0.8：交錯 ±0.2 的雜訊（R² 約 0.68，見下行計算）→ 舊門檻 0.5 會過、新門檻 0.8 不過
E('J05_r2_mid', R(80, -1).map((p, i) => ({ t: p.t, soc: p.soc + (i % 2 ? 0.2 : -0.2) })), O(), { status: 'INSUFFICIENT', detail: { reason: 'r2' } })
process.stdout.write(JSON.stringify({ version: 'g4-v4', chunks: [], glossary: {}, cases: { energy, telemetry: [], flightlog: [], alerts: [], manual: [] } }, null, 1))
