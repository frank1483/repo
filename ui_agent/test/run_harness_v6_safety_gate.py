"""New safety gate Qt controls; first Qt execution belongs to Claude.
Usage: python -I ui_agent/test/run_harness_v6_safety_gate.py <fresh-evidence-directory>
Real Overlay/Core/State; local navigation spy. No network, model, device or research runner.
The parent watchdog preserves timeout/stdout/stderr and never retries a failed attempt.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
WORKER = len(sys.argv) == 3 and sys.argv[1] == "--worker"
if not WORKER and len(sys.argv) != 2:
    raise SystemExit("exactly one fresh evidence directory required")
OUT = Path(sys.argv[2] if WORKER else sys.argv[1]).resolve()


def save(name, value):
    with (OUT / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_QUICK_BACKEND"] = "software"
    for key, name in (("XDG_CONFIG_HOME", "settings"), ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data")):
        os.environ[key] = str(OUT / name)
    import PySide6
    from PySide6.QtCore import QObject, QMetaObject, Qt, QUrl, QSettings, qVersion
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: F401

    workspace = OUT / "workspace"
    module = workspace / "QGroundControl" / "GCP"
    agent = module / "Agent"
    fixtures = agent / "test" / "harness"
    fixtures.mkdir(parents=True)
    (agent / "qml").mkdir()
    # Includes theme JS + Host.js, following the repaired 6c5e5a4 harness list.
    qml_names = (
        "GcpAgentState.qml", "GcpAgentOverlay.qml", "GcpAgentThemeEditor.qml", "GcpAgentModule.qml",
        "GcpAgentCore.js", "GcpAgentSnapshot.js", "GcpAgentThemePalette.js", "GcpAgentThemeColorMath.js",
        "GcpAgentThemeHostPolicy.js", "GcpAgentHost.js", "GcpAgentLoop.js", "GcpAgentCatalog.js",
        "GcpAgentVerifier.js", "GcpAgentReadableSession.js", "GcpAgentStateMachine.js", "GcpSlotLoop.js")
    pairs = [(HERE.parent / "qml" / name, agent / "qml" / name) for name in qml_names]
    pairs += [(HERE / "harness" / "GcpTheme.qml", module / "GcpTheme.qml"),
              (HERE / "harness" / "SafetyGateV6.qml", fixtures / "SafetyGateV6.qml")]
    inputs = []
    for source, target in pairs:
        shutil.copyfile(source, target)
        inputs.append({"source": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    inputs.append({"source": str(Path(__file__).resolve()), "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    (module / "qmldir").write_text("module QGroundControl.GCP\nsingleton GcpAgentState 1.0 Agent/qml/GcpAgentState.qml\nsingleton GcpTheme 1.0 GcpTheme.qml\n", encoding="utf-8")
    save("inputs.json", inputs)
    save("versions.json", {"python": sys.version, "pyside6": PySide6.__version__, "qt": qVersion(),
                           "qpa": os.environ["QT_QPA_PLATFORM"], "quick_backend": os.environ["QT_QUICK_BACKEND"]})
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(OUT / "settings"))
    app = QGuiApplication([sys.argv[0]])
    app.setOrganizationName("codex-safety-gate-first-execution")
    app.setApplicationName("v6-0399")
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(workspace))
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(row.toString() for row in values))
    engine.load(QUrl.fromLocalFile(str(fixtures / "SafetyGateV6.qml")))
    app.processEvents()
    if not engine.rootObjects():
        save("qml_warnings.json", warnings)
        raise RuntimeError("QML failed to load; retain first attempt")
    win = engine.rootObjects()[0]
    invoked = QMetaObject.invokeMethod(win, "run", Qt.ConnectionType.DirectConnection)
    deadline = time.monotonic() + 5
    while invoked and not win.property("resultJson") and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    raw = win.property("resultJson")
    save("qml_warnings.json", warnings)
    if not invoked or not raw:
        raise RuntimeError("QML checks did not finish within five seconds")
    result = json.loads(raw)
    panel = win.findChild(QObject, "agentGateHistory")
    toggle = win.findChild(QObject, "agentGateHistoryToggle")
    result["gate_panel_loaded"] = panel is not None and toggle is not None
    result["gate_panel_count"] = panel.property("count") if panel is not None else None
    result["gate_panel_visible"] = bool(panel.property("visible")) if panel is not None else False
    save("results.json", result)
    print(json.dumps({"total": result.get("total"), "passed": result.get("passed"), "failed": result.get("failed"),
                      "gate_panel_loaded": result["gate_panel_loaded"], "warnings": len(warnings)}, ensure_ascii=False), flush=True)
    win.close()
    return 0 if (result.get("total") == 8 and result.get("failed") == 0 and not warnings and
                 result["gate_panel_loaded"] and result["gate_panel_visible"] and
                 result["gate_panel_count"] == result.get("gate_count") == 4) else 1


if not WORKER:
    OUT.mkdir(parents=True, exist_ok=False)
    try:
        child = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(OUT)],
                               capture_output=True, timeout=25)
        (OUT / "stdout.txt").write_bytes(child.stdout)
        (OUT / "stderr.txt").write_bytes(child.stderr)
        status = child.returncode
    except subprocess.TimeoutExpired as error:
        (OUT / "stdout.txt").write_bytes(error.stdout or b"")
        (OUT / "stderr.txt").write_bytes(error.stderr or b"")
        save("timeout.json", {"timeout_seconds": 25, "retried": False})
        status = 124
    save("exit.json", {"exit": status, "research_scripts_run": False, "external_model_calls": 0})
    print(json.dumps({"exit": status, "evidence": str(OUT)}, ensure_ascii=False))
    raise SystemExit(status)

try:
    status = main()
except Exception:
    save("first_failure.json", {"traceback": traceback.format_exc()})
    traceback.print_exc()
    status = 2
save("worker_exit.json", {"exit": status})
raise SystemExit(status)
