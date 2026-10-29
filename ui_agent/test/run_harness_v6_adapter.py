"""New real-Qt adapter controls only; Claude owns first execution.

Usage: python -I ui_agent/test/run_harness_v6_adapter.py <new-output-directory>
No model server, API, sockets, flight, or existing regression suite is started.
All evidence and the isolated QML/settings workspace are retained on failure.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback

HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else None
if OUT is None:
    raise SystemExit("exactly one fresh output directory required")
OUT.mkdir(parents=True, exist_ok=False)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["XDG_CONFIG_HOME"] = str(OUT / "settings")
os.environ["XDG_CACHE_HOME"] = str(OUT / "cache")
os.environ["XDG_DATA_HOME"] = str(OUT / "data")


def save(name, data):
    with (OUT / name).open("x", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main():
    import PySide6
    from PySide6.QtCore import QObject, QMetaObject, Qt, QUrl, Slot, qVersion, QSettings
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: F401

    class StackOrder(QObject):
        @Slot(QObject, QObject)
        def stackAfter(self, item, sibling):
            if not isinstance(item, QQuickItem) or not isinstance(sibling, QQuickItem):
                raise TypeError("real QQuickItems required")
            item.stackAfter(sibling)

    workspace = OUT / "workspace"
    module = workspace / "QGroundControl" / "GCP"
    agent = module / "Agent"
    fixtures = agent / "test" / "harness"
    fixtures.mkdir(parents=True)
    (agent / "qml").mkdir()
    inputs = []
    pairs = [(HERE.parent / "qml" / name, agent / "qml" / name) for name in (
        "GcpAgentState.qml", "GcpAgentCore.js", "GcpAgentSnapshot.js")]
    pairs += [(HERE / "harness" / "GcpTheme.qml", module / "GcpTheme.qml"),
              (HERE / "harness" / "AdapterV6.qml", fixtures / "AdapterV6.qml")]
    for source, target in pairs:
        shutil.copyfile(source, target)
        inputs.append({"source": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    inputs.append({"source": str(Path(__file__).resolve()),
                   "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    (module / "qmldir").write_text(
        "module QGroundControl.GCP\n"
        "singleton GcpAgentState 1.0 Agent/qml/GcpAgentState.qml\n"
        "singleton GcpTheme 1.0 GcpTheme.qml\n", encoding="utf-8")
    save("inputs.json", inputs)
    save("versions.json", {"python": sys.version, "pyside6": PySide6.__version__,
                           "qt": qVersion(), "platform": sys.platform,
                           "qpa": os.environ["QT_QPA_PLATFORM"],
                           "quick_backend": os.environ["QT_QUICK_BACKEND"]})
    # Keep settings under evidence, including on Windows. Never use user's real GCP store.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(OUT / "settings"))
    app = QGuiApplication([sys.argv[0]])
    app.setOrganizationName("codex-adapter-first-execution")
    app.setApplicationName("v6-batch5b1")
    order = StackOrder()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(workspace))
    engine.rootContext().setContextProperty("qtOrder", order)
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    engine.load(QUrl.fromLocalFile(str(fixtures / "AdapterV6.qml")))
    app.processEvents()
    if not engine.rootObjects():
        save("qml_warnings.json", warnings)
        raise RuntimeError("QML failed to load; preserve this first attempt")
    win = engine.rootObjects()[0]
    invoked = QMetaObject.invokeMethod(win, "run", Qt.ConnectionType.DirectConnection)
    app.processEvents()
    raw = win.property("resultJson")
    save("qml_warnings.json", warnings)
    if not invoked or not raw:
        raise RuntimeError("QML run did not finish; inspect warnings")
    results = json.loads(raw)
    save("results.json", results)
    # Freeze the intended case count; a truncated QML run cannot silently pass.
    total = results.get("total")
    failed = results.get("failed")
    print(json.dumps({"total": total, "passed": results.get("passed"), "failed": failed,
                      "qml_warnings": len(warnings), "evidence": str(OUT)}, ensure_ascii=False))
    win.close()
    return 0 if total == 20 and failed == 0 and not warnings else 1


try:
    status = main()
except Exception:
    save("first_failure.json", {"traceback": traceback.format_exc()})
    traceback.print_exc()
    status = 2
save("exit.json", {"exit": status, "research_scripts_run": False, "external_model_calls": 0})
raise SystemExit(status)
