"""本機已安裝模型清單。模型算「已安裝」要同時符合：manifest 合法、模型檔存在、SHA256 相符、driver 可用。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MODEL_DIR = Path(__file__).parent / "models"
_REQUIRED = ("id", "name_zh", "task", "runtime", "file", "sha256", "classes")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(drivers, model_dir=MODEL_DIR, device="demo-host"):
    """回傳每個 manifest 的狀態列（含沒安裝的，畫面要能說明為什麼不能選）。"""
    rows = []
    for p in sorted(Path(model_dir).glob("*.json")):
        if p.name.endswith(".weights.json"):
            continue
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        row = {"id": m.get("id", p.stem), "manifest": m, "installed": False, "problems": []}
        missing = [k for k in _REQUIRED if k not in m]
        if missing:
            row["problems"].append("manifest 缺欄位：" + "、".join(missing))
            rows.append(row)
            continue
        if m["task"] != "detect":
            row["problems"].append(f"任務類型 {m['task']} 不支援")
        drv = drivers.get(m["runtime"])
        ok, why = drv.available() if drv else (False, f"沒有 {m['runtime']} driver")
        if not ok:
            row["problems"].append(why)
        path = (Path(model_dir) / m["file"]).resolve()
        if Path(model_dir).resolve() not in path.parents:
            row["problems"].append("模型檔路徑超出模型資料夾")
        elif not path.is_file():
            row["problems"].append("模型檔不存在（未下載）")
        elif sha256_file(path) != m["sha256"]:
            row["problems"].append("SHA256 不符")
        row["path"] = str(path)
        lat = m.get("latency_ms", {}).get(device)
        row["latency_ms"] = lat
        row["installed"] = not row["problems"]
        rows.append(row)
    return rows
