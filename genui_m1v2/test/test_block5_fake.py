"""第 5 塊用假 backend 的固定案例（雲端）。真正的 Job Object 要在 PC 上另測。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'host'))
import ollama_stop as S
P = F = 0
def ok(i, c, m=''):
    global P, F
    if c: P += 1
    else: F += 1; print('FAIL', i, m)
class Fake:
    def __init__(s, busy=False, die_after=0.3, never_die=False):
        s.t = 0.0; s.busy = busy; s.procs = 0; s.die_at = None; s.die_after = die_after; s.never = never_die; s.calls = []
    def clock(s): return s.t
    def sleep(s, d): s.t += d
    def port_in_use(s, p):
        return s.busy or (s.procs > 0 and not (s.die_at is not None and s.t >= s.die_at and not s.never))
    def create_suspended_in_job(s, p): s.calls.append('create_suspended'); s.procs = 2
    def resume(s): s.calls.append('resume')
    def job_process_count(s): return 0 if (s.die_at is not None and s.t >= s.die_at and not s.never) else s.procs
    def close_connection(s): s.calls.append('close')
    def terminate_job(s): s.calls.append('terminate'); s.die_at = s.t + s.die_after
    def restart(s, p): s.calls.append('restart'); s.die_at = None; s.procs = 2
def mk(**k):
    f = Fake(**k); return f, S.Slot(f, f.clock)
# K1 埠被占用 → 停下回報，不建立程序
f, s = mk(busy=True); ok('K1', s.start(11500) == 'PORT_BUSY' and 'create_suspended' not in f.calls)
# K2 先暫停建立再放行
f, s = mk(); s.start(11500); ok('K2', f.calls[:2] == ['create_suspended', 'resume'])
# K3 正常完成：done 且 2 秒內 HTTP 結束 → 名額可交出，不殺 Job
f, s = mk(); s.start(11500); s.begin_request(); ok('K3', s.finish(True, 1.9) == 'SLOT_FREE' and s.can_hand_over() and 'terminate' not in f.calls)
# K4 done 但 HTTP 2.01 秒才結束 → 走取消，關連線→結束 Job→確認→重啟
f, s = mk(); s.start(11500); s.begin_request(); r = s.finish(True, 2.01)
ok('K4', r == 'SLOT_FREE' and f.calls[2:] == ['close', 'terminate', 'restart'] and s.can_hand_over(), (r, f.calls))
# K5 5 秒內確認不了 → 模型暫停、不重試、不能交出名額
f, s = mk(never_die=True); s.start(11500); s.begin_request(); r = s.cancel('user')
ok('K5', r == 'MODEL_PAUSED' and f.calls.count('terminate') == 1 and 'restart' not in f.calls and not s.can_hand_over())
ok('K5b', s.start(11500) == 'MODEL_PAUSED')
# K6 4.9 秒才停 → 仍在 5 秒內，算確認
f, s = mk(die_after=4.9); s.start(11500); s.begin_request(); ok('K6', s.cancel('user') == 'SLOT_FREE')
print(S.STOP_VERSION, 'pass', P, 'fail', F); sys.exit(1 if F else 0)
