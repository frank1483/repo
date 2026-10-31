#!/usr/bin/env bash
# Install into a disposable UI COPY. Never run against the original worktree.
# --check prepares and retains a staged tree, without replacing target files.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
MODE=apply
if [[ "${1:-}" == --check ]]; then MODE=check; shift; fi
[[ $# == 1 ]] || { echo 'usage: bash install_into_ui.sh [--check] <UI-copy-root>' >&2; exit 2; }
UI="$(cd -- "$1" && pwd -P)"
DOC='GCS_開發交接與變更紀錄.md'
PATCHES=(elan_gcp_ui_agent.patch elan_gcp_home_modules.patch elan_gcp_text_scale.patch elan_gcp_joystick_grab.patch elan_gcp_agent_handoff_v6.patch)
# The manifest intentionally enumerates the complete source set: fail on drift.
mapfile -t ASSETS < "$HERE/install_assets_v6.txt"
[[ ${#ASSETS[@]} == 10 ]] || { echo 'expected exactly 10 Agent assets' >&2; exit 2; }
for tool in patch sha256sum find cp mv mkdir mktemp grep cut cat rmdir sed; do command -v "$tool" >/dev/null; done
[[ -f "$UI/GCP/GcpMainShell.qml" && -f "$UI/GCP/CMakeLists.txt" && -f "$UI/$DOC" ]] || { echo 'UI copy is incomplete' >&2; exit 2; }
[[ ! -L "$UI/GCP" && ! -L "$UI/$DOC" && ! -e "$UI/GCP/Agent" && ! -L "$UI/GCP/Agent" ]] || { echo 'symlink or prior Agent installation refused' >&2; exit 2; }
[[ -z "$(find "$UI/GCP" -type l -print -quit)" ]] || { echo 'GCP symlinks refused' >&2; exit 2; }
for asset in "${ASSETS[@]}"; do
    [[ "$asset" =~ ^GcpAgent[A-Za-z0-9]+\.(js|qml)$ && -f "$HERE/qml/$asset" && ! -L "$HERE/qml/$asset" ]] || { echo 'invalid asset path' >&2; exit 2; }
done
for patch_name in "${PATCHES[@]}"; do [[ -f "$HERE/patch/$patch_name" && ! -L "$HERE/patch/$patch_name" ]]; done
# Text-only manifest: SHA256 after CRLF -> LF, independent of Git checkout EOL.
payload_count=0
while read -r expected relative; do
    [[ "$expected" =~ ^[a-f0-9]{64}$ && "$relative" =~ ^[A-Za-z0-9_./-]+$ && "$relative" != /* && "$relative" != *..* && -f "$HERE/$relative" && ! -L "$HERE/$relative" ]] || exit 2
    actual="$(sed 's/\r$//' "$HERE/$relative" | sha256sum)"
    [[ "${actual%% *}" == "$expected" ]] || { echo "LF payload checksum mismatch: $relative" >&2; exit 2; }
    payload_count=$((payload_count+1))
done < "$HERE/install_payload_v6.sha256"
[[ "$payload_count" == 20 ]] || { echo 'expected 20 payload checksum entries' >&2; exit 2; }
LOCK="$UI/.ui-agent-install.lock"
mkdir -- "$LOCK" || { echo 'installer lock exists; inspect its owner, do not steal it' >&2; exit 2; }
STAGE=''
MOVED=0
DOC_DONE=0
finish() {
    local status=$?
    trap - EXIT HUP INT TERM
    set +e
    if (( status != 0 && MOVED )); then
        if [[ -e "$UI/GCP" ]]; then
            mv -T -- "$UI/GCP" "$STAGE/failed-GCP" || { echo "rollback could not preserve new GCP; see $STAGE" >&2; exit 90; }
        fi
        mv -T -- "$STAGE/original-GCP" "$UI/GCP" || { echo "rollback failed; original at $STAGE/original-GCP" >&2; exit 90; }
        if (( DOC_DONE )); then cp -p -- "$STAGE/original-handoff.md" "$UI/$DOC" || { echo "handoff rollback failed; original at $STAGE/original-handoff.md" >&2; exit 90; }; fi
    fi
    [[ -z "$STAGE" ]] || echo "staging/backup retained: $STAGE" >&2
    rmdir -- "$LOCK" || { echo "lock retained at $LOCK" >&2; exit 90; }
    exit "$status"
}
trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
STAGE="$(mktemp -d "$UI/.ui-agent-install.XXXXXX")"
cp -a -- "$UI/GCP" "$STAGE/GCP"
cp -p -- "$UI/$DOC" "$STAGE/$DOC"
cp -p -- "$UI/$DOC" "$STAGE/original-handoff.md"
# Normalize only the 43 declared patch targets in the disposable stage.
while IFS= read -r relative; do
    [[ "$relative" == GCP/* || "$relative" == "$DOC" ]] && [[ "$relative" != *..* && -f "$STAGE/$relative" && ! -L "$STAGE/$relative" ]] || exit 2
    sed 's/\r$//' "$STAGE/$relative" > "$STAGE/.normalized"
    cp -- "$STAGE/.normalized" "$STAGE/$relative"
done < "$HERE/install_targets_v6.txt"
# Apply sequentially to the SAME stage: later patches see earlier changes.
for patch_name in "${PATCHES[@]}"; do
    sed 's/\r$//' "$HERE/patch/$patch_name" > "$STAGE/$patch_name.lf"
    patch --batch --forward --fuzz=0 -p1 -d "$STAGE" < "$STAGE/$patch_name.lf" > "$STAGE/$patch_name.log" 2>&1 || { cat -- "$STAGE/$patch_name.log" >&2; exit 3; }
done
mkdir -- "$STAGE/GCP/Agent"
for asset in "${ASSETS[@]}"; do cp -- "$HERE/qml/$asset" "$STAGE/GCP/Agent/$asset"; done
for asset in "${ASSETS[@]}"; do
    [[ "$(sha256sum < "$HERE/qml/$asset")" == "$(sha256sum < "$STAGE/GCP/Agent/$asset")" ]] || exit 3
    [[ "$(grep -Fxc "        Agent/$asset" "$STAGE/GCP/CMakeLists.txt")" == 1 ]] || { echo "CMake asset count mismatch: $asset" >&2; exit 3; }
done
[[ "$(grep -Fxc 'set_source_files_properties(Agent/GcpAgentState.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)' "$STAGE/GCP/CMakeLists.txt")" == 1 ]] || exit 3
grep -Fq 'readableViewport: root' "$STAGE/GCP/GcpMainShell.qml"
grep -Fq 'readableGoalPolicy: root.agentReadableGoalPolicy' "$STAGE/GCP/GcpMainShell.qml"
printf 'ui-agent-v6-part7\npayload_manifest_sha256=%s\nassets=10\nreadability_policy_default=null\n' "$(sha256sum < "$HERE/install_payload_v6.sha256" | cut -d ' ' -f1)" > "$STAGE/GCP/Agent/.install_v6_receipt"
if [[ "$MODE" == check ]]; then echo 'CHECK: 5 patches staged; 10 assets verified; target GCP and handoff unchanged'; exit 0; fi
# Two renames are recoverable on ordinary failures/signals, not power-loss atomic.
# Preserve the original directory and handoff; never delete an old backup.
mv -T -- "$UI/GCP" "$STAGE/original-GCP"
MOVED=1
mv -T -- "$STAGE/GCP" "$UI/GCP"
DOC_DONE=1
mv -T -- "$STAGE/$DOC" "$UI/$DOC"
MOVED=0
echo 'Installed 10 Agent assets and 5 UI-copy patches. No build, model, service or application was started.'
