"""拼回 w_raw.txt → w.json；判定：每個排版成功的框都載入、ok、沒有 overflow；W2 重畫次數 ≤ 3；每案都有截圖；沒有 errors；
另外列出 qml 的 warning 行（含 TypeError、ReferenceError、Cannot assign）。用法：python3 collect_w.py w_raw.txt w.json"""
import json, os, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
parts, total = {}, None
for line in raw:
    k = line.find("QTV|")
    if k < 0: continue
    _, i, n, frag = line[k:].split("|", 3); parts[int(i)] = frag; total = int(n)
warn = [l for l in raw if "QTV|" not in l and any(x in l for x in ("TypeError", "ReferenceError", "Cannot assign", "is not a type", "Error:", "Unable to assign", "warning", "No such file", "not found", "failed to load", "Cannot open", "Cannot load"))]
if total is None or len(parts) != total: print(f"incomplete output: got {len(parts)} of {total}"); [print("  " + w) for w in warn[:40]]; sys.exit(2)
s = "".join(parts[i] for i in range(total)); open(sys.argv[2], "w", encoding="utf-8").write(s)
q = json.loads(s); fails = [f"error: {e}" for e in q.get("errors", [])]
for key, c in q["cases"].items():
    for it in c["items"]:
        if not it["loaded"]: fails.append(f"{key} {it['node_id']} {it['component_id']}: not loaded")
        elif not it["ok"]: fails.append(f"{key} {it['node_id']} {it['component_id']}: not ok ({it['error']})")
        elif it["overflow"]: fails.append(f"{key} {it['node_id']} {it['component_id']}: overflow")
        pr = it.get("probe") or {}
        for kind in ("outside", "overlap", "clipped"):
            for x in pr.get(kind, []): fails.append(f"{key} {it['node_id']} {it['component_id']}: text {kind}: {x}")
        if pr.get("elided"): print(f"  info {key} {it['node_id']} {it['component_id']} elided: {pr['elided']}")
        if it["paint"] is not None and it["paint"] > 3: fails.append(f"{key} {it['node_id']}: W2 painted {it['paint']} times")
    if not c["shot"].endswith(".png") or not os.path.exists(c["shot"]): fails.append(f"{key}: shot {c['shot']!r}")
    if key.startswith("long_") and c["layout_ok"] and key not in ("long_200",) and not any(i["component_id"] == "W4_DIAG" for i in c["items"]): fails.append(f"{key}: W4 missing (R1 ETA-NA)")
    for it in c["items"]:
        if it["component_id"] == "W4_DIAG" and it.get("cards"):
            want = {"base": "telemetryMetricBlue", "near": "telemetryMetricOrange", "long": "telemetryMetricOrange"}[key.split("_")[0]]
            eta = [x for x in it["cards"] if x.startswith("eta:")]
            if not eta or not eta[0].endswith(":" + want): fails.append(f"{key}: W4 eta accent {eta} want {want}")
    if key.startswith("base_") and c["layout_ok"] and key not in ("base_200",) and not any(i["component_id"] == "W4_DIAG" for i in c["items"]): fails.append(f"{key}: W4 missing")
    if key.startswith("near_") and c["layout_ok"] and key not in ("near_200",) and not any(i["component_id"] == "W4_DIAG" for i in c["items"]): fails.append(f"{key}: W4 missing")
    print(f"{key}: layout_ok {c['layout_ok']} {c['layout_error']}, items {[(i['component_id'], i['ok'], i['overflow'], i['paint'], i.get('cards')) for i in c['items']]}")
print("answer_lines_base", q.get("answer_lines_base"))
print(f"cases {len(q['cases'])}, fails {len(fails)}, qml warnings {len(warn)}")
for f in fails: print("  " + f)
for w in warn[:40]: print("  WARN " + w)
sys.exit(1 if fails or warn else 0)
