"""在 PySide6（QJSEngine／QQmlEngine）裡載入 m1v2 的 .pragma library JS，跑 scenarios.js，輸出 JSON。
用法：python run_qt.py input.json > qt.json"""
import json, os, sys
from PySide6.QtCore import QCoreApplication, QUrl, QMetaObject, qVersion
from PySide6.QtQml import QQmlEngine, QQmlComponent

app = QCoreApplication(sys.argv)
here = os.path.dirname(os.path.abspath(__file__))
eng = QQmlEngine()
comp = QQmlComponent(eng, QUrl.fromLocalFile(os.path.join(here, "poc.qml")))
obj = comp.create()
if obj is None:
    print(json.dumps({"qt_version": qVersion(), "load_errors": [e.toString() for e in comp.errors()]}, ensure_ascii=False)); sys.exit(2)
obj.setProperty("inputJson", open(sys.argv[1], encoding="utf-8").read())
QMetaObject.invokeMethod(obj, "run")
err = obj.property("error")
if err:
    print(json.dumps({"qt_version": qVersion(), "run_error": err}, ensure_ascii=False)); sys.exit(3)
out = json.loads(obj.property("outputJson")); out["qt_version"] = qVersion()
print(json.dumps(out, ensure_ascii=False))
