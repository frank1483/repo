"""所有 QML 檔（元件、骨架、驗證包）交付前的共同靜態檢查（host03、host05 兩次載入失敗後加）：
1. 屬性名稱不能大寫開頭（QML 規定）；2. 行內註解前有未配對的三元「?」（註解會吃掉後半段）；3. 括號配對；4. QML 的 JS 解析器把 ES3 舊保留字（long、int、char 等）當保留字，不可當識別字（host09 run1 載入失敗後加）。
沒有 Qt 的雲端只能做到這裡；筆電另跑 qmllint。用法：python3 test/check_qml_common.py"""
import os, re, sys
root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
# 已封存、首敗保留的舊驗證包（不修改）：只記錄，不算失敗
KNOWN = {"qt_trans_verify_host05", "qt_widgets_verify_bind01", "qt_viewer_verify_host09"}
RESERVED = ["abstract", "boolean", "byte", "char", "double", "final", "float", "goto", "int", "long", "native", "short", "synchronized", "throws", "transient", "volatile"]
RES_RE = re.compile(r"(?:\bfunction\s+\w*\s*\(([^)]*)\)|\b(?:var|let|const)\s+([^;=\n]+)|\bproperty\s+\S+\s+(\w+))")
fails, known, n = [], [], 0
for dp, _, fs in os.walk(root):
    if "/." in dp or "qt_stub" in dp: continue
    for f in fs:
        if not f.endswith(".qml"): continue
        p = os.path.join(dp, f); rel = os.path.relpath(p, root); src = open(p, encoding="utf-8").read(); n += 1
        bucket = known if rel.split(os.sep)[0] in KNOWN else fails
        for ln, line in enumerate(src.splitlines(), 1):
            m = re.match(r"\s*(?:readonly\s+|required\s+|default\s+)*property\s+\S+\s+(\w+)", line)
            if m and m.group(1)[0].isupper(): bucket.append(f"{rel}:{ln}: property name {m.group(1)!r} starts with upper case")
            k = line.find("//")
            if k > 0 and "://" not in line[max(0, k - 5):k + 2]:
                head = re.sub(r'"[^"]*"', '""', line[:k])
                lead = 1 if re.match(r"\s*(readonly\s+)?(property\s+\S+\s+)?[\w.]+\s*:", head) else 0
                if head.count("?") > head.count(":") - lead: bucket.append(f"{rel}:{ln}: inline comment inside ternary")
        for ln, line in enumerate(src.splitlines(), 1):
            body = re.sub(r'"(?:\\.|[^"\\])*"', '""', line.split("//")[0])
            for m in RES_RE.finditer(body):
                names = re.findall(r"[A-Za-z_]\w*", ",".join(g for g in m.groups() if g))
                for nm in names:
                    if nm in RESERVED: bucket.append(f"{rel}:{ln}: reserved word {nm!r} used as identifier")
        code = re.sub(r'"(?:\\.|[^"\\])*"', '""', re.sub(r"//[^\n]*", "", src))
        for a, b in ("{}", "()", "[]"):
            if code.count(a) != code.count(b): bucket.append(f"{rel}: unbalanced {a}{b} ({code.count(a)} vs {code.count(b)})")
print(f"check_qml_common: files {n}, fails {len(fails)}, known (archived) {len(known)}")
for x in known: print("  known " + x)
for x in fails: print("  " + x)
sys.exit(1 if fails else 0)
