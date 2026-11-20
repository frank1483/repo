"""拼回 v_raw.txt → v.json；判定（引文視窗說明 v1 §8，V1～V4 照建議）：
W5 在 96 高時只顯示「查看手冊引文（3 段）」（cards 0、hidden 3）；開啟後 3 段出處與全文都完整（沒省略、沒裁切），用正式字型；
捲到最後一段時最後一段的出處與全文都在可見範圍內；新回答、critical、返回鍵、按鈕都會關閉，紀錄順序與原因正確；
W5 在 220 高時是「還有 N 段」（來源 more）；全部放得下時不能開；沒有 qml 警告。用法：python3 collect_v.py v_raw.txt v.json"""
import json, re, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
parts, total = {}, None
for line in raw:
    k = line.find("QTV|")
    if k < 0: continue
    _, i, n, frag = line[k:].split("|", 3); parts[int(i)] = frag; total = int(n)
warn = [l for l in raw if "QTV|" not in l and (re.search(r"file://\S+:\d+", l) or any(x in l for x in ("Expected token", "SyntaxError", "TypeError", "ReferenceError", "Cannot assign", "is not a type", "Error:", "Unable to assign", "warning", "No such file", "not found", "failed to load", "Cannot open", "Cannot load")))]
if total is None or len(parts) != total: print(f"incomplete output: got {len(parts)} of {total}"); [print("  " + w) for w in warn[:40]]; sys.exit(2)
s = "".join(parts[i] for i in range(total)); open(sys.argv[2], "w", encoding="utf-8").write(s)
q = json.loads(s); fails = [f"error: {e}" for e in q.get("errors", [])]; st = {x["name"]: x for x in q["steps"]}
def need(c, m):
    if not c: fails.append(m)
w = st["w5_view_only"]["w5"]; need(w and w["cards"] == 0 and w["n"] == 3 and w["hidden"] == 3, f"w5_view_only {w}")
need(q.get("open_view_ret") is True and st["open_view"]["viewerOpen"], "open_view failed")
pt = st["open_view"].get("probe_top", {}); need(not pt.get("truncated"), f"top truncated {pt.get('truncated')}")
pe = st["scroll_end"].get("probe_end", {}); need(not pe.get("missing") and not pe.get("truncated"), f"end {pe}")
print("probe_top", pt); print("probe_end", pe)
fam = set((pt.get("families") or {}).keys()) | set((pe.get("families") or {}).keys()); need(fam == {"Noto Sans TC"}, f"fonts {fam}")
log = st["open_more"]["log"] + []
want = ["open:view:rL:3", "close:new_answer:rL:3", "open:view:rL:3", "close:critical:rL:3", "open:view:rL:3", "close:back:rL:3"]
got = st["close_back"]["log"]; need(got == want, f"log {got} want {want}")
wm = st["w5_more"]["w5"]; need(wm and wm["cards"] >= 1 and wm["hidden"] >= 1, f"w5_more {wm}")
need(st["open_more"]["log"][-1].startswith("open:more:rL:3") and st["close_button"]["log"][-1] == "close:button:rL:3" and not st["close_button"]["viewerOpen"], f"more/button {st['close_button']['log'][-2:]}")
need(q.get("open_refused_ret") is False and not st["open_refused"]["viewerOpen"], "open allowed when nothing hidden")
for k in ("w5_view_only", "open_view", "scroll_end", "w5_more"): need(st[k]["shot"].endswith(".png"), f"{k} shot {st[k]['shot']}")
for x in q["steps"]: print(x["name"], x["viewerOpen"], x["w5"], x["log"][-1:] if x["log"] else [], x["shot"])
print(f"steps {len(q['steps'])}, fails {len(fails)}, qml warnings {len(warn)}")
for x in fails: print("  " + x)
for x in warn[:40]: print("  WARN " + x)
sys.exit(1 if fails or warn else 0)
