"""host14：拼回 f2_raw.txt 的 QTF 輸出 → f2.json，和 expected_js.json（雲端 node 輸出）逐位比對 14 個案例的 status／reason／max／mean／n_series，
另檢查回答句（最大值附時間、平均值、樣本不足走 T-CANNOT）與版本；有任何 qml 警告也算失敗。用法：python3 collect_f2.py f2_raw.txt f2.json"""
import json, re, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
parts, total = {}, None
for line in raw:
    k = line.find("QTF|")
    if k < 0: continue
    _, i, n, frag = line[k:].split("|", 3); parts[int(i)] = frag; total = int(n)
warn = [l for l in raw if "QTF|" not in l and "QTF_END" not in l and not l.startswith("exit=") and l.strip()]
if total is None or len(parts) != total: print(f"incomplete output: got {len(parts)} of {total}"); [print("  " + w) for w in warn[:40]]; sys.exit(2)
s = "".join(parts[i] for i in range(total)); open(sys.argv[2], "w", encoding="utf-8").write(s)
q = json.loads(s); exp = {x["name"]: x for x in json.load(open("expected_js.json", encoding="utf-8"))}; fails = []
for r in q["out"]:
    e = exp.get(r["name"])
    if e is None: fails.append(f"unknown case {r['name']}"); continue
    for k in ("status", "reason", "max", "mean", "n_series"):
        if r.get(k) != e.get(k): fails.append(f"{r['name']} {k}: qt {r.get(k)} node {e.get(k)}")
    print(r["name"], r["status"], r["max"], r["mean"], r["n_series"], r["reason"])
if len(q["out"]) != len(exp): fails.append(f"cases {len(q['out'])} vs {len(exp)}")
x = q["extra"]; print("sentences", x["sentences"]); print("cannot", x["cannot"]); print("versions", x["versions"])
if "該趟紀錄中偏離航線距離最大值是 11公尺（t=3 秒）" not in x["sentences"]: fails.append("max sentence")
if "該趟紀錄中偏離航線距離平均值是 11公尺" not in x["sentences"]: fails.append("mean sentence")
if "T-CANNOT|飛行紀錄樣本不足，無法估計" not in x["cannot"]: fails.append("T-CANNOT")
if not (x["versions"][0].startswith("tools-m1-0.5") and x["versions"][1].startswith("claims-m1-0.5")): fails.append(f"versions {x['versions']}")
print(f"cases {len(q['out'])}, bitwise diffs/fails {len(fails)}, other output lines {len(warn)}")
for f in fails: print("  " + f)
for w in warn[:40]: print("  WARN " + w)
sys.exit(1 if fails or warn else 0)
