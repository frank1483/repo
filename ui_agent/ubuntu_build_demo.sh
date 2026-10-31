#!/usr/bin/env bash
# Fresh local copy -> verified install -> offline desktop build. Never starts UI.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
[[ $# -ge 1 && $# -le 2 ]] || { echo 'usage: bash ubuntu_build_demo.sh <source-UI> [fresh-copy-path]' >&2; exit 2; }
SRC="$(cd -- "$1" && pwd -P)"
for tool in realpath rsync cmake tee; do command -v "$tool" >/dev/null; done
DST="$(realpath -m -- "${2:-$SRC/../ELAN_GCP_ui_agent}")"
[[ "$DST" != / && "$DST" != "$SRC" && "$DST" != "$SRC/"* && "$SRC" != "$DST/"* && ! -e "$DST" && ! -L "$DST" ]] || { echo 'destination must be a fresh separate copy path' >&2; exit 2; }
[[ -f "$SRC/GCP/GcpMainShell.qml" && ! -e "$SRC/GCP/Agent" ]] || { echo 'source must be an uninstalled UI tree' >&2; exit 2; }
[[ -n "${QT_PREFIX:-}" && -d "$QT_PREFIX/lib/cmake/Qt6" ]] || { echo 'set QT_PREFIX to an existing local Qt desktop installation' >&2; exit 2; }
CM_VERSION="$(cmake --version)"
[[ "$CM_VERSION" =~ ^cmake\ version\ ([0-9]+)\.([0-9]+) ]] || exit 2
(( BASH_REMATCH[1] > 3 || (BASH_REMATCH[1] == 3 && BASH_REMATCH[2] >= 25) )) || { echo 'CMake >= 3.25 required' >&2; exit 2; }
JOBS="${JOBS:-4}"
[[ "$JOBS" =~ ^[1-9][0-9]?$ ]] && (( JOBS <= 64 )) || { echo 'JOBS must be an integer 1..64' >&2; exit 2; }
EXTRA=()
if [[ -n "${LIBEVENTS_SOURCE:-}" ]]; then
    [[ -f "$LIBEVENTS_SOURCE/libs/cpp/protocol/receive.h" ]] || { echo 'LIBEVENTS_SOURCE must be an existing local libevents tree' >&2; exit 2; }
    EXTRA+=("-DCPM_libevents_SOURCE=$LIBEVENTS_SOURCE")
fi
# No worktree metadata changes, clone, model download or deletion of old builds.
mkdir -- "$DST"
rsync -a --exclude='/.git' --exclude='/build*/' --exclude='/.ui-agent-*' -- "$SRC/" "$DST/"
bash "$HERE/install_into_ui.sh" "$DST"
cmake -S "$DST" -B "$DST/build-agent-v6" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug "-DCMAKE_PREFIX_PATH=$QT_PREFIX" \
    -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DCPM_LOCAL_PACKAGES_ONLY=ON "${EXTRA[@]}" \
    2>&1 | tee "$DST/configure_agent_v6.log"
cmake --build "$DST/build-agent-v6" --parallel "$JOBS" 2>&1 | tee "$DST/build_agent_v6.log"
printf 'Build command completed. Inspect the logs and actual executable path in %q. No application was launched.\n' "$DST/build-agent-v6"
