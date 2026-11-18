"""第 4 塊（告警計分 0.2）與第 5 塊（Ollama 停止 0.2，假 backend）在 v3.1c 的新案例，預期手算。"""
import sys, os
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'eval')); sys.path.insert(0, os.path.join(H, '..', 'host'))
import alert_score as A, ollama_stop as S
P = F = 0
def ok(i, c, m=''):
    global P, F
    if c: P += 1
    else: F += 1; print('FAIL', i, m)
seg = lambda s, e: dict(session='s1', vehicle='v1', predictor='p', start=s, end=e)
ev = lambda t, lv=2: dict(session='s1', vehicle='v1', predictor='p', t=t, kind='rise', level=lv)
lok = lambda s, lv: lv >= 2
# F4 先合格、後低等級：命中 1、重複 0、等級不足 1，互不重疊
r = A.score([seg(0, 10)], [ev(1), ev(3, 1)], lok)
ok('F4a', r['per_segment'][0]['result'] == 'HIT' and r['duplicate_rises'] == 0 and r['low_level_rises'] == 1, r)
# F4 同鍵 [0,10]、[15,20] 合併；15 秒合格升起只配一次
m = A.merge_segments([seg(0, 10), seg(15, 20)]); r = A.score(m, [ev(15)], lok)
ok('F4b', len(m) == 1 and r['per_segment'][0]['result'] == 'HIT' and r['duplicate_rises'] == 0 and r['false_alarms'] == 0)
# F5 Codex C15：(0,5000001,5000001,1) → rtt 1 ns、offset floor(10000001/2)=5000000、誤差界 ceil(0.5)=1
smp = [(0, 5000001, 5000001, 1)] + [(10**6 * k, 10**6 * k + 5000100, 10**6 * k + 5000100, 10**6 * k + 300) for k in range(1, 5)]
c = A.clock_offset(smp)
ok('F5a', c['valid'] and c['rtt_ns'] == 1 and c['offset_ns'] == 5000000 and c['err_ns'] == 1, c)
# F5 最小 RTT 同分取最早
smp2 = [(0, 10, 10, 2), (100, 200, 200, 102), (1000, 1005, 1005, 1010), (2000, 2100, 2100, 2050), (3000, 3100, 3100, 3050)]
c2 = A.clock_offset(smp2)
ok('F5b', c2['rtt_ns'] == 2 and c2['offset_ns'] == 9, c2)
ok('F5c', A.clock_offset([(0.0, 1.0, 1.0, 2.0)] * 5)['valid'] is False)
class Fake:
    def __init__(s, assign_ok=True, die_after=0.3, never=False):
        s.t = 0.0; s.assign_ok = assign_ok; s.procs = 0; s.die_at = None; s.die_after = die_after; s.never = never; s.calls = []
    def clock(s): return s.t
    def sleep(s, d): s.t += d
    def alive(s): return s.procs > 0 and not (s.die_at is not None and s.t >= s.die_at and not s.never)
    def port_in_use(s, p): return s.alive()
    def create_suspended(s, p): s.calls.append('create_suspended'); s.procs = 1
    def assign_to_job(s): s.calls.append('assign'); return s.assign_ok
    def terminate_suspended(s): s.calls.append('terminate_suspended'); s.procs = 0
    def resume(s): s.calls.append('resume'); s.procs = 2
    def job_process_count(s): return s.procs if s.alive() else 0
    def close_connection(s): s.calls.append('close')
    def terminate_job(s): s.calls.append('terminate'); s.die_at = s.t + s.die_after
    def close_job_handle(s): s.calls.append('close_handle')
    def restart(s, p): s.calls.append('restart'); s.die_at = None; s.procs = 2
def mk(**k):
    f = Fake(**k); return f, S.Slot(f, f.clock)
# J1a 納管失敗 → 結束暫停程序、不恢復
f, s = mk(assign_ok=False); ok('J1a', s.start(11500) == 'ASSIGN_FAILED' and 'resume' not in f.calls and 'terminate_suspended' in f.calls)
# J1b 取消：關連線 → 結束 Job →（證據）→ 關控制代碼 → 重啟
f, s = mk(); s.start(11500); s.begin_request(); r = s.cancel('user')
ok('J1b', r == 'SLOT_FREE' and f.calls[3:] == ['close', 'terminate', 'close_handle', 'restart'], f.calls)
# J1c 5 秒內沒證據 → 不關控制代碼、模型暫停
f, s = mk(never=True); s.start(11500); s.begin_request(); r = s.cancel('user')
ok('J1c', r == 'MODEL_PAUSED' and 'close_handle' not in f.calls)
# J2 done:true、2 秒內結束，但本體截斷 → 走取消
f, s = mk(); s.start(11500); s.begin_request(); r = s.finish(True, 1.0, body_complete=False)
ok('J2a', 'terminate' in f.calls and r == 'SLOT_FREE')
f, s = mk(); s.start(11500); s.begin_request(); r = s.finish(True, 1.0, read_error=True)
ok('J2b', 'terminate' in f.calls)
f, s = mk(); s.start(11500); s.begin_request(); r = s.finish(True, 1.0)
ok('J2c', r == 'SLOT_FREE' and 'terminate' not in f.calls)
print(A.SCORE_VERSION, S.STOP_VERSION, 'pass', P, 'fail', F); sys.exit(1 if F else 0)
