"""New disposable installer controls. Claude runs once; no model/Qt/research suite.

python run_install_v6_controls.py <uninstalled-UI-fixture> <new-evidence-directory>
Requires Linux/bash, coreutils and GNU patch. Every first failure is retained.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
FIXTURE = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=False)
RESULTS = []
DOC = "GCS_開發交接與變更紀錄.md"


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


def check_only():
    root = fresh("check only")
    before = snapshot(root)
    run("check", ["bash", str(HERE / "install_into_ui.sh"), "--check", str(root)], True)
    assert snapshot(root) == before
    assert not (root / "GCP/Agent").exists()
    assert not (root / ".ui-agent-install.lock").exists()


def install_and_refuse_repeat():
    root = fresh("install with spaces")
    run("install", ["bash", str(HERE / "install_into_ui.sh"), str(root)], True)
    assets = (HERE / "install_assets_v6.txt").read_text().splitlines()
    assets = [name.strip() for name in assets if name.strip()]
    payload_assets = [line.split("  ", 1)[1][4:]
                      for line in (HERE / "install_payload_v6.sha256").read_text().splitlines()
                      if line.split("  ", 1)[1].startswith("qml/")]
    assert assets and len(assets) == len(set(assets))
    assert len(assets) == len(payload_assets) and set(assets) == set(payload_assets)
    cmake = (root / "GCP/CMakeLists.txt").read_text()
    for name in assets:
        assert digest(HERE / "qml" / name) == digest(root / "GCP/Agent" / name)
        assert cmake.splitlines().count("        Agent/" + name) == 1
    shell = (root / "GCP/GcpMainShell.qml").read_text()
    assert "property var agentReadableGoalPolicy: null" in shell
    assert "readableViewport: root" in shell
    assert "readableGoalPolicy: root.agentReadableGoalPolicy" in shell
    assert "UI agent v6 part7" in (root / DOC).read_text(encoding="utf-8")
    stages = list(root.glob(".ui-agent-install.*"))
    assert len(stages) == 1 and (stages[0] / "original-GCP").is_dir()
    before = snapshot(root)
    run("repeat", ["bash", str(HERE / "install_into_ui.sh"), str(root)], False)
    assert snapshot(root) == before


def late_patch_failure():
    root = fresh("late patch failure")
    # The first patch can succeed in the stage; the later joystick patch must fail.
    joystick = root / "GCP/Flight/GcpVirtualJoystick.qml"
    joystick.write_text("// intentionally incompatible scratch fixture\n")
    before = snapshot(root)
    run("late-patch", ["bash", str(HERE / "install_into_ui.sh"), str(root)], False)
    assert snapshot(root) == before and not (root / "GCP/Agent").exists()
    assert not (root / ".ui-agent-install.lock").exists()
    assert list(root.glob(".ui-agent-install.*"))


def corrupt_payload():
    root = fresh("corrupt payload")
    package = OUT / "bad package"
    shutil.copytree(HERE, package)
    with (package / "qml/GcpAgentLoop.js").open("a") as f:
        f.write("\n// tampered scratch payload\n")
    before = snapshot(root)
    run("corrupt", ["bash", str(package / "install_into_ui.sh"), str(root)], False)
    assert snapshot(root) == before and not (root / "GCP/Agent").exists()


def symlink_refused():
    root = fresh("symlink")
    original = root / "GCP/GcpMainShell.qml"
    real = OUT / "linked-shell.qml"
    shutil.copy2(original, real)
    original.unlink()
    original.symlink_to(real)
    before = digest(real)
    run("symlink", ["bash", str(HERE / "install_into_ui.sh"), str(root)], False)
    assert digest(real) == before and not (root / "GCP/Agent").exists()


def existing_lock_refused():
    root = fresh("existing lock")
    lock = root / ".ui-agent-install.lock"
    lock.mkdir()
    (lock / "owner").write_text("fixture-owner\n")
    before = snapshot(root)
    run("lock", ["bash", str(HERE / "install_into_ui.sh"), str(root)], False)
    assert snapshot(root) == before and (lock / "owner").read_text() == "fixture-owner\n"


def rename_failure(fail_at):
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
    proc = run("commit-failure%d" % fail_at, ["bash", str(HERE / "install_into_ui.sh"), str(root)], False, env)
    assert proc.returncode == 79
    assert snapshot(root) == before and not (root / "GCP/Agent").exists()
    assert not (root / ".ui-agent-install.lock").exists()


for name, fn in [("check leaves target unchanged", check_only),
                 ("complete install and repeat refusal", install_and_refuse_repeat),
                 ("late patch failure leaves target unchanged", late_patch_failure),
                 ("corrupt payload refused", corrupt_payload),
                 ("symlink refused", symlink_refused),
                 ("existing lock preserved", existing_lock_refused),
                 ("second rename failure restores original", lambda: rename_failure(2)),
                 ("handoff rename failure restores both originals", lambda: rename_failure(3))]:
    case(name, fn)
print(json.dumps({"controls": len(RESULTS), "passed": sum(r["ok"] for r in RESULTS),
                  "model_calls": 0, "qt_executed": False}))
sys.exit(0 if all(r["ok"] for r in RESULTS) else 2)
