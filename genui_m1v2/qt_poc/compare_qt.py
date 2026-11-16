"""逐鍵比對 qt.json 與 node.json（qt_version 除外）。數字容差 0（要求逐位相同）。"""
import json, sys
q, n = json.load(open(sys.argv[1], encoding="utf-8")), json.load(open(sys.argv[2], encoding="utf-8"))
print("qt_version", q.pop("qt_version", None))
if "load_errors" in q or "run_error" in q: print(json.dumps(q, ensure_ascii=False)); sys.exit(2)
diffs = []
def walk(a, b, p):
    if type(a) is not type(b): diffs.append(f"{p}: type qt={type(a).__name__} node={type(b).__name__}"); return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b: diffs.append(f"{p}.{k}: missing in {'qt' if k not in a else 'node'}")
            else: walk(a[k], b[k], p + "." + k)
    elif isinstance(a, list):
        if len(a) != len(b): diffs.append(f"{p}: len qt={len(a)} node={len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)): walk(x, y, f"{p}[{i}]")
    elif a != b: diffs.append(f"{p}: qt={a!r} node={b!r}")
walk(q, n, "")
print("caps(qt)", json.dumps(q.get("caps"), ensure_ascii=False))
print(f"gate inputs {len(q.get('gate', {}))}, energy cases {len(q.get('energy', {}))}, diffs {len(diffs)}")
for d in diffs[:40]: print("  " + d)
sys.exit(1 if diffs else 0)
