// G4 第 5 版：程式 0.4（附件 v3.1c）的新案例。預期值由條文手算，先於執行提交。
const R = (a, b, n = 61, t0 = 0) => Array.from({ length: n }, (_, i) => ({ t: t0 + i, soc: a + b * i / 60 }))
const O = x => Object.assign({ now: 60, reservePct: 20, vehicleType: 'multirotor' }, x || {})
const energy = [], E = (id, samples, opts, expect) => energy.push({ id, samples, opts, expect })
// J03b 末值 74：與前一筆 79 恰差 5 → 不算跳變；名目窗 [1,61] 共 61 筆；末筆偏離大，R² 約 0.329 < 0.8 → INSUFFICIENT r2
E('J03b_step5_exact', R(80, -1).concat([{ t: 61, soc: 74 }]), O({ now: 61 }), { status: 'INSUFFICIENT', detail: { jump_at: null, n_valid: 61, reason: 'r2', insufficient_reasons: ['r2'], eta_min: null, eta_reason: 'no_trend' } })
// K3 90−t/4 後接 (61,70)：前一筆 75，恰差 5 → 不跳變；61 筆、下降
E('K3_step5_then_ok', Array.from({ length: 61 }, (_, t) => ({ t, soc: 90 - t / 4 })).concat([{ t: 61, soc: 70 }]), O({ now: 61 }), { status: 'OK', detail: { jump_at: null, n_valid: 61, direction: '下降', insufficient_reasons: [] } })
// K4 固定 0.1、保留值 -1：回歸前判持平，斜率 0、R² 空、保留值無效、ETA 空、not_falling
E('K4_flat_0p1', Array.from({ length: 61 }, (_, t) => ({ t, soc: 0.1 })), O({ reservePct: -1 }), { status: 'OK', detail: { direction: '持平', slope_pct_per_min: 0, r2: null, reserve_valid: false, eta_min: null, eta_reason: 'not_falling' } })
// K5 79+(t%2)、now 70、檢查過期：過期，同時保留 R² 不足；不發布方向
E('K5_stale_and_r2', Array.from({ length: 61 }, (_, t) => ({ t, soc: 79 + (t % 2) })), { now: 70, checkStale: true, reservePct: 20 }, { status: 'STALE', detail: { stale: true, insufficient_reasons: ['r2'], insufficient_reason: 'r2', reason: 'stale', direction: null, eta_min: null, eta_reason: 'no_trend' } })
// K6 多項不足同時記：5 筆、0..4 秒 → n_valid、coverage 都不足；主要原因 n_valid
E('K6_multi_insufficient', R(80, -1, 5), O({ now: 4 }), { status: 'INSUFFICIENT', detail: { insufficient_reasons: ['n_valid', 'coverage'], reason: 'n_valid' } })
// K7 跳變在名目窗外（t=0→1 跳 10，之後到 t=100）：名目窗 [40,100] 內無跳變 → jump_at null
E('K7_jump_outside_window', [{ t: 0, soc: 95 }].concat(R(85, -1, 100, 1)), O({ now: 100 }), { status: 'OK', detail: { jump_at: null, n_valid: 61 } })
// K8 E01 不變（ETA 59、eta_reason 空字串）
E('K8_E01', R(80, -1), O(), { status: 'OK', detail: { eta_min: 59, eta_reason: '', reserve_valid: true, reserve_pct: 20 } })
// K9 E05a 保留值無效（下降）
E('K9_reserve_invalid', R(80, -1), O({ reservePct: -1 }), { status: 'OK', detail: { eta_min: null, eta_reason: 'reserve_invalid', reserve_valid: false, reserve_pct: -1 } })

const flightlog = []
const cyc = i => [0, 50, 100][i % 3]
// FL02 301 列全在 t=100：統計用全部原值；桶寬 0 → 全部第 0 桶；同值取最早到達 → (100,0) 第 0 列、(100,100) 第 2 列
flightlog.push({ id: 'FL02_all_same_t', field: 'alt', unit: 'm', t0: 0, t1: 150, gaps: [], samples: Array.from({ length: 301 }, (_, i) => ({ t: 100, value: cyc(i) })),
  expect: { status: 'OK', points: [[100, 0], [100, 100]], facts: { 'alt.min': 0, 'alt.max': 100, 'alt.mean': 15000 / 301 } } })
// FL03 首列 (0,50)、其餘 300 列在 t=150：t=150 全進最後一桶；第 1 列是 0、第 3 列是 100
flightlog.push({ id: 'FL03_right_end', field: 'alt', unit: 'm', t0: 0, t1: 150, gaps: [], samples: [{ t: 0, value: 50 }].concat(Array.from({ length: 300 }, (_, i) => ({ t: 150, value: cyc(i) }))),
  expect: { status: 'OK', points: [[0, 50], [150, 0], [150, 100]] } })
