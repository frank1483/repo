"""host13：截圖底改成不透明白底；region() 先把 alpha 疊在白底上再算亮度與顏色；每張截圖另記 alpha 最小值（應為 255）；告警列對比只記錄。
host12：另驗可見文字看得到：QML 量的文字／底色對比 ≥ 3（< 4.5 另列）；截圖上每段文字範圍內要有明顯深淺差（不是單一底色）；
告警列在視窗開關前後（截圖像素平均色）不變。PNG 用 Python 內建 zlib 解，不需要另外安裝套件。
host11：另驗視窗背景與標題列不透明（alpha 1）、可見文字不和標題列重疊；長內容（huge）捲到最後 contentY > 0、最後一段完整可見。
拼回 v_raw.txt → v.json；判定（引文視窗說明 v1 §8，V1～V4 照建議）：
W5 在 96 高時只顯示「查看手冊引文（3 段）」（cards 0、hidden 3）；開啟後 3 段出處與全文都完整（沒省略、沒裁切），用正式字型；
捲到最後一段時最後一段的出處與全文都在可見範圍內；新回答、critical、返回鍵、按鈕都會關閉，紀錄順序與原因正確；
W5 在 220 高時是「還有 N 段」（來源 more）；全部放得下時不能開；沒有 qml 警告。用法：python3 collect_v.py v_raw.txt v.json"""
import json, re, sys, zlib, struct, os
def png(path):
    d = open(path, 'rb').read(); assert d[:8] == b'\x89PNG\r\n\x1a\n'; i = 8; idat = b''
    while i < len(d):
        n, = struct.unpack('>I', d[i:i+4]); t = d[i+4:i+8]; c = d[i+8:i+8+n]; i += 12 + n
        if t == b'IHDR': W, H, bd, ct = struct.unpack('>IIBB', c[:10])
        elif t == b'IDAT': idat += c
    assert bd == 8 and ct in (2, 6), (bd, ct); bpp = 4 if ct == 6 else 3; raw = zlib.decompress(idat); st = W * bpp; rows = []; prev = bytearray(st); k = 0
    for y in range(H):
        f = raw[k]; line = bytearray(raw[k+1:k+1+st]); k += 1 + st
        for x in range(st):
            a = line[x-bpp] if x >= bpp else 0; b = prev[x]; cc = prev[x-bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - cc; pa, pb, pc = abs(p - a), abs(p - b), abs(p - cc)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else cc)) & 255
        rows.append(bytes(line)); prev = line
    return W, H, bpp, rows
def region(img, x, y, w, h):
    W, H, bpp, rows = img; ls = []
    for yy in range(max(0, y), min(H, y + h)):
        r = rows[yy]
        for xx in range(max(0, x), min(W, x + w)):
            a = r[xx*bpp+3] if bpp == 4 else 255; p = tuple((r[xx*bpp+i] * a + 255 * (255 - a)) / 255 for i in range(3)); ls.append((0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2], p, a))
    return ls
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
want = ["open:view:rL:3", "close:new_answer:rL:3", "open:view:rL:3", "close:button:rL:3", "open:view:rL:3", "close:new_answer:rL:3", "open:view:rL:3", "close:critical:rL:3", "open:view:rL:3", "close:back:rL:3"]
got = st["close_back"]["log"]; need(got == want, f"log {got} want {want}")
wm = st["w5_more"]["w5"]; need(wm and wm["cards"] >= 1 and wm["hidden"] >= 1, f"w5_more {wm}")
need(st["open_more"]["log"][-1].startswith("open:more:rL:3") and st["close_button"]["log"][-1] == "close:button:rL:3" and not st["close_button"]["viewerOpen"], f"more/button {st['close_button']['log'][-2:]}")
need(q.get("open_refused_ret") is False and not st["open_refused"]["viewerOpen"], "open allowed when nothing hidden")
for k in ("open_view", "huge_open", "huge_scroll_end"):
    h = st[k].get("header") or {}; print(k, "header", h)
    need(h.get("bg_alpha") == 1 and h.get("header_alpha") == 1, f"{k}: not opaque {h}")
    need(not h.get("overlap_header"), f"{k}: text under header {h.get('overlap_header')}")
hh = st["huge_scroll_end"].get("header") or {}
need(hh.get("contentH", 0) > hh.get("viewH", 1e9) and hh.get("contentY", 0) > 0, f"huge: no real scroll {hh}")
ph = st["huge_scroll_end"].get("probe_huge_end", {}); need(not ph.get("missing") and not ph.get("truncated"), f"huge end {ph}")
pht = st["huge_open"].get("probe_huge_top", {}); need(not pht.get("truncated"), f"huge top truncated {pht}")
print("probe_huge_end", ph)
for k in ("w5_view_only", "open_view", "scroll_end", "w5_more", "huge_open", "huge_scroll_end"): need(st[k]["shot"].endswith(".png"), f"{k} shot {st[k]['shot']}")
base = os.path.dirname(os.path.abspath(sys.argv[1])); imgs = {}
def img(k):
    if k not in imgs: imgs[k] = png(os.path.join(base, st[k]["shot"]))
    return imgs[k]
for k in ("open_view", "huge_open", "huge_scroll_end"):
    cs = st[k].get("contrast") or []; need(len(cs) >= 3, f"{k}: contrast probe has {len(cs)} texts")
    low = [(c["text"], c["ratio"]) for c in cs if c["ratio"] < 3]; mid = [(c["text"], c["ratio"]) for c in cs if 3 <= c["ratio"] < 4.5]
    need(not low, f"{k}: contrast < 3 {low}"); print(k, "contrast min", min([c["ratio"] for c in cs] or [0]), "below 4.5:", mid)
    if not st[k]["shot"].endswith(".png"): continue
    flat = []
    for c in cs:
        if c["h"] < 4 or c["w"] < 4: continue
        ls = region(img(k), c["x"], c["y"], c["w"], c["h"]); v = [x[0] for x in ls]
        if not v or max(v) - min(v) < 40: flat.append((c["text"], round(max(v) - min(v), 1) if v else None))
    need(not flat, f"{k}: text area looks blank in screenshot {flat}"); print(k, "pixel check", len(cs), "texts, blank", flat)
def mean(k):
    ls = region(img(k), 0, 0, 1280, 56); n = len(ls); return tuple(round(sum(x[1][i] for x in ls) / n, 1) for i in range(3))
m0, m1 = mean("w5_view_only"), mean("open_view"); print("alert bar mean", m0, m1, st["open_view"].get("alert"))
need(all(abs(a - b) <= 2 for a, b in zip(m0, m1)), f"alert bar changed when viewer opened {m0} -> {m1}")
print("alert bar text contrast (fixture, info only)", (st["open_view"].get("alert") or {}).get("contrast"))
for k in ("w5_view_only", "open_view", "huge_open", "huge_scroll_end"):
    W, H, bpp, rows = img(k); amin = 255 if bpp == 3 else min(min(r[3::4]) for r in rows); print(k, "alpha min", amin)
    need(amin == 255, f"{k}: screenshot has transparent pixels (alpha min {amin})")
for x in q["steps"]: print(x["name"], x["viewerOpen"], x["w5"], x["log"][-1:] if x["log"] else [], x["shot"])
print(f"steps {len(q['steps'])}, fails {len(fails)}, qml warnings {len(warn)}")
for x in fails: print("  " + x)
for x in warn[:40]: print("  WARN " + x)
sys.exit(1 if fails or warn else 0)
