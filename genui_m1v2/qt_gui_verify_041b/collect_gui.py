"""拼回 gui_raw.txt 的 QTV 片段 → gui.json；判定：
1) Qt 端引擎輸出（ok/error/rects/dropped/compact）與 node 的 expect_gui.json 逐字相同；
2) 每個高度實際量到的元件位置大小與矩形相同、不超出、不重疊（mismatches 為空）；
3) 每個高度都有截圖檔、沒有 errors。
用法：python3 collect_gui.py gui_raw.txt expect_gui.json gui.json"""
import json, os, sys
parts, total = {}, None
for line in open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines():
    k = line.find("QTV|")
    if k < 0: continue
    _, i, n, frag = line[k:].split("|", 3); parts[int(i)] = frag; total = int(n)
if total is None or len(parts) != total: print(f"incomplete output: got {len(parts)} of {total}"); sys.exit(2)
s = "".join(parts[i] for i in range(total)); open(sys.argv[3], "w", encoding="utf-8").write(s)
q, e = json.loads(s), json.load(open(sys.argv[2], encoding="utf-8"))
fails = [f"error: {x}" for x in q.get("errors", [])]
for key, exp in e.items():
    c = q["cases"].get(key)
    if c is None: fails.append(f"{key}: missing"); continue
    for f in ("ok", "error", "rects", "dropped", "compact"):
        if c.get(f) != exp.get(f): fails.append(f"{key}.{f}: qt={c.get(f)!r} node={exp.get(f)!r}")
    for m in c.get("mismatches", []): fails.append(f"{key}: {m}")
    shot = c.get("shot", "")
    if not shot.endswith(".png") or not os.path.exists(shot): fails.append(f"{key}: shot {shot!r}")
    print(f"{key}: rects {len(c.get('rects') or [])}, dropped {c.get('dropped')}, compact {c.get('compact')}, shot {shot}")
print(f"cases {len(e)}, fails {len(fails)}")
for f in fails: print("  " + f)
sys.exit(1 if fails else 0)
