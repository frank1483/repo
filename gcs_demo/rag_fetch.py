"""下載 PX4／QGC 英文手冊 Markdown（只取文字），固定在某個 commit。

使用者 2026-11-18 21:38 同意 D-2、D-3（專案聊天室），23:55 在 ADR-0002 討論串「繼續：下載並建索引」。
來源：GitHub 公開 repo；授權 CC BY 4.0（docs.px4.io、QGC 文件授權頁）。不取圖片。
輸出：<out>/<name>/<commit>/<path> 與 <out>/<name>/FETCH_MANIFEST.json（每檔 sha256、bytes）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request

SOURCES = [
    {"name": "px4", "repo": "PX4/PX4-Autopilot", "ref": "main", "prefix": "docs/en/", "license": "CC BY 4.0"},
    {"name": "qgc", "repo": "mavlink/qgroundcontrol", "ref": "master", "prefix": "docs/en/", "license": "CC BY 4.0"},
]
UA = {"User-Agent": "thesis-rag-fetch", "Accept": "application/vnd.github+json"}


def get(url, accept=None):
    h = dict(UA)
    if accept:
        h["Accept"] = accept
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def fetch(src, out):
    commit = json.loads(get(f"https://api.github.com/repos/{src['repo']}/commits/{src['ref']}"))["sha"]
    top = src["prefix"].rstrip("/").split("/")
    sha = commit
    for part in top:                                    # 逐層找到 docs/en 的 tree
        tree = json.loads(get(f"https://api.github.com/repos/{src['repo']}/git/trees/{sha}"))
        sha = next(t["sha"] for t in tree["tree"] if t["path"] == part and t["type"] == "tree")
    tree = json.loads(get(f"https://api.github.com/repos/{src['repo']}/git/trees/{sha}?recursive=1"))
    if tree.get("truncated"):
        raise SystemExit("tree 被截斷，停下")
    files = [t for t in tree["tree"] if t["type"] == "blob" and t["path"].endswith(".md")]
    base = os.path.join(out, src["name"], commit)
    man = {"source": src, "commit": commit, "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "files": []}
    for i, t in enumerate(files):
        rel = src["prefix"] + t["path"]
        data = get(f"https://raw.githubusercontent.com/{src['repo']}/{commit}/{rel}", accept="text/plain")
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        man["files"].append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                             "git_blob": t["sha"]})
        if i % 100 == 0:
            print(src["name"], i, "/", len(files), flush=True)
    man["total_bytes"] = sum(f["bytes"] for f in man["files"])
    with open(os.path.join(out, src["name"], "FETCH_MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    return {"name": src["name"], "commit": commit, "files": len(man["files"]), "bytes": man["total_bytes"]}


if __name__ == "__main__":
    out = sys.argv[1]
    if any(os.path.exists(os.path.join(out, s["name"])) for s in SOURCES):
        raise SystemExit("輸出已存在；只下載一次，要更新請開新目錄")
    print(json.dumps([fetch(s, out) for s in SOURCES], ensure_ascii=False))
