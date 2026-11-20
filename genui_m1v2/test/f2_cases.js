// F2 手算案例（說明 f2_deviation_v1 §6）。JS 與 Python（test/ref_deviation.py）共用這份輸入。
const R = 6371008.8, deg = m => m / R * 180 / Math.PI     // 公尺 → 緯度差（度）
const line = n => Array.from({ length: n }, (_, i) => ({ seq: i, lat: 0, lon: deg(100 * i) }))   // 赤道上每 100 m 一點（cos0=1）
const S = (pts) => pts.map((p, i) => ({ t: i, lat: p[0], lon: p[1] }))
module.exports = [
  { name: 'straight_north_11m', wp: line(2), s: S([[deg(11), deg(50)]]), t0: 0, t1: 10, expect: { status: 'OK', max: 11, mean: 11 } },
  { name: 'beyond_end_endpoint', wp: line(2), s: S([[0, deg(130)]]), t0: 0, t1: 10, expect: { status: 'OK', max: 30 } },
  { name: 'L_shape', wp: [{ seq: 0, lat: 0, lon: 0 }, { seq: 1, lat: 0, lon: deg(100) }, { seq: 2, lat: deg(100), lon: deg(100) }], s: S([[deg(50), deg(80)]]), t0: 0, t1: 10, expect: { status: 'OK', max: 20 } },
  { name: 'invalid_middle_breaks', wp: [{ seq: 0, lat: 0, lon: 0 }, { seq: 1, lat: 0, lon: deg(100) }, { seq: 2, lat: NaN, lon: 0 }, { seq: 3, lat: 0, lon: deg(300) }, { seq: 4, lat: 0, lon: deg(400) }],
    s: S([[deg(40), deg(200)]]), t0: 0, t1: 10, expect: { status: 'PARTIAL', breaks: 1, segs: 2 } },   // 不接 B–C：到最近端點的距離 > 40
  { name: 'all_invalid', wp: [{ seq: 0, lat: 200, lon: 0 }, { seq: 1, lat: null, lon: 1 }], s: S([[0, 0]]), t0: 0, t1: 10, expect: { status: 'INSUFFICIENT', reason: 'no_segment' } },
  { name: 'single_point', wp: [{ seq: 0, lat: 0, lon: 0 }], s: S([[0, 0]]), t0: 0, t1: 10, expect: { status: 'INSUFFICIENT', reason: 'no_segment' } },
  { name: 'duplicate_points', wp: [{ seq: 0, lat: 0, lon: 0 }, { seq: 1, lat: 0, lon: 0 }], s: S([[0, 0]]), t0: 0, t1: 10, expect: { status: 'INSUFFICIENT', reason: 'no_segment' } },
  { name: 'seg_0_009m_rejected', wp: [{ seq: 0, lat: 0, lon: 0 }, { seq: 1, lat: deg(0.009), lon: 0 }], s: S([[0, 0]]), t0: 0, t1: 10, expect: { status: 'INSUFFICIENT', reason: 'no_segment' } },
  { name: 'seg_0_011m_accepted', wp: [{ seq: 0, lat: 0, lon: 0 }, { seq: 1, lat: deg(0.011), lon: 0 }], s: S([[0, deg(5)]]), t0: 0, t1: 10, expect: { status: 'OK', max: 5 } },
  { name: 'antimeridian_waypoints', wp: [{ seq: 0, lat: 0, lon: 179.9 }, { seq: 1, lat: 0, lon: -179.9 }], s: S([[0, 179.95]]), t0: 0, t1: 10, expect: { status: 'INSUFFICIENT', reason: 'antimeridian' } },
  { name: 'no_samples_error', wp: line(2), s: [], t0: 0, t1: 10, expect: { status: 'ERROR' } },
  { name: 'no_samples_with_gap_partial', wp: line(2), s: [], t0: 0, t1: 10, gaps: [[2, 5]], expect: { status: 'PARTIAL' } },
  { name: 'downsample_mean_raw', wp: line(11), s: Array.from({ length: 601 }, (_, i) => ({ t: i, lat: deg(i % 7), lon: deg(i * 1000 / 600) })), t0: 0, t1: 600, expect: { status: 'OK', max: 6, mean: Array.from({ length: 601 }, (_, i) => i % 7).reduce((a, b) => a + b, 0) / 601, down: true } },
  { name: 'window_filter_and_order', wp: line(2), s: [{ t: 5, lat: deg(3), lon: deg(10) }, { t: 1, lat: deg(9), lon: deg(10) }, { t: 20, lat: deg(50), lon: deg(10) }], t0: 0, t1: 10, expect: { status: 'OK', max: 9, mean: 6 } }
]
