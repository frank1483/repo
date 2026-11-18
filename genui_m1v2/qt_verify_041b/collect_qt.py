"""把 qml 的 console 輸出（QTV|i|n|片段）拼回 JSON，並與 node.json 逐鍵比對（容差 0）。
用法：python3 collect_qt.py qt_raw.txt node.json qt.json"""
import json, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
parts, total = {}, None
for line in raw:
    k = line.find("QTV|")
    if k < 0: continue
    _, i, n, frag = line[k:].split("|", 3)
    parts[int(i)] = frag; total = int(n)
if total is None or len(parts) != total: print(f"incomplete output: got {len(parts)} of {total}"); sys.exit(2)
s = "".join(parts[i] for i in range(total)); open(sys.argv[3], "w", encoding="utf-8").write(s)
q, n = json.loads(s), json.load(open(sys.argv[2], encoding="utf-8"))
if "run_error" in q: print("run_error", q["run_error"]); sys.exit(2)
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
print(f"gate {len(q['gate'])}, energy {len(q['energy'])}, flightlog {len(q['flightlog'])}, manual {len(q['manual'])}, diffs {len(diffs)}")
for d in diffs[:60]: print("  " + d)
sys.exit(1 if diffs else 0)
