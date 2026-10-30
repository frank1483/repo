"""First real-Qt Overlay/owned-Loop controls; Claude runs once on a fresh output directory.
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
    from PySide6.QtCore import QObject, QMetaObject, QSettings, Qt, QUrl, qVersion
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
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
    save("versions.json", {"python": sys.version, "pyside6": PySide6.__version__, "qt": qVersion()})
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(OUT / "settings"))
    app = QGuiApplication([sys.argv[0]])
    app.setOrganizationName("codex-readable-first-execution")
    app.setApplicationName("v6-part5-readable")
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

    def card():
        label = win.findChild(QObject, "agentConfirmationText")
        panel = win.findChild(QObject, "agentConfirmationCard")
        wait_for(lambda: label is not None and panel is not None and panel.property("visible"), "card visible")
        text = label.property("text")
        for expected in ("160", "80", "移動允許", "降尺寸不允許", "回所在畫面不允許", "尚未接模型修補"):
            need(expected in text, "actual Text missing " + expected)
        need(not win.property("active") and win.property("miniScale") == 1, "card changed layout")
        win.grabWindow().save(str(OUT / "confirmation.png"))

    check("actual-card-text-and-no-execution", card)
    check("No-does-not-apply", lambda: (invoke("reject"), need(win.property("miniScale") == 1 and not win.property("active"), "No applied")))
    invoke("reset")
    check("stale-container-blocks-Yes", lambda: (invoke("stale"), need(win.property("miniScale") == 1 and not win.property("active"), "stale applied")))
    invoke("reset")

    def success():
        invoke("accept")
        cancel_button = win.findChild(QObject, "agentCancelModel")
        need(cancel_button is not None and cancel_button.property("visible"), "cancel button hidden during Loop")
        wait_for(lambda: win.property("idle") and win.property("undoCount") == 1, "verified single atomic undo entry")
        need(win.property("miniScale") > 1, "mini did not grow")

    check("real-State-Loop-verified-commit", success)
    for method in ("cancel", "closePending"):
        invoke("reset")
        check(method + "-rolls-back-owned-group", lambda method=method: (
            invoke(method), wait_for(lambda: not win.property("active") and win.property("miniScale") == 1, method),
            need(win.property("undoCount") == 0, "cancel created undo")))
    invoke("reset")
    check("foreign-token-preserved", lambda: (invoke("foreignCase"), need(win.property("foreignOwned"), "foreign group was changed"), invoke("cleanForeign")))
    invoke("reset")
    check("destruction-rolls-back-owned-group", lambda: (
        invoke("destroyPending"), wait_for(lambda: not win.property("active") and win.property("miniScale") == 1, "destruction")))
    save("results.json", {"total": len(rows), "cases": rows, "backend_calls": 0})
    save("qml_warnings.json", warnings)
    print(json.dumps({"total": len(rows), "failed": 0, "qml_warnings": len(warnings), "backend_calls": 0}))
    win.close()
    return 0 if len(rows) == 8 and not warnings else 1


try:
    status = main()
except Exception:
    save("first_failure.json", {"traceback": traceback.format_exc()})
    traceback.print_exc()
    status = 2
raise SystemExit(status)
