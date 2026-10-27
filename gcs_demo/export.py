"""產生不需伺服器的單檔 HTML（備案：環境沒有 jupyter-server-proxy 時用）。

python3 -m gcs_demo.export gcs_demo_static.html
預先把預設風況下「每個候選 × 每個重規劃候選」的結果都算好嵌進頁面；
頁面操作和伺服器版相同，只是不能改風速（改了會提示）。模型呼叫在產生時進行。
"""
from __future__ import annotations

import json
import os
import sys

from . import server as srv

WEB = os.path.join(os.path.dirname(__file__), "web", "index.html")


def _k(*parts):
    return "|".join(f"{p:g}" if isinstance(p, float) else str(p) for p in parts)


def build() -> dict:
    data = {}
    srv.SESSION.reset()
    srv.SESSION.calib = 1.0
    data["scenario"] = srv.handle("/api/scenario", {})
    wind = data["scenario"]["wind"]
    todo, seen = [1.0], set()
    while todo:
        calib = round(todo.pop(0), 3)
        if calib in seen or len(seen) >= 3:
            continue
        seen.add(calib)
        srv.SESSION.reset()
        srv.SESSION.calib = calib
        plan = srv.handle("/api/plan", {"wind": wind})
        pk = _k("plan", calib)
        data[pk] = plan
        # 預設路徑（規則建議）先算，讓「套用修正係數」最常走的那條一定有預算結果
        for c in sorted(plan["candidates"], key=lambda c: c["id"] != plan["pick"]["choice_id"]):
            if not c["feasible"]:
                continue
            srv.SESSION.calib = calib
            srv.SESSION.plan = plan
            start = srv.handle("/api/start", {"choice_id": c["id"]})
            sk = _k("start", pk, c["id"])
            data[sk] = start
            if "report" in start:
                todo.append(start["report"]["next_calib"])
                continue
            rp = start["replan"]
            first = c["id"] == plan["pick"]["choice_id"]
            for rc in sorted(rp["candidates"], key=lambda x: x["id"] != rp["pick"]["choice_id"]):
                if not rc["feasible"]:
                    continue
                # 每個重規劃候選都從同一個暫停點重新模擬
                srv.SESSION.plan = plan
                srv.SESSION.calib = calib
                srv.handle("/api/start", {"choice_id": c["id"]})
                cont = srv.handle("/api/continue", {"choice_id": rc["id"]})
                data[_k("cont", sk, rc["id"])] = cont
                if first and rc["id"] == rp["pick"]["choice_id"]:
                    todo.insert(0, cont["report"]["next_calib"])
                else:
                    todo.append(cont["report"]["next_calib"])
    return data


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "gcs_demo_static.html"
    data = build()
    html = open(WEB, encoding="utf-8").read()
    inject = ("<script>window.STATIC_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
              .replace("</", "<\\/") + ";</script>\n")
    html = html.replace("<script>\nconst $", inject + "<script>\nconst $", 1)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已輸出 {out}（{os.path.getsize(out)/1e6:.1f} MB，{len(data)} 組預算結果）")


if __name__ == "__main__":
    main()
