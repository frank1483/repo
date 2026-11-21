"""host15：拼回 f2r_raw.txt 的 QTR 輸出 → f2r.json；和 expected_node.json 逐項比對 33 句意圖與 4 個情境（路由、狀態、原因、最大／平均原始值、回答句、元件），
再查截圖情境：W1 每一行（「未查」用縮短句）都找得到、沒被裁切；成功情境有 W2 框、mismatch 只有 W1；截圖 alpha 最小 255；沒有其他輸出行。
只用 Python 內建模組。用法：python3 collect_f2r.py f2r_raw.txt f2r.json"""
import json, sys, zlib, struct, os
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
    k = line.find("QTR|")
    if k < 0: continue
    _, i, n, frag = line[k:].split("|", 3); parts[int(i)] = frag; total = int(n)
warn = [l for l in raw if "QTR|" not in l and "QTR_END" not in l and not l.startswith("exit=") and l.strip()]
if total is None or len(parts) != total: print(f"incomplete output: got {len(parts)} of {total}"); [print("  " + w) for w in warn[:40]]; sys.exit(2)
s = "".join(parts[i] for i in range(total)); open(sys.argv[2], "w", encoding="utf-8").write(s)
q = json.loads(s); exp = json.load(open("expected_node.json", encoding="utf-8")); fails = [f"error: {e}" for e in q.get("errors", [])]
def need(c, m):
    if not c: fails.append(m)
need(q["versions"] == exp["versions"], f"versions {q['versions']} vs {exp['versions']}")
need(len(q["intents"]) == len(exp["intents"]) == 33, f"intents {len(q['intents'])}")
for a, b in zip(q["intents"], exp["intents"]):
    need(a == b, f"intent differs: qt {a} node {b}")
nf2 = sum(1 for x in q["intents"] if x["op"] == "DEVIATION"); print("intents", len(q["intents"]), "F2", nf2, "general", len(q["intents"]) - nf2)
need(nf2 == 11, f"F2 count {nf2}")
for a, b in zip(q["scenes"], exp["scenes"]):
    need(a == b, f"scene differs {a['name']}: qt {a} node {b}")
    print(a["name"], a["status"], a["reason"], a["max"], a["mean"], ",".join(a["comps"])); [print("   ", l) for l in a["lines"]]
base = os.path.dirname(os.path.abspath(sys.argv[1]))
for st in q["steps"]:
    p = st.get("probe") or {}; comps = [r[0] for r in st["rects"]]
    print(st["name"], "rects", st["rects"], "missing", p.get("missing"), "truncated", p.get("truncated"), "shot", st.get("shot"))
    need(not p.get("missing") and not p.get("truncated"), f"{st['name']}: W1 text missing/truncated {p}")
    need(comps == (["W1_FACT"] if st["name"] == "mismatch" else ["W1_FACT", "W2_SERIES"]), f"{st['name']}: comps {comps}")
    if st["name"] == "deferred": need(p.get("w1_lines", [None])[-1] == "未查：飛行時間。請另外再問一次。", f"deferred last W1 line {p.get('w1_lines')}")
    need(str(st.get("shot", "")).endswith(".png"), f"{st['name']} shot {st.get('shot')}")
    if str(st.get("shot", "")).endswith(".png"):
        W, H, bpp, rows = png(os.path.join(base, st["shot"])); amin = 255 if bpp == 3 else min(min(r[3::4]) for r in rows)
        need(amin == 255, f"{st['name']}: transparent pixels {amin}")
need(len(q["steps"]) == 4, f"steps {len(q['steps'])}")
print(f"steps {len(q['steps'])}, fails {len(fails)}, other output lines {len(warn)}")
for f in fails: print("  " + f)
for w in warn[:40]: print("  WARN " + w)
sys.exit(1 if fails or warn else 0)
