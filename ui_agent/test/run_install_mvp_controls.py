"""MVP 共用安裝器（ui_agent/mvp/install_mvp_into_ui.sh）控制測試。Claude 只跑一次，首次結果原樣保留。

python run_install_mvp_controls.py <未安裝的 UI 副本樣本> <全新的證據資料夾>
需要 Linux/bash、coreutils、GNU patch。不啟動模型、Qt、建置或任何服務。
每個情境都在證據資料夾裡複製一份樣本；需要竄改來源的情境另外複製一份 repo 子集，不動工作目錄。
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=False)
RESULTS = []
DOC = "GCS_開發交接與變更紀錄.md"
PLUGIN_FILES = ["AiAlerts/GcpAiAlertsCore.js", "AiAlerts/GcpAiAlertsPanel.qml",
                "AiMission/GcpMissionAiPanel.qml", "AiMission/GcpMissionCore.js"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root):
    return {str(p.relative_to(root)): digest(p)
            for p in sorted((root / "GCP").rglob("*")) if p.is_file()} | {DOC: digest(root / DOC)}


def fresh(name):
    root = OUT / name
    root.mkdir()
    shutil.copytree(FIXTURE / "GCP", root / "GCP", symlinks=True)
    shutil.copy2(FIXTURE / DOC, root / DOC)
    return root


def repo_copy(name):
    """ui_agent/ 與外掛來源資料夾的獨立副本，供竄改情境使用。"""
    dst = OUT / ("repo " + name)
    shutil.copytree(REPO / "ui_agent", dst / "ui_agent", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for rel in ("gcs_demo/qml", "gcs_demo/alerts/qml"):
        shutil.copytree(REPO / rel, dst / rel, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "test"))
    return dst


def installer(repo=REPO):
    return str(repo / "ui_agent/mvp/install_mvp_into_ui.sh")


def run(name, argv, expected_ok, env=None):
    proc = subprocess.run(argv, capture_output=True, env=env)
    (OUT / (name + ".stdout")).write_bytes(proc.stdout)
    (OUT / (name + ".stderr")).write_bytes(proc.stderr)
    (OUT / (name + ".exit.json")).write_text(json.dumps({"exit": proc.returncode}) + "\n")
    assert (proc.returncode == 0) == expected_ok, (name, proc.returncode)
    return proc


def case(name, fn):
    try:
        fn()
        RESULTS.append({"name": name, "ok": True})
    except Exception as exc:
        RESULTS.append({"name": name, "ok": False, "error": repr(exc)})
    (OUT / "results.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def no_state(root):
    assert not (root / ".mvp-install.lock").exists()
    assert not list(root.glob(".ui-agent-install*"))


def check_only():
    root = fresh("check only")
    before = snapshot(root)
    run("check", ["bash", installer(), "--check", str(root)], True)
    assert snapshot(root) == before
    for d in ("Agent", "AiAlerts", "AiMission", "MvpSlots"):
        assert not (root / "GCP" / d).exists()
    no_state(root)


def installed_registry(root):
    text = (root / "GCP/MvpSlots/GcpMvpInstalled.js").read_text(encoding="utf-8")
    line = [l for l in text.splitlines() if l.startswith("var files = ")]
    assert len(line) == 1
    return json.loads(line[0][len("var files = "):])


def full_install_and_repeat():
    root = fresh("full install")
    run("install", ["bash", installer(), str(root)], True)
    gcp = root / "GCP"
    agent_assets = [a for a in (REPO / "ui_agent/install_assets_v6.txt").read_text().splitlines() if a.strip()]
    assert len(agent_assets) == 16
    cmake = (gcp / "CMakeLists.txt").read_text(encoding="utf-8").splitlines()
    for a in agent_assets:
        assert digest(REPO / "ui_agent/qml" / a) == digest(gcp / "Agent" / a)
        assert cmake.count("        Agent/" + a) == 1
    src = {"AiAlerts": REPO / "gcs_demo/alerts/qml", "AiMission": REPO / "gcs_demo/qml"}
    for rel in PLUGIN_FILES:
        d, f = rel.split("/")
        assert digest(src[d] / f) == digest(gcp / rel)
        assert cmake.count("        " + rel) == 1
    assert cmake.count("        MvpSlots/GcpMvpInstalled.js") == 1
    assert installed_registry(root) == PLUGIN_FILES
    shell = (gcp / "GcpMainShell.qml").read_text(encoding="utf-8")
    assert 'import "MvpSlots/GcpMvpInstalled.js" as MvpInstalled' in shell
    assert 'source: active ? "AiAlerts/GcpAiAlertsPanel.qml" : ""' in shell and "alertManager: GcpAlertManager" in shell
    assert "readableViewport: root" in shell  # UI agent 仍在
    planner = (gcp / "GcpMissionPlannerPage.qml").read_text(encoding="utf-8")
    assert 'source: active ? "AiMission/GcpMissionAiPanel.qml" : ""' in planner and "missionController: root._missionController" in planner
    subnav = (gcp / "GcpTelemetrySubNav.qml").read_text(encoding="utf-8")
    assert "Vibration, MissionReport }" in subnav
    page = (gcp / "GcpTelemetryPage.qml").read_text(encoding="utf-8")
    assert 'source: "AiMission/GcpMissionReportView.qml"' in page
    receipt = (gcp / "MvpSlots/.install_mvp_receipt").read_text()
    assert receipt.startswith("mvp-install-v1\n") and "plugins=4 files" in receipt
    assert (gcp / "Agent/.install_v6_receipt").is_file()
    no_state(root)
    stages = list(root.glob(".mvp-install.*"))
    assert len(stages) == 1 and (stages[0] / "original-GCP").is_dir() and (stages[0] / "agent-stage").is_dir()
    before = snapshot(root)
    run("repeat", ["bash", installer(), str(root)], False)
    assert snapshot(root) == before


def skip_all_plugins():
    root = fresh("skip plugins")
    run("skip", ["bash", installer(), "--skip", "AiMission", "--skip", "AiAlerts", str(root)], True)
    assert installed_registry(root) == []
    assert not (root / "GCP/AiAlerts").exists() and not (root / "GCP/AiMission").exists()
    cmake = (root / "GCP/CMakeLists.txt").read_text(encoding="utf-8")
    assert "AiAlerts/" not in cmake.replace("inserts AiMission/AiAlerts entries", "")
    assert "MvpInstalled.has(" in (root / "GCP/GcpMainShell.qml").read_text(encoding="utf-8")
    no_state(root)


def unknown_skip_refused():
    root = fresh("unknown skip")
    before = snapshot(root)
    run("unknown-skip", ["bash", installer(), "--skip", "AiNothing", str(root)], False)
    assert snapshot(root) == before
    no_state(root)


def corrupt_plugin_refused():
    repo = repo_copy("corrupt plugin")
    p = repo / "gcs_demo/alerts/qml/GcpAiAlertsPanel.qml"
    p.write_bytes(p.read_bytes() + b"\n// tampered\n")
    root = fresh("corrupt plugin")
    before = snapshot(root)
    proc = run("corrupt-plugin", ["bash", installer(repo), str(root)], False)
    assert proc.returncode == 2 and b"LF checksum mismatch: GcpAiAlertsPanel.qml" in proc.stderr
    assert snapshot(root) == before
    no_state(root)


def corrupt_slot_patch_refused():
    repo = repo_copy("corrupt slot patch")
    p = repo / "ui_agent/mvp/patch/elan_gcp_mvp_slots.patch"
    p.write_bytes(p.read_bytes().replace(b"z: 90", b"z: 99", 1))
    root = fresh("corrupt slot patch")
    before = snapshot(root)
    proc = run("corrupt-slot-patch", ["bash", installer(repo), str(root)], False)
    assert proc.returncode == 2 and b"mvp/patch/elan_gcp_mvp_slots.patch" in proc.stderr
    assert snapshot(root) == before
    no_state(root)


def name_collision_refused():
    root = fresh("name collision")
    (root / "GCP/Controls/GcpMissionAiPanel.qml").write_text("import QtQuick\nItem {}\n")
    before = snapshot(root)
    proc = run("collision", ["bash", installer(), str(root)], False)
    assert proc.returncode == 2 and b"QML type clash" in proc.stderr
    assert snapshot(root) == before
    no_state(root)


def late_slot_failure():
    root = fresh("late slot failure")
    nav = root / "GCP/GcpTelemetrySubNav.qml"
    nav.write_bytes(nav.read_bytes().replace(b"LogViewer, Vibration }", b"LogViewer, Vibration, Extra }", 1))
    before = snapshot(root)
    proc = run("late-slot", ["bash", installer(), str(root)], False)
    assert proc.returncode == 3
    assert snapshot(root) == before and not (root / "GCP/Agent").exists()
    no_state(root)


def existing_lock_refused():
    root = fresh("existing lock")
    (root / ".mvp-install.lock").mkdir()
    before = snapshot(root)
    run("lock", ["bash", installer(), str(root)], False)
    assert snapshot(root) == before and (root / ".mvp-install.lock").is_dir()


def rename_failure(fail_at):
    # mv 呼叫順序：UI agent 安裝器 3 次、搬走它的預演 1 次，之後本安裝器 5=原 GCP、6=新 GCP、7=交接文件
    root = fresh("commit failure %d" % fail_at)
    before = snapshot(root)
    stub = OUT / ("bin%d" % fail_at)
    stub.mkdir()
    real_mv = shutil.which("mv")
    assert real_mv
    wrapper = stub / "mv"
    wrapper.write_text('#!/usr/bin/env bash\nset -eu\nn=0\n[[ ! -f "$MV_COUNT" ]] || read -r n < "$MV_COUNT"\nn=$((n+1))\nprintf "%s\\n" "$n" > "$MV_COUNT"\n[[ "$n" != "$MV_FAIL_AT" ]] || exit 79\nexec "$REAL_MV" "$@"\n')
    wrapper.chmod(0o755)
    env = dict(os.environ, PATH=str(stub) + os.pathsep + os.environ["PATH"],
               REAL_MV=real_mv, MV_COUNT=str(OUT / ("mv-count%d" % fail_at)), MV_FAIL_AT=str(fail_at))
    proc = run("commit-failure%d" % fail_at, ["bash", installer(), str(root)], False, env)
    assert proc.returncode == 79
    assert snapshot(root) == before and not (root / "GCP/Agent").exists()
    no_state(root)


for name, fn in [("check leaves target unchanged", check_only),
                 ("full install (agent + slots + 2 plugins) and repeat refusal", full_install_and_repeat),
                 ("skip both plugins keeps empty slots", skip_all_plugins),
                 ("unknown --skip refused", unknown_skip_refused),
                 ("corrupt plugin file refused", corrupt_plugin_refused),
                 ("corrupt slot patch refused", corrupt_slot_patch_refused),
                 ("plugin file name collision refused", name_collision_refused),
                 ("late slot patch failure leaves target unchanged", late_slot_failure),
                 ("existing lock preserved", existing_lock_refused),
                 ("new GCP rename failure restores original", lambda: rename_failure(6)),
                 ("handoff rename failure restores both originals", lambda: rename_failure(7))]:
    case(name, fn)
print(json.dumps({"controls": len(RESULTS), "passed": sum(r["ok"] for r in RESULTS),
                  "model_calls": 0, "qt_executed": False}))
sys.exit(0 if all(r["ok"] for r in RESULTS) else 2)
