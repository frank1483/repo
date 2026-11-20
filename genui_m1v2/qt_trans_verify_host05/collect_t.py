"""拼回 t_raw.txt → t.json；判定（轉場說明 v1，T1～T3）：
邏輯：before 模糊 0；t60 約 0.5 且還沒換；t120 已換（swapCount 1）、模糊 1；t210 約 0.5；t300 回到 IDLE、模糊 0、套用解鎖；轉場中套用上鎖；
critical：立刻模糊 0、已換、解鎖；reduced：直接換、不上鎖、模糊 0、log 有 skip:reduced_motion。
畫面（只用標準函式庫解 PNG）：工作區清晰度（相鄰像素差的平均）t60 < 0.85×before、t120 < t60、t300 ≥ 0.9×ref_B、critical ≥ 0.9×ref_B；
告警列（上方 56 px）清晰度在 t60、t120、t210 與 before 相差不到 5%（不模糊）。沒有 qml 警告。用法：python3 collect_t.py t_raw.txt t.json"""
import json, os, re, struct, sys, zlib
def png(path):
    b = open(path, "rb").read(); assert b[:8] == b"\x89PNG\r\n\x1a\n"; i = 8; idat = b""; w = h = ct = bd = None
    while i < len(b):
        n, = struct.unpack(">I", b[i:i+4]); t = b[i+4:i+8]; d = b[i+8:i+8+n]; i += 12 + n
        if t == b"IHDR": w, h, bd, ct, _, _, il = struct.unpack(">IIBBBBB", d); assert bd == 8 and il == 0 and ct in (2, 6)
        elif t == b"IDAT": idat += d
        elif t == b"IEND": break
    bpp = 4 if ct == 6 else 3; raw = zlib.decompress(idat); stride = w * bpp; rows = []; prev = bytearray(stride); p = 0
    for y in range(h):
        f = raw[p]; line = bytearray(raw[p+1:p+1+stride]); p += 1 + stride
        for x in range(stride):
            a = line[x-bpp] if x >= bpp else 0; c = prev[x-bpp] if x >= bpp else 0; up = prev[x]
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + up) & 255
            elif f == 3: line[x] = (line[x] + ((a + up) >> 1)) & 255
            elif f == 4:
                pa, pb, pc = abs(up - c), abs(a - c), abs(a + up - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else (up if pb <= pc else c))) & 255
        rows.append(bytes(line)); prev = line
    return w, h, bpp, rows
def sharp(img, y0, y1):
    w, h, bpp, rows = img; s = 0; n = 0
    for y in range(max(0, y0), min(h, y1), 2):
        r = rows[y]
        for x in range(0, (w - 1) * bpp, bpp * 2):
            s += abs(r[x] - r[x + bpp]) + abs(r[x+1] - r[x+1+bpp]) + abs(r[x+2] - r[x+2+bpp]); n += 1
    return s / max(1, n)
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
parts, total = {}, None
for line in raw:
    k = line.find("QTV|")
    if k < 0: continue
    _, i, n, frag = line[k:].split("|", 3); parts[int(i)] = frag; total = int(n)
warn = [l for l in raw if "QTV|" not in l and (re.search(r"file://\S+:\d+", l) or any(x in l for x in ("Expected token", "SyntaxError", "TypeError", "ReferenceError", "Cannot assign", "is not a type", "Error:", "Unable to assign", "warning", "No such file", "not found", "failed to load", "Cannot open", "Cannot load", "not supported", "ShaderEffect", "MultiEffect", "rhi", "RHI")))]
if total is None or len(parts) != total: print(f"incomplete output: got {len(parts)} of {total}"); [print("  " + w) for w in warn[:40]]; sys.exit(2)
s = "".join(parts[i] for i in range(total)); open(sys.argv[2], "w", encoding="utf-8").write(s)
q = json.loads(s); fails = [f"error: {e}" for e in q.get("errors", [])]
st = {x["name"]: x for x in q["steps"]}
def need(c, msg):
    if not c: fails.append(msg)
for k in ("ref_B", "before", "t60", "t120", "t210", "t300", "critical", "reduced"): need(k in st, f"step {k} missing")
if not fails:
    need(st["before"]["blur"] == 0 and st["before"]["state"] == "IDLE", "before not idle")
    need(abs(st["t60"]["blur"] - 0.5) < 1e-6 and st["t60"]["swapCount"] == 0 and st["t60"]["applyLocked"], f"t60 {st['t60']}")
    need(st["t120"]["blur"] == 1 and st["t120"]["swapCount"] == 1 and st["t120"]["applyLocked"], f"t120 {st['t120']}")
    need(abs(st["t210"]["blur"] - 0.5) < 1e-6 and st["t210"]["swapCount"] == 1 and st["t210"]["applyLocked"], f"t210 {st['t210']}")
    need(st["t300"]["blur"] == 0 and st["t300"]["state"] == "IDLE" and not st["t300"]["applyLocked"] and st["t300"]["swapCount"] == 1, f"t300 {st['t300']}")
    need(st["t300"]["answer_first"] == st["ref_B"]["answer_first"], "t300 not showing B")
    need(st["critical"]["blur"] == 0 and st["critical"]["state"] == "IDLE" and st["critical"]["swapCount"] == 1 and not st["critical"]["applyLocked"] and "abort_critical" in st["critical"]["log"], f"critical {st['critical']}")
    need(st["reduced"]["blur"] == 0 and st["reduced"]["swapCount"] == 1 and not st["reduced"]["applyLocked"] and "skip:reduced_motion" in st["reduced"]["log"], f"reduced {st['reduced']}")
    m = {}
    for k in ("ref_B", "before", "t60", "t120", "t210", "t300", "critical"):
        f = st[k]["shot"]
        if not f.endswith(".png") or not os.path.exists(f): fails.append(f"{k}: shot {f!r}"); continue
        img = png(f); m[k] = {"ws": round(sharp(img, 56, img[1]), 3), "bar": round(sharp(img, 0, 56), 3)}
    print("sharpness", json.dumps(m, ensure_ascii=False))
    if len(m) == 7:
        need(m["t60"]["ws"] < 0.85 * m["before"]["ws"], "t60 workspace not blurred")
        need(m["t120"]["ws"] < m["t60"]["ws"], "t120 not blurrier than t60")
        need(m["t300"]["ws"] >= 0.9 * m["ref_B"]["ws"], "t300 not sharp again")
        need(m["critical"]["ws"] >= 0.9 * m["ref_B"]["ws"], "critical not sharp")
        for k in ("t60", "t120", "t210"): need(abs(m[k]["bar"] - m["before"]["bar"]) <= 0.05 * max(1e-9, m["before"]["bar"]), f"{k}: alert bar changed")
for x in q["steps"]: print(x["name"], x["state"], x["blur"], x["swapCount"], x["applyLocked"], x["log"], x["shot"])
print(f"steps {len(q['steps'])}, fails {len(fails)}, qml warnings {len(warn)}")
for x in fails: print("  " + x)
for w in warn[:40]: print("  WARN " + w)
sys.exit(1 if fails or warn else 0)
