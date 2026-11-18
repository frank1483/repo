"""check_expect 第 2 版（v3.1c 第十三節）：容差 1e-9；「缺欄」與 null 分開；覆寫不能刪除原斷言（覆寫要含原 expect 的每個鍵）；
空覆寫不算；新增 hit_set（只比集合）。用法：python3 -I check_expect_v2.py vectors.json result.json [overrides.json]"""
import json, math, sys

V, R = json.load(open(sys.argv[1], encoding="utf-8")), json.load(open(sys.argv[2], encoding="utf-8"))
OV = json.load(open(sys.argv[3], encoding="utf-8")) if len(sys.argv) > 3 else {}
TOL = 1e-9
MISSING = object()
bad = n = 0


def eq(a, b):
    if b is MISSING: return False
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=TOL, abs_tol=TOL)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(eq(x, y) for x, y in zip(a, b))
    return a == b


def sub(exp, got, path, out):
    for k, v in exp.items():
        g = got.get(k, MISSING) if isinstance(got, dict) else MISSING
        if isinstance(v, dict):
            if not isinstance(g, dict): out.append(f"{path}.{k}: want object got={'<missing>' if g is MISSING else repr(g)}")
            else: sub(v, g, path + "." + k, out)
        elif not eq(v, g):
            out.append(f"{path}.{k}: want={v!r} got={'<missing>' if g is MISSING else repr(g)}")


def keys(d, p=""):
    out = set()
    for k, v in d.items():
        out.add(p + k)
        if isinstance(v, dict): out |= keys(v, p + k + ".")
    return out


for group, cases in V["cases"].items():
    for c in cases:
        if "expect" not in c: continue
        exp = c["expect"]
        if c["id"] in OV:
            ov = OV[c["id"]]
            lost = keys(exp) - keys(ov)
            if not ov or lost:
                bad += 1; n += 1; print(f"OVERRIDE_INVALID {c['id']} (dropped {sorted(lost)})"); continue
            print("OVERRIDE " + c["id"]); exp = ov
        n += 1
        exp, got, diffs = json.loads(json.dumps(exp)), R.get(c["id"]), []
        if got is None: diffs.append("missing case")
        else:
            if "points" in exp and group == "flightlog":
                pts = exp.pop("points")
                if not eq(pts, got.get("points", MISSING)): diffs.append(f"points want={pts} got={got.get('points')}")
            if "points_head" in exp:
                ph = exp.pop("points_head")
                if not eq(ph, (got.get("points") or [])[:len(ph)]): diffs.append(f"points_head want={ph} got={(got.get('points') or [])[:len(ph)]}")
            if "facts" in exp and group == "flightlog":
                fx = exp.pop("facts"); fm = {f[2]: f[3] for f in got["facts"]}
                for k, v in fx.items():
                    if not eq(v, fm.get(k, MISSING)): diffs.append(f"facts.{k}: want={v} got={fm.get(k, '<missing>')}")
            if "hit_ids" in exp:
                hid = exp.pop("hit_ids")
                if [h[0] for h in got["hits"]] != hid: diffs.append(f"hit_ids want={hid} got={[h[0] for h in got['hits']]}")
            if "hit_set" in exp:
                hs = exp.pop("hit_set")
                if sorted(h[0] for h in got["hits"]) != sorted(hs): diffs.append(f"hit_set want={sorted(hs)} got={sorted(h[0] for h in got['hits'])}")
            sub(exp, got, c["id"], diffs)
        if diffs:
            bad += 1; print("MISMATCH " + c["id"]); [print("  " + d) for d in diffs]
print(f"expect cases {n} / mismatch {bad}")
sys.exit(1 if bad else 0)
