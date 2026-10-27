"""產生智慧告警 demo：跑兩趟模擬（不理會告警 / 採用建議），每個告警經 LLM 說明，輸出可播放的 HTML。

用法：
  GCS_LLM_BACKEND=none   python3 -m gcs_demo.alerts.run_demo out/      # 不用模型，全走規則
  GCS_LLM_BACKEND=ollama GCS_LLM_URL=http://127.0.0.1:11434 GCS_LLM_MODEL=gemma4:e2b \
                         python3 -m gcs_demo.alerts.run_demo out/      # 真實模型推論
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import explain, sim
from .energy_api import SOURCE as ENERGY_SOURCE


def main(out_dir="out"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    backend = explain.get_backend()
    runs = {}
    for policy in ("ignore", "follow"):
        t0 = time.time()
        r = sim.run(scenario="gusty", policy=policy, explain_fn=lambda ev: explain.explain(ev, backend))
        r["wall_s"] = round(time.time() - t0, 1)
        runs[policy] = r
        n_llm = sum(1 for e in r["events"] if e.get("explain", {}).get("source") == "llm")
        print(f"{policy}: {len(r['events'])} 事件（模型說明 {n_llm}）落地 {r['summary']['landed_true_pct_of_nominal']}%")
    meta = {"backend": getattr(backend, "name", "?"), "model": getattr(backend, "model", None),
            "energy_source": ENERGY_SOURCE, "generated": time.strftime("%Y-%m-%d %H:%M", time.localtime())}
    data = {"meta": meta, "runs": runs}
    (out / "alerts_demo.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    html = (Path(__file__).with_name("demo_template.html")).read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    (out / "alerts_demo.html").write_text(html, encoding="utf-8")
    print("寫出", out / "alerts_demo.html")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OUT", "out"))
