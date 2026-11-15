"""逐案比對 JS 與 Python 的結果。數字容差：相對 1e-9 或絕對 1e-9。用法：compare.py js.json py.json"""
import json, math, sys

TOL = 1e-9


def same(a, b, path, diffs):
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        if a != b: diffs.append(f"{path}: js={a!r} py={b!r}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not math.isclose(a, b, rel_tol=TOL, abs_tol=TOL): diffs.append(f"{path}: js={a!r} py={b!r}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): diffs.append(f"{path}: length js={len(a)} py={len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)): same(x, y, f"{path}[{i}]", diffs)
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b: diffs.append(f"{path}.{k}: missing in {'js' if k not in a else 'py'}")
            else: same(a[k], b[k], f"{path}.{k}", diffs)
    else:
        diffs.append(f"{path}: type js={type(a).__name__} py={type(b).__name__}")


js, py = json.load(open(sys.argv[1], encoding="utf-8")), json.load(open(sys.argv[2], encoding="utf-8"))
bad, status = 0, {}
for cid in sorted(set(js) | set(py)):
    diffs = []
    if cid not in js or cid not in py: diffs.append("missing case")
    else: same(js[cid], py[cid], cid, diffs)
    if diffs:
        bad += 1; print("DIFF " + cid); [print("  " + d) for d in diffs[:6]]
    elif "status" in js[cid]:
        key = cid.rstrip("0123456789_nulempty")[:1] + ":" + js[cid]["status"]; status[key] = status.get(key, 0) + 1
print("status coverage: " + json.dumps(status, ensure_ascii=False, sort_keys=True))
print(f"cases {len(set(js) | set(py))} / differ {bad}")
sys.exit(1 if bad else 0)
