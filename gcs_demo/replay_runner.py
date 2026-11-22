"""v3.10 離線回放：把某一次 live 跑次「模型實際回覆的原文」依呼叫用途（stage1、step:*、plan、replan）照順序重播給新程式。
不呼叫任何模型：回覆用完就丟例外（控制器照常走規則備援）。索引用 fake 設定（不算查詢向量），
所以候選排序可能和 live 不同；結果只當離線回歸，不是 live。

用法：
  python -m gcs_demo.replay_runner A --phase smoke --src ../runs/v39_A_live_smoke_run1 --out ../runs/v310_replay_A_smoke_run1
  python -m gcs_demo.replay_runner B --phase smoke --src ../runs/v39_B_live_smoke_run1 --out ../runs/v310_replay_B_smoke_run1 \
      --shared-from ../runs/v310_replay_A_smoke_run1
"""
from __future__ import annotations

import json
import os
import sys

from . import m4b_runner as R4

_CUR = {"key": None}
_SRC = {"dir": None}


def recorded(cond, case):
    p = os.path.join(_SRC["dir"], "cases", cond, case, "full.json")
    if not os.path.exists(p):
        return {}
    q = {}
    for c in json.load(open(p, encoding="utf-8")).get("calls") or []:
        if c.get("raw") is not None:
            q.setdefault(c["purpose"], []).append(c["raw"])
    return q


def replay_model(calls_log):
    queue = recorded(*_CUR["key"])

    def model(call):
        purpose = call.get("purpose", "")
        xs = queue.get(purpose) or []
        if not xs:
            calls_log.append({"purpose": purpose, "feature": "replay", "status": None, "raw": None, "error": "recording_exhausted"})
            raise RuntimeError("回放紀錄已用完")
        out = xs.pop(0)
        calls_log.append({"purpose": purpose, "feature": "replay", "status": 200, "latency_s": 0.0, "raw": out, "usage": None})
        return out
    return model


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    which = argv.pop(0)
    k = argv.index("--src")
    _SRC["dir"] = argv[k + 1]
    del argv[k:k + 2]
    if which == "B":
        from . import planb_runner as PB           # 匯入時把 R4.run_case 換成 B 的版本
        mod = PB
    else:
        mod = R4
    inner = R4.run_case

    def run_case(case, cond, factory, graph, counter, work):
        _CUR["key"] = (cond["id"], case["id"])
        return inner(case, cond, factory, graph, counter, work)
    R4.run_case = run_case
    R4.fake_model = replay_model
    R4.RUN_PROBE = False
    R4.HARNESS["name"] = R4.HARNESS.get("name", "") + "+replay"
    R4.EXTRA_INFO = lambda: {"replay_of": os.path.abspath(_SRC["dir"]),
                             "replay_note": "重播 live 原始回覆，未呼叫模型；fake 索引（無查詢向量），只當離線回歸"}
    return mod.main(argv + ["--fake"])


if __name__ == "__main__":
    sys.exit(main())
