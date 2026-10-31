"""Part5b: only the repaired destruction control, in a fresh evidence directory.
No server, model API, sockets, old suite or actual GCP settings are used.
All waits end on a condition or deadline, and first failure evidence is retained.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
if len(sys.argv) != 2:
    raise SystemExit("one fresh evidence directory required")
OUT = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=False)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
for name, leaf in (("XDG_CONFIG_HOME", "settings"), ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data")):
    os.environ[name] = str(OUT / leaf)


def save(name, data):
    with (OUT / name).open("x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    import PySide6
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QMetaObject, QSettings, Qt, QUrl, qVersion
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QJSValue
    from PySide6.QtQuick import QQuickWindow  # noqa: F401

    workspace = OUT / "workspace"
    module = workspace / "QGroundControl" / "GCP"
    agent_dir = module / "Agent"
    fixture = agent_dir / "test" / "harness" / "ReadableOverlayV6.qml"
    fixture.parent.mkdir(parents=True)
    inputs = []
    pairs = [(p, agent_dir / "qml" / p.name) for p in (HERE.parent / "qml").iterdir() if p.is_file()]
    pairs += [(HERE / "harness" / "GcpTheme.qml", module / "GcpTheme.qml"),
              (HERE / "harness" / "ReadableOverlayV6.qml", fixture)]
    for source, target in pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        inputs.append({"source": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    inputs.append({"source": str(Path(__file__).resolve()), "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    (module / "qmldir").write_text(
        "module QGroundControl.GCP\nsingleton GcpAgentState 1.0 Agent/qml/GcpAgentState.qml\n"
        "singleton GcpTheme 1.0 GcpTheme.qml\n", encoding="utf-8")
    save("inputs.json", inputs)
    save("versions.json", {"python": sys.version, "pyside6": PySide6.__version__, "qt": qVersion(),
                           "wait_policy": "processEvents then sendPostedEvents(DeferredDelete), condition/deadline"})
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(OUT / "settings"))
    app = QGuiApplication([sys.argv[0]])
    app.setOrganizationName("codex-part5b-first-execution")
    app.setApplicationName("v6-part5b-destruction-only")
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(workspace))
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(r.toString() for r in rows))
    engine.load(QUrl.fromLocalFile(str(fixture)))
    app.processEvents()
    if not engine.rootObjects():
        save("qml_warnings.json", warnings)
        raise RuntimeError("QML load failed")
    win = engine.rootObjects()[0]
    rows = []

    def invoke(name):
        if not QMetaObject.invokeMethod(win, name, Qt.ConnectionType.DirectConnection):
            raise AssertionError("cannot invoke " + name)

    def wait_for(predicate, label, timeout=4):
        deadline = time.monotonic() + timeout
        while True:
            app.processEvents()
            # processEvents() alone does not deliver DeferredDelete in this loop.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            if predicate():
                return
            if time.monotonic() >= deadline:
                raise AssertionError("condition timeout: " + label)
            time.sleep(0.005)  # Event-loop yield only; elapsed time never means success.

    def check(name, work):
        try:
            work()
            rows.append({"name": name, "ok": True})
        except Exception:
            rows.append({"name": name, "ok": False, "traceback": traceback.format_exc()})
            save("results_first_failure.json", rows)
            save("qml_warnings.json", warnings)
            raise  # Preserve first failure; do not mask it by running more cases.

    def need(ok, label):
        if not ok:
            raise AssertionError(label)

    invoke("setup")
    invoke("reset")

    # The original eight-case suite remains archived and is not executed here.
    overlay_value = win.property("agent")
    overlay = overlay_value.toQObject() if isinstance(overlay_value, QJSValue) else overlay_value
    need(isinstance(overlay, QObject), "missing real part5 QObject overlay")
    destroyed = []
    overlay.destroyed.connect(lambda *_: destroyed.append(True))

    def destruction():
        need(not win.property("active") and win.property("miniScale") == 1,
             "part5 baseline not idle")
        need(win.property("undoCount") == 0, "part5 baseline undo not empty")
        invoke("destroyPending")
        before = {"active": win.property("active"), "mini_scale": win.property("miniScale"),
                  "undo_count": win.property("undoCount"), "qobject_destroyed_signals": len(destroyed)}
        save("destruction_before_pump.json", before)
        need(before["active"], "part5 destroy request did not leave an owned group pending")
        wait_for(lambda: len(destroyed) == 1, "part5 real QObject destroyed signal")
        wait_for(lambda: not win.property("active") and win.property("miniScale") == 1,
                 "part5 destruction rollback")
        after = {"active": win.property("active"), "mini_scale": win.property("miniScale"),
                 "undo_count": win.property("undoCount"), "qobject_destroyed_signals": len(destroyed)}
        save("destruction_after.json", after)
        need(after["undo_count"] == 0, "part5 destruction committed undo")

    check("part5b-real-destruction-rolls-back-owned-group", destruction)
    save("results.json", {"total": len(rows), "cases": rows, "backend_calls": 0,
                          "old_suites_executed": 0, "original_part5_cases_omitted": 7})
    save("qml_warnings.json", warnings)
    print(json.dumps({"total": len(rows), "failed": 0, "qml_warnings": len(warnings), "backend_calls": 0}))
    win.close()
    return 0 if len(rows) == 1 and not warnings else 1


try:
    status = main()
except Exception:
    save("first_failure.json", {"traceback": traceback.format_exc()})
    traceback.print_exc()
    status = 2
raise SystemExit(status)
