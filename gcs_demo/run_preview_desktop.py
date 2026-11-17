"""桌面啟動檔：同一程序內啟動原本的 demo 伺服器（原樣，8765）與預覽伺服器（127.0.0.1:8766）。

token 由上層啟動器經 stdin 第一行傳入（不寫檔、不寫日誌）；沒有 token 就不啟動預覽伺服器。
用法：  <產生 token 的啟動器> | python -m gcs_demo.run_preview_desktop --store ./gcs_store
不改 server.py。
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer

from . import server
from . import commit_layer as cl
from .preview_api import PreviewServer, PreviewService, SessionFeeder


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--preview-port", type=int, default=8766)
    ap.add_argument("--store", default=os.environ.get("GCS_STORE_DIR", "gcs_store"))
    ap.add_argument("--rules-only", action="store_true")
    a = ap.parse_args(argv)
    token = sys.stdin.readline().strip()
    if len(token) < 32:
        print("預覽伺服器未啟動：stdin 沒有收到 token", file=sys.stderr)
        return 2
    server.apply_mvp_llm_defaults(a.rules_only)
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", a.port), server.Handler).serve_forever,
                     daemon=True).start()
    cl.init_store(a.store)
    coord, rep = cl.boot(a.store)
    feeder = SessionFeeder(server.SESSION, coord)
    evid = os.path.join(a.store, "evidence", f"boot-{int(time.time())}", "previews.jsonl")
    svc = PreviewService(coord, feeder, evid)

    def feed():
        while True:
            try:
                feeder.poll()
            except Exception:  # noqa: BLE001 - 任務執行中拿不到鎖時下一輪再試
                pass
            time.sleep(0.2)
    threading.Thread(target=feed, daemon=True).start()
    print(f"demo：http://127.0.0.1:{a.port}/  預覽：127.0.0.1:{a.preview_port}（boot_epoch {svc.boot_epoch}；"
          f"恢復：凍結 {len(rep['frozen'])} 項）")
    PreviewServer(("127.0.0.1", a.preview_port), svc, token).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
