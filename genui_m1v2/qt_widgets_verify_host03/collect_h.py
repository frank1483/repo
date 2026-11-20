"""拼回 h_raw.txt → h.json；判定（使用者 11/20 16:40）：
每個框都載入、ok、沒有 overflow；目標框裡「要看得到的文字」都完整（沒被省略、沒裁切、在框內）；沒有文字超框、重疊、裁切；
正式字型：探測文字實際用的字型＝GcpTheme.font.chineseFamily；沒有 qml 錯誤或警告（含 Cannot load；host02 起每案先在資料未接上時建立元件，這段的 TypeError 也算）；
host03：W2 標籤上下順序與線條一致；目標框文字都用正式字型。host02：至少 1 案 W2（1280 寬）且「目前／差距」「保留」完整。
用法：python3 collect_h.py h_raw.txt h.json"""
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
f = q.get("fonts", {})
print("versions", q.get("bind"), q.get("layout")); print("fonts", f)
if f.get("probe_family") != f.get("chineseFamily"): fails.append(f"font fallback: probe uses {f.get('probe_family')!r}, theme wants {f.get('chineseFamily')!r}")
for key, c in q["cases"].items():
    tgt = [i for i in c["items"] if i["target"]]
    if not tgt: fails.append(f"{key}: target {c['comp']} not in layout")
    for it in c["items"]:
        if not it["loaded"]: fails.append(f"{key} {it['component_id']}: not loaded")
        elif not it["ok"]: fails.append(f"{key} {it['component_id']}: not ok ({it['error']})")
        elif it["overflow"]: fails.append(f"{key} {it['component_id']}: overflow")
        pr = it.get("probe") or {}
        for kind in ("outside", "overlap", "clipped", "missing", "order"):
            for x in pr.get(kind, []): fails.append(f"{key} {it['component_id']}: text {kind}: {x}")
        if pr.get("elided"): print(f"  info {key} {it['component_id']} elided: {pr['elided']}")
        if it["target"]:
            bad_f = [k for k in (pr.get("families") or {}) if k != f.get("chineseFamily")]
            if bad_f: fails.append(f"{key} {it['component_id']}: non-theme font {bad_f}")
        if it["target"]: print(f"  {key} target {it['component_id']} {it['w']:.0f}x{it['h']:.0f} families {pr.get('families')}")
    if not c["shot"].endswith(".png") or not os.path.exists(c["shot"]): fails.append(f"{key}: shot {c['shot']!r}")
    print(f"{key}: below_error {c['below_error']}, must {c['must']}, items {[(i['component_id'], round(i['w']), round(i['h']), i['ok'], i['overflow']) for i in c['items']]}")
if not any(c["comp"] == "W2_SERIES" for c in q["cases"].values()): fails.append("no W2 case at 1280")
print(f"cases {len(q['cases'])}, fails {len(fails)}, qml warnings {len(warn)}")
for x in fails: print("  " + x)
for w in warn[:40]: print("  WARN " + w)
sys.exit(1 if fails or warn else 0)
