"""辨識切換 LLM 冒煙測試：農業／巡檢／多機各呼叫一次 llm_pick（經共用閘道）。

只準備、不自動執行。使用者打「同意 <hash8>」後只跑一次；首次結果與失敗原樣保留，不重跑。

    python3 -m gcs_demo.recognition.smoke_llm --dry-run          # 只印出 prompt 與 bundle hash8，不呼叫模型
    python3 -m gcs_demo.recognition.smoke_llm --out <新目錄>      # 實際呼叫 3 次；目錄已存在就拒絕

bundle hash = 本腳本與演算法來源檔、場域設定檔、模型 manifest 的 SHA256 清單再取 SHA256。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from ..domain_profile import load_classes, load_domains
from . import selector as S
from .switcher import GATEWAY_MODEL, GATEWAY_URL, Switcher, default_backend

ROOT = Path(__file__).resolve().parents[2]
DOMAINS = ("agriculture", "inspection", "multi_uav")


def bundle_files():
    base = ROOT / "gcs_demo"
    files = [base / "llm.py", base / "domain_profile.py"]
    files += sorted((base / "recognition").glob("*.py"))
    files += sorted((base / "domains").glob("*.json"))
    files += sorted((base / "recognition" / "models").glob("*.json"))
    return [f for f in files if f.is_file()]


def bundle_manifest():
    rows = []
    for f in bundle_files():
        data = f.read_bytes().replace(b"\r\n", b"\n")
        rows.append(f"{hashlib.sha256(data).hexdigest()}  {f.relative_to(ROOT).as_posix()}")
    text = "\n".join(rows) + "\n"
    return text, hashlib.sha256(text.encode()).hexdigest()


def prepare():
    s = Switcher(backend=None)
    items = []
    for did in DOMAINS:
        dom = s.domains[did]
        ev = S.evaluate(dom, s.rows(), s.alias, None, s.class_zh)
        system, user, ids = S.build_prompt(dom, ev) if ev["decision"] == "SELECT" else (None, None, {})
        items.append({"domain": did, "evaluation": ev, "system": system, "user": user, "ids": ids})
    return items


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    manifest, full = bundle_manifest()
    items = prepare()
    print(f"bundle sha256 {full}\nhash8 {full[:8]}")
    if a.dry_run or not a.out:
        for it in items:
            print(f"\n== {it['domain']}  規則選擇 {it['evaluation']['choice']}  候選 {sorted(it['ids'])}")
            print(it["user"])
        if not a.dry_run:
            print("\n未給 --out，未呼叫模型。")
        return 0
    out = Path(a.out)
    if out.exists():
        print("輸出目錄已存在，拒絕執行（每次只跑一次，修正另開新目錄）", file=sys.stderr)
        return 2
    out.mkdir(parents=True)
    (out / "sha256.txt").write_text(manifest, encoding="utf-8")
    backend = default_backend()
    env = {"backend": getattr(backend, "name", "none"), "url": getattr(backend, "url", ""),
           "model": getattr(backend, "model", ""), "default_url": GATEWAY_URL, "default_model": GATEWAY_MODEL,
           "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    results = []
    for it in items:
        dom = load_domains()[it["domain"]]
        rec = S.llm_pick(backend, dom, it["evaluation"])
        model_id, source, reason, raw = rec
        results.append({"domain": it["domain"], "rule_choice": it["evaluation"]["choice"], "picked": model_id,
                        "source": source, "reason_zh": reason, "llm": raw,
                        "agree_with_rule": model_id == it["evaluation"]["choice"]})
        print(f"{it['domain']}: {source} → {model_id}（規則 {it['evaluation']['choice']}）")
    (out / "run1.json").write_text(json.dumps({"env": env, "results": results}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    ok = sum(r["source"] == "llm" for r in results)
    print(f"模型有效輸出 {ok}/3；結果 {out / 'run1.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
