"""New part6 controls only; Claude executes once in a fresh evidence directory.
No old passing suite, model backend, device or network call is executed.
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
    with (OUT / name).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    import PySide6
    from PySide6.QtCore import QObject, QMetaObject, QSettings, Qt, QUrl, qVersion
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow  # noqa: F401

    workspace = OUT / "workspace"
    module = workspace / "QGroundControl" / "GCP"
    agent_dir = module / "Agent"
    fixture = agent_dir / "test" / "harness" / "ReadableOverlayV6Part6.qml"
    fixture.parent.mkdir(parents=True)
    pairs = [(p, agent_dir / "qml" / p.name) for p in (HERE.parent / "qml").iterdir() if p.is_file()]
    pairs += [(HERE / "harness" / "GcpTheme.qml", module / "GcpTheme.qml"),
              (HERE / "harness" / "ReadableOverlayV6Part6.qml", fixture)]
    inputs = []
    for source, target in pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        inputs.append({"source": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    inputs.append({"source": str(Path(__file__).resolve()), "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    (module / "qmldir").write_text(
        "module QGroundControl.GCP\nsingleton GcpAgentState 1.0 Agent/qml/GcpAgentState.qml\n"
        "singleton GcpTheme 1.0 GcpTheme.qml\n", encoding="utf-8")
    save("inputs.json", inputs)
    save("versions.json", {"python": sys.version, "pyside6": PySide6.__version__, "qt": qVersion()})
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(OUT / "settings"))
    app = QGuiApplication([sys.argv[0]])
    app.setOrganizationName("codex-part6-first-execution")
    app.setApplicationName("readable-geometry-destruction")
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(workspace))
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    engine.load(QUrl.fromLocalFile(str(fixture)))
    app.processEvents()
    if not engine.rootObjects():
        save("qml_warnings.json", warnings)
        raise RuntimeError("QML load failed")
    win = engine.rootObjects()[0]
    rows, geometries = [], []
    latest_geometry = {}

    def invoke(name):
        if not QMetaObject.invokeMethod(win, name, Qt.ConnectionType.DirectConnection):
            raise AssertionError("cannot invoke " + name)

    def need(ok, label):
        if not ok:
            raise AssertionError(label)

    def wait_for(predicate, label, timeout=4):
        deadline = time.monotonic() + timeout
        while True:
            app.processEvents()
            if predicate():
                return
            if time.monotonic() >= deadline:
                raise AssertionError("condition timeout: " + label)
            time.sleep(0.005)

    def check(name, work):
        try:
            work()
            rows.append({"name": name, "ok": True})
        except Exception:
            rows.append({"name": name, "ok": False, "traceback": traceback.format_exc()})
            save("results_first_failure.json", rows)
            save("geometry_first_failure.json", {"completed": geometries, "latest": latest_geometry})
            save("qml_warnings.json", warnings)
            win.grabWindow().save(str(OUT / "first_failure.png"))
            raise

    invoke("setup")

    def geometry(width):
        nonlocal latest_geometry
        win.setWidth(width)
        invoke("reset")

        def ready():
            nonlocal latest_geometry
            invoke("scrollConfirmationTop")
            invoke("measureConfirmation")
            top = json.loads(win.property("geometryJson") or "{}")
            invoke("scrollConfirmationBottom")
            invoke("measureConfirmation")
            latest_geometry = json.loads(win.property("geometryJson") or "{}")
            for name in ("agentConfirmYes", "agentConfirmNo", "agentSaveLayout", "agentHistoryHeading"):
                need(top.get("rects", {}).get(name) == latest_geometry.get("rects", {}).get(name), "fixed action moved " + name)
            latest_geometry["fixed_actions_unchanged_by_scroll"] = True
            return latest_geometry.get("ok") and latest_geometry.get("window", {}).get("w") == width

        wait_for(ready, "all fixed actions and final text line visible at " + str(width))
        need(latest_geometry["last_line_text"] == "對嗎？", "last text line changed")
        for expected in ("160", "80", "移動允許", "降尺寸不允許", "回所在畫面不允許", "尚未接模型修補"):
            need(expected in latest_geometry["text"], "confirmation missing " + expected)
        need(not win.property("active") and win.property("miniScale") == 1, "geometry applied action")
        need(win.property("undoCount") == 0, "geometry created undo")
        geometries.append(latest_geometry)
        need(win.grabWindow().save(str(OUT / ("confirmation_" + str(width) + ".png"))), "screenshot failed")

    for width in (900, 640):
        check("confirmation-fixed-actions-last-line-" + str(width), lambda width=width: geometry(width))
    save("geometry.json", geometries)
    invoke("reset")
    destroyed = []
    overlay = win.findChild(QObject, "part6Overlay")
    need(overlay is not None, "missing real QObject overlay")
    overlay.destroyed.connect(lambda *_: destroyed.append(True))

    def destruction():
        invoke("armDestruction")
        need(win.property("destructionArmed"), "not owned and in-flight before destroy")
        save("destruction_before.json", json.loads(win.property("destructionEvidence")))
        invoke("destroyArmed")
        wait_for(lambda: len(destroyed) == 1, "real QObject destroyed signal")
        need(not win.property("active") and win.property("miniScale") == 1, "destruction did not rollback")
        need(win.property("undoCount") == 0, "destruction committed undo")
        invoke("probeAfterDestruction")
        evidence = json.loads(win.property("destructionEvidence"))
        save("destruction_after.json", {**evidence, "qobject_destroyed_signals": len(destroyed)})
        need(win.property("schedulerDrained"), "baseline, cancellation or stale callback failed")

    check("paused-owned-mutation-real-destruction-and-stale-callback", destruction)
    save("results.json", {"total": len(rows), "cases": rows, "backend_calls": 0, "old_suites_executed": 0})
    save("qml_warnings.json", warnings)
    print(json.dumps({"total": len(rows), "failed": 0, "qml_warnings": len(warnings), "backend_calls": 0}))
    win.close()
    return 0 if len(rows) == 3 and not warnings else 1


try:
    status = main()
except Exception:
    save("first_failure.json", {"traceback": traceback.format_exc()})
    traceback.print_exc()
    status = 2
raise SystemExit(status)
