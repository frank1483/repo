"""Fine-tune Laya multilingual on the UI slot data (run on the lab server by the user).

    python laya_train.py --data DATA_DIR --model BASE_MODEL_DIR --out OUT_DIR [--run A|B] [--device cuda]

DATA_DIR holds train.jsonl / val.jsonl / report.json from laya_build_train.cjs.
Runs (pick one per OUT_DIR; one run per new directory, no resume):
  A  head only (freeze_encoder=True)  - cheap, first try
  B  full fine-tune                   - only if A is not enough
Both: loss soft-ce, option order shuffled every epoch (fights position bias), val.jsonl as eval.
Writes OUT_DIR/model/ (loads with laya.load), OUT_DIR/summary.json, OUT_DIR/train_log.txt.
The held-out dev/test sentences are NOT in DATA_DIR (laya_build_train.cjs rejects them); the final
comparison is done afterwards with laya_run_v2.py + eval_semantic_offline.js, exactly like the base model.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import time

os.environ.setdefault("USE_TF", "0")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

VERSION = "laya-train-1"
RUNS = {
    "A": {"freeze_encoder": True, "epochs": 4, "head_lr": 1e-4, "encoder_lr": 2.5e-5},
    "B": {"freeze_encoder": False, "epochs": 3, "head_lr": 1e-4, "encoder_lr": 2.5e-5},
}
COMMON = {"loss": "soft-ce", "micro_batch": 16, "grad_accum": 4, "shuffle_options": ("choice",), "seed": 0}


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Tee(io.TextIOBase):
    def __init__(self, *s):
        self.s = s

    def write(self, x):
        for s in self.s:
            s.write(x)
            s.flush()
        return len(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run", choices=sorted(RUNS), default="A")
    ap.add_argument("--device", default="auto")
    a = ap.parse_args()
    if os.path.exists(a.out):
        raise SystemExit("--out exists; one run per new directory")
    os.makedirs(a.out)
    train, val = os.path.join(a.data, "train.jsonl"), os.path.join(a.data, "val.jsonl")
    import torch
    import laya
    from laya.train import TrainConfig, finetune
    cfg = dict(COMMON, **RUNS[a.run])
    summary = {"version": VERSION, "run": a.run, "config": {k: list(v) if isinstance(v, tuple) else v for k, v in cfg.items()},
               "data": {f: sha_file(os.path.join(a.data, f)) for f in ("train.jsonl", "val.jsonl", "report.json")},
               "base_model": {f: sha_file(os.path.join(a.model, f)) for f in ("model.safetensors", "rl_agent_config.json")},
               "versions": {"torch": torch.__version__, "laya": getattr(laya, "__version__", "?"), "python": sys.version.split()[0],
                            "cuda": torch.cuda.is_available() and torch.cuda.get_device_name(0)},
               "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    log = open(os.path.join(a.out, "train_log.txt"), "w", encoding="utf-8")
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
            result = finetune(train, os.path.abspath(a.model), os.path.join(a.out, "model"),
                              config=TrainConfig(eval_data=val, **cfg), device=a.device)
        summary["ok"] = True
        summary["result"] = json.loads(json.dumps(result, default=str))
    except Exception as e:  # noqa: BLE001 - recorded, not retried
        summary["ok"] = False
        summary["error"] = "%s: %s" % (type(e).__name__, e)
    log.close()
    summary["minutes"] = round((time.time() - t0) / 60, 1)
    summary["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if summary["ok"]:
        md = os.path.join(a.out, "model")
        summary["model_files"] = {os.path.relpath(os.path.join(r, f), md).replace(os.sep, "/"): sha_file(os.path.join(r, f))
                                  for r, _, fs in os.walk(md) for f in fs}
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": summary["ok"], "error": summary.get("error", ""), "minutes": summary["minutes"]}))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
