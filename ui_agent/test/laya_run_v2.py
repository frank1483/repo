"""v2 (tag/device options, hashes every model file) of laya_run.py. Laya part of the UI semantic-scoring experiment: record Laya's option probabilities for every slot-tree node.

    python laya_run_v2.py prepare --nodes NODES.jsonl --model MODEL_DIR --tag TAG [--device cpu|cuda]   -> hash8
    python laya_run_v2.py run --nodes NODES.jsonl --model MODEL_DIR --tag TAG [--device ..] --out DIR --confirm HASH8

Offline only: HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE are set before laya is imported and the model is
loaded from a local directory. One run per new OUT dir, no retry.
Writes record.json in the same shape as live_semantic.cjs's logprob part, so eval_semantic_offline.js
scores it unchanged:
  TAG          every node scored (full tree)
  TAG-pruned   the logprob part's rule re-applied (top 2 kinds / children with p >= 0.05)
"""
import argparse
import hashlib
import json
import os
import sys
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["USE_TF"] = "0"

VERSION = "laya-semantic-2"
SETTINGS = { "expand_kinds": 2, "expand_children": 2, "min_p": 0.05, "laya": "0.4.26",
            "model_repo": "convaiinnovations/laya-multilingual",
            "model_revision": "1720e3e3357cfe1e281542e223f8273b0890ca34"}


def model_files(model):
    """Every file of the checkpoint (fine-tuned layouts differ from the base), skipping hub caches."""
    out = {}
    for r, ds, fs in os.walk(model):
        ds[:] = [d for d in ds if not d.startswith(".")]
        for f in fs:
            if not f.startswith(".") and f != "README.md":
                p = os.path.join(r, f)
                out[os.path.relpath(p, model).replace(os.sep, "/")] = sha_file(p)
    return dict(sorted(out.items()))


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def source(nodes, model, tag, device):
    return {"experiment": "ui-semantic-scoring-1", "part": "laya", "version": VERSION, "tag": tag, "device": device,
            "nodes_sha256": sha_file(nodes), "runner_sha256": sha_file(os.path.abspath(__file__)),
            "model_files": model_files(model), "settings": SETTINGS}


def source_hash(src):
    return hashlib.sha256(json.dumps(src, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def pruned(row_dists):
    """The logprob part's expansion rule applied to full-tree distributions."""
    st = SETTINGS
    top = lambda d, n: [k for k, p in sorted(d.items(), key=lambda x: -x[1]) if p >= st["min_p"]][:n]
    keep = {"": row_dists[""]}
    for k in top(row_dists[""], st["expand_kinds"]):
        if k == "NONE" or k not in row_dists:
            continue
        keep[k] = row_dists[k]
        if k in ("NAV", "LAYOUT"):
            for c in top(row_dists[k], st["expand_children"]):
                if k + "/" + c in row_dists:
                    keep[k + "/" + c] = row_dists[k + "/" + c]
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["prepare", "run"])
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out")
    ap.add_argument("--confirm")
    ap.add_argument("--tag", required=True, help="group name in the analysis, e.g. laya-ft-A1")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    a = ap.parse_args()
    TAG = a.tag
    src = source(a.nodes, a.model, TAG, a.device)
    h = source_hash(src)
    if a.mode == "prepare":
        print(json.dumps({"hash8": h[:8], "source_sha256": h, "source": src}, ensure_ascii=False, indent=1))
        return 0
    if a.confirm != h[:8]:
        raise SystemExit("confirm hash8 mismatch; expected " + h[:8])
    if not a.out or os.path.exists(a.out):
        raise SystemExit("--out must be a new directory")
    os.makedirs(a.out)
    with open(os.path.join(a.out, "source.json"), "w", encoding="utf-8") as f:
        json.dump(dict(src, source_sha256=h), f, ensure_ascii=False, indent=1)
    rows = [json.loads(l) for l in open(a.nodes, encoding="utf-8") if l.strip()]
    rec = {"source_sha256": h, "part": "logprob", "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    full = {"tag": TAG, "ok": False, "dists": {}, "calls": 0}
    rec["logprob_models"] = [full]
    raw = open(os.path.join(a.out, "raw_calls.jsonl"), "w", encoding="utf-8")
    try:
        import torch
        import laya
        torch.manual_seed(0)
        t0 = time.time()
        agent = laya.load(os.path.abspath(a.model), device=a.device)
        rec["load_s"] = round(time.time() - t0, 2)
        rec["versions"] = {"torch": torch.__version__, "laya": getattr(laya, "__version__", "?"), "python": sys.version.split()[0]}
        for n, row in enumerate(rows, 1):
            keys = list(row["questions"])
            qs = {"q%d" % i: row["questions"][k] for i, k in enumerate(keys)}
            t = time.time()
            res = agent.predict(row["state"], qs)
            ms = round((time.time() - t) * 1000)
            full["calls"] += 1
            raw.write(json.dumps({"n": n, "model": TAG, "id": row["id"], "latency_ms": ms, "questions": len(qs),
                                  "usage": res.get("usage")}, ensure_ascii=False) + "\n")
            row_d = dict(row["fixed"])
            for i, k in enumerate(keys):
                ans = res["answers"]["q%d" % i]
                probs = ans["probabilities"]
                if set(probs) != set(row["questions"][k]["criteria"]):
                    raise RuntimeError("option keys differ at %s|%s" % (row["id"], k))
                row_d[k] = {c: float(p) for c, p in probs.items()}
            for k, d in row_d.items():
                full["dists"][row["id"] + "|" + k] = d
        full["ok"] = True
    except Exception as e:  # noqa: BLE001 - recorded, not retried
        full["error"] = "%s: %s" % (type(e).__name__, e)
    raw.close()
    if full["ok"]:
        pr = {"tag": TAG + "-pruned", "ok": True, "dists": {}, "calls": 0, "note": "derived offline from " + TAG}
        for row in rows:
            rd = {k.split("|", 1)[1]: d for k, d in full["dists"].items() if k.split("|", 1)[0] == row["id"]}
            for k, d in pruned(rd).items():
                pr["dists"][row["id"] + "|" + k] = d
        rec["logprob_models"].append(pr)
    rec["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rec["calls"] = full["calls"]
    with open(os.path.join(a.out, "record.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    print(json.dumps({"calls": full["calls"], "ok": full["ok"], "error": full.get("error", ""), "load_s": rec.get("load_s")}))
    return 0 if full["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