// FL04 區間內沒有資料、沒有缺段 → 對外 ERROR
flightlog.push({ id: 'FL04_empty', field: 'alt', unit: 'm', t0: 0, t1: 60, gaps: [], samples: [], expect: { status: 'ERROR' } })

const chunks = [], manual = []
// M02 兩階段去重：c1/battery、c2/battery（同文件同文字被淘汰）、c2/motor（同 id 被淘汰）→ 查 motor 查不到
// M03 __proto__ 同 id 不同文件 → 只留一筆
// M04 單篇「返航 保留」查「如何設定返航保留電量」→ 內容詞 返航、保留、電量；命中 2/3
// M05 前 50：50 篇各重複一個詞 100 次，第 51 篇才同時有 alpha beta → 截前 50 後沒有合格 → 查不到
// M06 r3a-12 電池廢棄：返航 4 篇、保留 3 篇、電量 2 篇；過濾後只剩「電量」，保底補回「保留」→ 內容詞 [保留, 電量]；
//     電池廢棄片段命中 1/2 = 0.5 ≥ 0.5 → 依已確認的 v3.1c 仍會合格（r3a-12 沒有被這條修好，另報）
const sets = {
  M02: [{ chunk_id: 'c1', doc: 'D', text: 'battery' }, { chunk_id: 'c2', doc: 'D', text: 'battery' }, { chunk_id: 'c2', doc: 'D', text: 'motor' }],
  M03: [{ chunk_id: '__proto__', doc: 'A', text: 'battery' }, { chunk_id: '__proto__', doc: 'B', text: 'battery' }],
  M04: [{ chunk_id: 'x1', doc: 'D', text: '返航 保留' }],
  M05: [].concat(
    Array.from({ length: 13 }, (_, i) => ({ chunk_id: 'a' + i, doc: 'D' + i, text: Array(100).fill('alpha').join(' ') })),
    Array.from({ length: 13 }, (_, i) => ({ chunk_id: 'b' + i, doc: 'E' + i, text: Array(100).fill('beta').join(' ') })),
    Array.from({ length: 12 }, (_, i) => ({ chunk_id: 'g' + i, doc: 'F' + i, text: Array(100).fill('gamma').join(' ') })),
    Array.from({ length: 12 }, (_, i) => ({ chunk_id: 'd' + i, doc: 'G' + i, text: Array(100).fill('delta').join(' ') })),
    [{ chunk_id: 'z51', doc: 'Z', text: 'alpha beta ' + Array(98).fill('filler').join(' ') }]),
  M06: [{ chunk_id: 'm1', doc: 'D', text: '返航 保留 電量 設定說明' }, { chunk_id: 'm2', doc: 'D', text: '返航 保留 高度' }, { chunk_id: 'm3', doc: 'D', text: '返航 保留 速度' },
        { chunk_id: 'm4', doc: 'D', text: '返航 航線' }, { chunk_id: 'm5', doc: 'D', text: '電池廢棄 電量 回收' },
        { chunk_id: 'm6', doc: 'D', text: '相機 曝光' }, { chunk_id: 'm7', doc: 'D', text: '雲台 角度' }, { chunk_id: 'm8', doc: 'D', text: '影像 傳輸' },
        { chunk_id: 'm9', doc: 'D', text: '地圖 圖層' }, { chunk_id: 'm10', doc: 'D', text: '韌體 更新' }]
}
for (const k in sets) for (const c of sets[k]) chunks.push(Object.assign({ set: k, heading: 'h', version: 'v1' }, c))
manual.push({ id: 'M02_two_stage', set: 'M02', query: 'motor', use_glossary: false, expect: { status: 'EMPTY_COMPLETE', hit_ids: [] } })
manual.push({ id: 'M03_proto', set: 'M03', query: 'battery', use_glossary: false, expect: { status: 'OK', hit_ids: ['__proto__'] } })
manual.push({ id: 'M04_content_v1', set: 'M04', query: '如何設定返航保留電量', use_glossary: false, expect: { status: 'OK', hit_ids: ['x1'] } })
manual.push({ id: 'M05_top50', set: 'M05', query: 'alpha beta gamma delta', use_glossary: false, expect: { status: 'EMPTY_COMPLETE', hit_ids: [] } })
manual.push({ id: 'M06_battery_disposal', set: 'M06', query: '如何設定返航保留電量', use_glossary: false, expect: { status: 'OK', hit_set: ['m1', 'm2', 'm3', 'm5'] } })
process.stdout.write(JSON.stringify({ version: 'g4-v5', chunks, glossary: {}, cases: { energy, telemetry: [], flightlog, alerts: [], manual } }, null, 1))
