"""離屏載入面板與報告子頁，對真的 gcs_demo.server 跑：規劃 → 設選配 → 套用 → 復原 → 模擬 → 報告。
用法：QT_QPA_PLATFORM=offscreen python run_offscreen.py OUT.json [api_base]"""
import json, sys, time
from pathlib import Path
from PySide6.QtCore import QUrl, QCoreApplication, QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtCore import QMetaObject, Q_ARG, Q_RETURN_ARG

app = QGuiApplication(sys.argv[:1])
eng = QQmlEngine()
comp = QQmlComponent(eng, QUrl.fromLocalFile(str(Path(__file__).with_name("MissionHarness.qml"))))
root = comp.create()
if root is None:
    print("\n".join(e.toString() for e in comp.errors())); sys.exit(2)
if len(sys.argv) > 2:
    root.setProperty("api", sys.argv[2])
from PySide6.QtCore import QObject
panel, rep = root.findChild(QObject, "aiPanel"), root.findChild(QObject, "aiReport")
log = []

def pump(sec):
    t = time.time() + sec
    while time.time() < t:
        app.processEvents(QEventLoop.AllEvents, 50); time.sleep(0.02)

def wait(cond, sec):
    t = time.time() + sec
    while time.time() < t and not cond():
        pump(0.1)
    return cond()

def has(v):
    return v is not None and not (hasattr(v, "isNull") and (v.isNull() or v.isUndefined()))

def tov(v):
    return v.toVariant() if hasattr(v, "toVariant") else v

def snap(step):
    r = panel.property("result")
    e = {"step": step, "online": panel.property("online"), "stage": panel.property("stage"), "status": panel.property("status"),
         "selected": panel.property("selected"), "undo": panel.property("undoStack").property("length").toInt(),
         "coords": tov(QMetaObject.invokeMethod(root, "coords", Q_RETURN_ARG("QVariant")))}
    log.append(e); print(json.dumps(e, ensure_ascii=False)); return e

panel.setProperty("open", True)
ok = wait(lambda: panel.property("online"), 10); snap("open")
def call(obj, name, *args):
    QMetaObject.invokeMethod(obj, name, *args)
call(panel, "makePlan", Q_ARG("QVariant", False))
wait(lambda: not panel.property("busy") and has(panel.property("result")), 120); snap("plan")
res = {"log": log}
try:
    call(panel, "applySelected"); wait(lambda: not panel.property("busy"), 120); snap("apply")
    call(panel, "undo"); wait(lambda: not panel.property("busy"), 120); snap("undo")
    call(panel, "simulate"); wait(lambda: not panel.property("busy"), 180); snap("simulate")
    if panel.property("stage") == "replan":
        call(panel, "continueFlight"); wait(lambda: not panel.property("busy"), 240); snap("continue")
    wait(lambda: has(rep.property("report")), 10)
    res["report_page"] = {"online": rep.property("online"), "has_report": has(rep.property("report")),
                          "mission": rep.property("missionName")}
    print(json.dumps(res["report_page"], ensure_ascii=False))
except Exception as exc:
    res["error"] = repr(exc)
with open(sys.argv[1], "x", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
