"""MVP 插槽 Qt 載入測試（PySide6 離屏）。Claude 只跑一次，首次結果原樣保留。

python -I run_harness_mvp_slots.py <已用 install_mvp_into_ui.sh 安裝的 UI 副本> <只裝插槽、--skip 全部外掛的 UI 副本> <全新證據資料夾>
只複製已安裝副本裡的 MvpSlots/、AiAlerts/、AiMission/ 到暫存資料夾，旁邊放 harness/MvpSlotsV1.qml（和插槽 patch 同寫法）。
不連任何真服務（apiBase 指到沒人聽的埠），不呼叫模型。
"""
import json, os, shutil, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem  # noqa: F401

HERE = Path(__file__).resolve().parent
FULL, EMPTY, OUT = (Path(a).resolve() for a in sys.argv[1:4])
OUT.mkdir(parents=True, exist_ok=False)
app = QGuiApplication([sys.argv[0]])
app.setOrganizationName("mvp-slots-%d" % os.getpid()); app.setApplicationName("h")
RESULTS = []


def pump(s):
    end = time.time() + s
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)


def load(ui_copy, label):
    work = Path(tempfile.mkdtemp(prefix="mvp_slots_", dir=OUT))
    for d in ("MvpSlots", "AiAlerts", "AiMission"):
        if (ui_copy / "GCP" / d).is_dir():
            shutil.copytree(ui_copy / "GCP" / d, work / d)
    shutil.copy(HERE / "harness/MvpSlotsV1.qml", work / "Main.qml")
    eng = QQmlApplicationEngine(); warnings = []
    eng.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    eng.load(QUrl.fromLocalFile(str(work / "Main.qml")))
    pump(1.0)
    (OUT / (label + "_warnings.json")).write_text(json.dumps(warnings, ensure_ascii=False, indent=1), encoding="utf-8")
    roots = eng.rootObjects()
    assert roots, ("load failed", warnings[:3])
    return eng, roots[0], warnings


def check(name, fn):
    try:
        fn(); RESULTS.append({"name": name, "ok": True})
    except Exception as exc:
        RESULTS.append({"name": name, "ok": False, "error": repr(exc)})


def slot(root, name):
    from PySide6.QtCore import QObject
    return root.findChild(QObject, name)


engines = []


def full():
    eng, root, warnings = load(FULL, "full"); engines.append(eng)
    a, m, r = slot(root, "alertsSlot"), slot(root, "missionSlot"), slot(root, "reportSlot")
    assert root.property("alertsStatus") == 1 and a.property("item") is not None, "alerts not Ready"
    assert root.property("missionStatus") == 1 and m.property("item") is not None, "mission not Ready"
    assert r.property("active") is False and r.property("item") is None, "report should be inactive"
    ai = a.property("item"); mi = m.property("item")
    assert ai.property("apiBase") == "http://127.0.0.1:65530", ai.property("apiBase")
    assert ai.property("alertManager") is not None, "alertManager not bound"
    assert ai.property("vehicleId") == 0
    root.setProperty("activeVehicle", root.property("fakeVehicle")); pump(0.2)
    assert ai.property("vehicleId") == 7, ai.property("vehicleId")
    assert mi.property("missionController") is not None, "missionController not bound"
    assert mi.property("activeVehicle") is not None, "activeVehicle binding"
    assert ai.property("x") >= 0 and ai.property("width") > 0
    bad = [w for w in warnings if "GcpAiAlerts" in w or "GcpMission" in w or "MvpSlots" in w or "Main.qml" in w]
    (OUT / "full_plugin_warnings.json").write_text(json.dumps(bad, ensure_ascii=False, indent=1), encoding="utf-8")


def empty():
    eng, root, warnings = load(EMPTY, "empty"); engines.append(eng)
    for n in ("alertsSlot", "missionSlot", "reportSlot"):
        s = slot(root, n)
        assert s.property("active") is False and s.property("item") is None, n
    assert not warnings, warnings[:3]


check("installed plugins load through slots and get bound properties", full)
check("no plugins: all slots inactive, no warnings", empty)
(OUT / "results.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"total": len(RESULTS), "failed": sum(not r["ok"] for r in RESULTS), "model_calls": 0}))
sys.exit(0 if all(r["ok"] for r in RESULTS) else 2)
