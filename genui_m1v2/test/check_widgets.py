"""靜態檢查 W 元件（說明 v1.2 §3、允許清單 v2）：import 只能是 4 個模組＋本地 JS；不得出現會自己動或讀即時狀態的型別。"""
import os, re, sys
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "qml", "widgets")
ALLOWED = {"QtQuick", "QtQuick.Layouts", "QtQuick.Effects", "QGroundControl.GCP"}
FORBID = [r"\bTimer\s*\{", r"\b\w*Animation\s*\{", r"\bBehavior\s+on\b", r"\bAnimatedImage\b", r"\bGcpVehicleState\b", r"\bmultiVehicleManager\b",
          r"\bactiveVehicle\b", r"\bQtCharts\b", r"\bgrabToImage\b", r"\bShaderEffectSource\b", r"\bMouseArea\b", r"\bHoverHandler\b", r"\bXMLHttpRequest\b"]
fails = []
for f in sorted(os.listdir(d)):
    if not f.endswith(".qml"): continue
    src = open(os.path.join(d, f), encoding="utf-8").read()
    code = re.sub(r"//[^\n]*", "", src)
    for m in re.finditer(r"^\s*import\s+(\S+)", code, re.M):
        mod = m.group(1)
        if mod.startswith('"'):
            if not re.fullmatch(r'"\.\./Genui\w+\.js"', mod): fails.append(f"{f}: local import {mod}")
        elif mod not in ALLOWED: fails.append(f"{f}: import {mod}")
    for pat in FORBID:
        if re.search(pat, code): fails.append(f"{f}: forbidden {pat}")
    if "blurSource" in code and not re.search(r"blurSource:\s*null", code): fails.append(f"{f}: blurSource not null")
    if re.search(r"GcpPanel\s*\{", code) or code.lstrip().startswith("GcpPanel") or re.search(r"^GcpPanel", code, re.M):
        if not re.search(r"blurSource:\s*null", code): fails.append(f"{f}: GcpPanel without blurSource: null")
    print(f"{f}: checked")
print(f"check_widgets: fails {len(fails)}")
for x in fails: print("  " + x)
sys.exit(1 if fails else 0)
