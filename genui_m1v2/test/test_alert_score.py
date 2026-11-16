"""第 4 塊告警計分固定案例，預期值手算。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eval'))
import alert_score as A
P = F = 0
def ok(i, c, m=''):
    global P, F
    if c: P += 1
    else: F += 1; print('FAIL', i, m)
seg = lambda s, e, pr='p', v='v1', se='s1': dict(session=se, vehicle=v, predictor=pr, start=s, end=e)
ev = lambda t, lv=2, k='rise', pr='p', v='v1', se='s1': dict(session=se, vehicle=v, predictor=pr, t=t, kind=k, level=lv)
lok = lambda s, lv: lv >= 2
# S1 間隔 5.0 合併、5.01 不合併；不同預測器不合併
m = A.merge_segments([seg(0, 10), seg(15, 20), seg(25.01, 30), seg(12, 13, pr='q')])
ok('S1', [(x['predictor'], x['start'], x['end']) for x in m] == [('p', 0, 20), ('p', 25.01, 30), ('q', 12, 13)], m)
# S2 窗兩端都算：start 與 end+5
r = A.score([seg(10, 20)], [ev(10)], lok); ok('S2a', r['per_segment'][0]['result'] == 'HIT')
r = A.score([seg(10, 20)], [ev(25)], lok); ok('S2b', r['per_segment'][0]['result'] == 'HIT')
r = A.score([seg(10, 20)], [ev(25.001), ev(9.999)], lok); ok('S2c', r['per_segment'][0]['result'] == 'MISS' and r['false_alarms'] == 2)
# S3 只有等級不足 → LEVEL_LOW；先低後合格 → HIT 且計 1 低等級
r = A.score([seg(0, 10)], [ev(1, 1)], lok); ok('S3a', r['per_segment'][0]['result'] == 'LEVEL_LOW' and r['low_level_rises'] == 1)
r = A.score([seg(0, 10)], [ev(1, 1), ev(2, 3)], lok); ok('S3b', r['per_segment'][0]['first_ok_t'] == 2 and r['low_level_rises'] == 1)
# S4 重複升起另計；非 rise 事件不算；不同機體不配對
r = A.score([seg(0, 10)], [ev(1), ev(3), ev(4, k='clear'), ev(5, v='v2')], lok)
ok('S4', r['duplicate_rises'] == 1 and r['false_alarms'] == 1 and r['per_segment'][0]['first_ok_t'] == 1, r)
# C1 對時：取 RTT 最短；offset 手算
smp = [(0, 0.0105, 0.0106, 0.0021), (1, 1.0102, 1.0103, 1.0006), (2, 2.0110, 2.0111, 2.0030), (3, 3.0102, 3.0104, 3.0009), (4, 4.0101, 4.0102, 4.0008)]
c = A.clock_offset(smp)
ok('C1', c['valid'] and abs(c['rtt'] - 0.0005) < 1e-9 and abs(c['offset'] - 0.00995) < 1e-9, c)
# C2 最短 RTT 超過 1 ms → 整包無效；C3 不足 5 次 → 無效
ok('C2', A.clock_offset([(i, i + .01, i + .0101, i + .0021) for i in range(5)])['valid'] is False)
ok('C3', A.clock_offset(smp[:4])['valid'] is False)
print(A.SCORE_VERSION, 'pass', P, 'fail', F); sys.exit(1 if F else 0)
