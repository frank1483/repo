"""把一份結果（JS 或 Python）和 vectors_v3.json 的 expect 比對。expect 是部分欄位；數字容差 1e-6。
用法：python3 -I check_expect.py vectors_v3.json result.json  （結束碼 1 表示有不符）"""
import json, math, sys

V, R = json.load(open(sys.argv[1], encoding="utf-8")), json.load(open(sys.argv[2], encoding="utf-8"))
bad = n = 0


def eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(eq(x, y) for x, y in zip(a, b))
    return a == b


def sub(exp, got, path, out):
    for k, v in exp.items():
        if isinstance(v, dict):
            sub(v, (got or {}).get(k) or {}, path + "." + k, out)
        elif k not in (got or {}) or not eq(v, got[k]):
            out.append(f"{path}.{k}: want={v!r} got={(got or {}).get(k, '<missing>')!r}")


for group, cases in V["cases"].items():
    for c in cases:
        if "expect" not in c: continue
        n += 1
        got, exp, diffs = R.get(c["id"]), dict(c["expect"]), []
        if got is None: diffs.append("missing case")
        else:
            if "points_head" in exp:
                ph = exp.pop("points_head")
                if not eq(ph, got["points"][:len(ph)]): diffs.append(f"points_head want={ph} got={got['points'][:len(ph)]}")
            if "facts" in exp and group == "flightlog":
                fx = exp.pop("facts"); fm = {f[2]: f[3] for f in got["facts"]}
                for k, v in fx.items():
                    if not eq(v, fm.get(k)): diffs.append(f"facts.{k}: want={v} got={fm.get(k)}")
            if "hit_ids" in exp:
                hid = exp.pop("hit_ids")
                if [h[0] for h in got["hits"]] != hid: diffs.append(f"hit_ids want={hid} got={[h[0] for h in got['hits']]}")
            sub(exp, got, c["id"], diffs)
        if diffs:
            bad += 1; print("MISMATCH " + c["id"]); [print("  " + d) for d in diffs]
print(f"expect cases {n} / mismatch {bad}")
sys.exit(1 if bad else 0)
