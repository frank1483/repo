"""告警計分（附件 §F、v3.1b §F'；M1 演算法說明 v3 補充第 4 節，使用者 11/16 13:58「五塊照說明」）。
純函式，評估端使用。時間單位秒（float）。對時門檻 RTT_MAX_S 為候選值〔待凍結〕。"""
SCORE_VERSION = "alertscore-m1-0.1"
MERGE_GAP_S = 5.0
WINDOW_TAIL_S = 5.0
RTT_MAX_S = 0.001

def merge_segments(segs):
    """segs: [{session, vehicle, predictor, start, end}]。同 key 間隔 <= 5 s 合併。執行前做一次，之後不改。"""
    out = []
    key = lambda s: (s["session"], s["vehicle"], s["predictor"])
    for s in sorted(segs, key=lambda s: (key(s), s["start"], s["end"])):
        if out and key(out[-1]) == key(s) and s["start"] - out[-1]["end"] <= MERGE_GAP_S:
            out[-1]["end"] = max(out[-1]["end"], s["end"])
        else:
            out.append(dict(s))
    return out

def score(segs_merged, events, level_ok):
    """events: [{session, vehicle, predictor, t, kind('rise'|...), level}]；level_ok(seg, level)->bool。
    只看升起事件、同 session／機體／預測器。窗 [start, end+5]，兩端都算。"""
    per, dup, low, fp = [], 0, 0, 0
    rises = sorted([e for e in events if e["kind"] == "rise"], key=lambda e: e["t"])
    used = set()
    for s in segs_merged:
        lo, hi = s["start"], s["end"] + WINDOW_TAIL_S
        inwin = [i for i, e in enumerate(rises)
                 if (e["session"], e["vehicle"], e["predictor"]) == (s["session"], s["vehicle"], s["predictor"])
                 and lo <= e["t"] <= hi]
        used.update(inwin)
        hit = next((i for i in inwin if level_ok(s, rises[i]["level"])), None)
        n_low = sum(1 for i in inwin if not level_ok(s, rises[i]["level"]))
        if hit is not None:
            res = "HIT"; dup += sum(1 for i in inwin if i != hit and level_ok(s, rises[i]["level"]))
        elif inwin:
            res = "LEVEL_LOW"
        else:
            res = "MISS"
        low += n_low
        per.append({"seg": s, "result": res, "first_ok_t": rises[hit]["t"] if hit is not None else None})
    fp = sum(1 for i in range(len(rises)) if i not in used)
    return {"per_segment": per, "duplicate_rises": dup, "low_level_rises": low, "false_alarms": fp,
            "version": SCORE_VERSION}

def clock_offset(samples):
    """samples: 5 次來回，每次 (t0 重放器送, t1 Qt 收, t2 Qt 回, t3 重放器收)。
    取 RTT 最短一次：offset = ((t1-t0)+(t2-t3))/2，rtt = (t3-t0)-(t2-t1)。rtt > 門檻整包無效。"""
    best = None
    for (t0, t1, t2, t3) in samples:
        rtt = (t3 - t0) - (t2 - t1)
        off = ((t1 - t0) + (t2 - t3)) / 2.0
        if best is None or rtt < best[0]:
            best = (rtt, off)
    if best is None or len(samples) != 5:
        return {"valid": False, "reason": "need_5_samples"}
    return {"valid": best[0] <= RTT_MAX_S, "rtt": best[0], "offset": best[1],
            "reason": None if best[0] <= RTT_MAX_S else "rtt_over_limit"}
