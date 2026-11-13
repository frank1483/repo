#!/usr/bin/env bash
# MVP 共用安裝器：把 UI agent、MVP 插槽與外掛包（AiAlerts、AiMission）裝進一份「全新」的正式 UI 副本。
# 只動副本，絕不對正式 UI 原始資料夾執行。任何一步失敗：副本維持原樣（或還原），三者都不裝。
#   bash install_mvp_into_ui.sh [--check] [--skip <外掛名>]... <UI 副本根目錄>
# --check：完整預演（含 UI agent 安裝、插槽 patch、外掛複製與 CMake 清單），保留預演目錄，不替換副本。
# --skip：不裝某個外掛（插槽仍在，只是不啟用）；UI agent 與插槽不能略過。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
AGENT_DIR="$(cd -- "$HERE/.." && pwd -P)"
REPO="$(cd -- "$HERE/../.." && pwd -P)"
MODE=apply
declare -A SKIP=()
while [[ $# -gt 1 ]]; do
    case "$1" in
        --check) MODE=check; shift ;;
        --skip) [[ $# -gt 2 ]] || { echo 'usage: --skip <name>' >&2; exit 2; }; SKIP["$2"]=1; shift 2 ;;
        *) break ;;
    esac
done
[[ $# == 1 && "$1" != --* ]] || { echo 'usage: bash install_mvp_into_ui.sh [--check] [--skip NAME]... <UI-copy-root>' >&2; exit 2; }
UI="$(cd -- "$1" && pwd -P)"
DOC='GCS_開發交接與變更紀錄.md'
SLOT_PATCH="$HERE/patch/elan_gcp_mvp_slots.patch"
TEMPLATE="$HERE/GcpMvpInstalled.js.in"
PLUGINS="$HERE/mvp_plugins_v1.txt"
CMAKE_MARKER='        # MVP plugin files (install_mvp_into_ui.sh inserts AiMission/AiAlerts entries below)'
for tool in bash patch sha256sum find cp mv mkdir mktemp grep cut cat rmdir sed awk basename; do command -v "$tool" >/dev/null; done

# ---- 1. 副本與安裝器自身檢查（還沒動任何東西） ----
[[ -f "$UI/GCP/GcpMainShell.qml" && -f "$UI/GCP/CMakeLists.txt" && -f "$UI/$DOC" ]] || { echo 'UI copy is incomplete' >&2; exit 2; }
[[ ! -L "$UI/GCP" && ! -L "$UI/$DOC" ]] || { echo 'symlinked UI copy refused' >&2; exit 2; }
[[ -z "$(find "$UI/GCP" -type l -print -quit)" ]] || { echo 'GCP symlinks refused' >&2; exit 2; }
for d in Agent AiAlerts AiMission MvpSlots; do
    [[ ! -e "$UI/GCP/$d" && ! -L "$UI/GCP/$d" ]] || { echo "prior installation refused: GCP/$d exists (use a fresh UI copy)" >&2; exit 2; }
done
[[ ! -e "$UI/.mvp-install.lock" && -z "$(find "$UI" -maxdepth 1 -name '.ui-agent-install*' -print -quit)" ]] || { echo 'prior installer state found; use a fresh UI copy' >&2; exit 2; }
# 安裝器自身檔案（LF 雜湊）
while read -r expected relative; do
    [[ "$expected" =~ ^[a-f0-9]{64}$ && "$relative" =~ ^[A-Za-z0-9_./-]+$ && "$relative" != *..* && -f "$HERE/$relative" && ! -L "$HERE/$relative" ]] || { echo "bad installer manifest line: $relative" >&2; exit 2; }
    actual="$(sed 's/\r$//' "$HERE/$relative" | sha256sum)"
    [[ "${actual%% *}" == "$expected" ]] || { echo "LF checksum mismatch: mvp/$relative" >&2; exit 2; }
done < "$HERE/install_mvp_payload_v1.sha256"
[[ "$(grep -c . "$HERE/install_mvp_payload_v1.sha256")" == 4 ]] || { echo 'expected 4 installer checksum entries' >&2; exit 2; }

# 外掛包：名稱、目的資料夾、檔名規則、來源、資產清單、雜湊清冊
declare -a PNAMES=() PDESTS=() PFILES=()
mapfile -t EXISTING_TYPES < <(find "$UI/GCP" -type f \( -name '*.qml' -o -name '*.js' \) -printf '%f\n' | sort -u)
known=0
while read -r name dest regex srcrel assets payload; do
    [[ -z "$name" || "$name" == \#* ]] && continue
    known=$((known+1))
    [[ "$name" =~ ^[A-Za-z]+$ && "$dest" =~ ^[A-Za-z]+$ && "$srcrel" =~ ^[A-Za-z0-9_/]+$ && "$srcrel" != *..* ]] || { echo "bad plugin entry: $name" >&2; exit 2; }
    if [[ -n "${SKIP[$name]:-}" ]]; then echo "skip plugin: $name (slot stays inactive)"; unset 'SKIP[$name]'; continue; fi
    src="$REPO/$srcrel"
    [[ -f "$src/$assets" && -f "$src/$payload" && ! -L "$src/$assets" && ! -L "$src/$payload" ]] || { echo "plugin $name: manifest files missing in $srcrel" >&2; exit 2; }
    mapfile -t list < <(sed 's/\r$//' "$src/$assets" | grep -v '^[[:space:]]*$')
    [[ ${#list[@]} -ge 1 ]] || { echo "plugin $name: empty asset list" >&2; exit 2; }
    declare -A seen=()
    while read -r expected file; do
        [[ -z "$expected" ]] && continue
        [[ "$expected" =~ ^[a-f0-9]{64}$ && "$file" =~ $regex ]] || { echo "plugin $name: bad payload line: $file" >&2; exit 2; }
        seen["$file"]="$expected"
    done < <(sed 's/\r$//' "$src/$payload")
    [[ ${#seen[@]} == ${#list[@]} ]] || { echo "plugin $name: asset list and payload differ" >&2; exit 2; }
    for file in "${list[@]}"; do
        [[ "$file" =~ $regex && -n "${seen[$file]:-}" && -f "$src/$file" && ! -L "$src/$file" ]] || { echo "plugin $name: invalid asset $file" >&2; exit 2; }
        actual="$(sed 's/\r$//' "$src/$file" | sha256sum)"
        [[ "${actual%% *}" == "${seen[$file]}" ]] || { echo "plugin $name: LF checksum mismatch: $file" >&2; exit 2; }
        for t in "${EXISTING_TYPES[@]}"; do [[ "$t" != "$file" ]] || { echo "plugin $name: $file collides with an existing UI file name (QML type clash)" >&2; exit 2; }; done
        PNAMES+=("$name"); PDESTS+=("$dest"); PFILES+=("$src/$file")
    done
    unset seen
done < <(sed 's/\r$//' "$PLUGINS")
[[ "$known" == 2 ]] || { echo 'expected 2 plugin entries' >&2; exit 2; }
[[ ${#SKIP[@]} == 0 ]] || { echo "unknown --skip name: ${!SKIP[*]}" >&2; exit 2; }

# ---- 2. 上鎖，在預演目錄裡組出完整結果 ----
LOCK="$UI/.mvp-install.lock"
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
STAGE="$(mktemp -d "$UI/.mvp-install.XXXXXX")"
WORK="$STAGE/ui"
mkdir -- "$WORK"
cp -a -- "$UI/GCP" "$WORK/GCP"
cp -p -- "$UI/$DOC" "$WORK/$DOC"
cp -p -- "$UI/$DOC" "$STAGE/original-handoff.md"
for f in AGENTS.md CLAUDE.md; do [[ ! -f "$UI/$f" ]] || cp -p -- "$UI/$f" "$WORK/$f"; done

# 2a. UI agent：用它自己的安裝器（含它的所有檢查）裝進預演副本
bash "$AGENT_DIR/install_into_ui.sh" "$WORK" > "$STAGE/agent-install.log" 2>&1 || { cat -- "$STAGE/agent-install.log" >&2; exit 3; }
mkdir -- "$STAGE/agent-stage"
find "$WORK" -maxdepth 1 -name '.ui-agent-install.*' -exec mv -t "$STAGE/agent-stage" -- {} +
for f in AGENTS.md CLAUDE.md; do rm -f -- "$WORK/$f"; done

# 2b. 插槽 patch（目標先轉 LF）
while IFS= read -r relative; do
    [[ "$relative" == GCP/* && "$relative" != *..* && -f "$WORK/$relative" && ! -L "$WORK/$relative" ]] || { echo "slot target missing: $relative" >&2; exit 3; }
    sed 's/\r$//' "$WORK/$relative" > "$STAGE/.normalized"
    cp -- "$STAGE/.normalized" "$WORK/$relative"
done < <(sed 's/\r$//' "$HERE/slot_targets_v1.txt")
sed 's/\r$//' "$SLOT_PATCH" > "$STAGE/slots.patch.lf"
patch --batch --forward --fuzz=0 -p1 -d "$WORK" < "$STAGE/slots.patch.lf" > "$STAGE/slots.patch.log" 2>&1 || { cat -- "$STAGE/slots.patch.log" >&2; exit 3; }

# 2c. 外掛檔案、CMake 清單與已安裝清單
CMAKE="$WORK/GCP/CMakeLists.txt"
[[ "$(grep -Fxc "$CMAKE_MARKER" "$CMAKE")" == 1 ]] || { echo 'CMake marker missing' >&2; exit 3; }
installed=()
cmake_lines=''
for i in "${!PFILES[@]}"; do
    dest="${PDESTS[$i]}"; file="$(basename -- "${PFILES[$i]}")"
    mkdir -p -- "$WORK/GCP/$dest"
    [[ ! -e "$WORK/GCP/$dest/$file" ]] || { echo "duplicate plugin file: $dest/$file" >&2; exit 3; }
    cp -- "${PFILES[$i]}" "$WORK/GCP/$dest/$file"
    [[ "$(sha256sum < "${PFILES[$i]}")" == "$(sha256sum < "$WORK/GCP/$dest/$file")" ]] || exit 3
    installed+=("$dest/$file")
    cmake_lines+="        $dest/$file"$'\n'
done
mkdir -- "$WORK/GCP/MvpSlots"
files_js='['
for p in "${installed[@]}"; do files_js+="\"$p\", "; done
files_js="${files_js%, }]"
sed "s#@FILES@#$files_js#" "$TEMPLATE" | sed 's/\r$//' > "$WORK/GCP/MvpSlots/GcpMvpInstalled.js"
grep -Fq "var files = $files_js" "$WORK/GCP/MvpSlots/GcpMvpInstalled.js" || exit 3
printf '%s' "$cmake_lines" > "$STAGE/cmake.lines"
awk -v marker="$CMAKE_MARKER" -v linesfile="$STAGE/cmake.lines" '
    { print } $0 == marker { while ((getline l < linesfile) > 0) print l }' "$CMAKE" > "$STAGE/.cmake"
cp -- "$STAGE/.cmake" "$CMAKE"
[[ "$(grep -Fxc '        MvpSlots/GcpMvpInstalled.js' "$CMAKE")" == 1 ]] || { echo 'CMake registry entry mismatch' >&2; exit 3; }
for p in "${installed[@]}"; do
    [[ "$(grep -Fxc "        $p" "$CMAKE")" == 1 ]] || { echo "CMake plugin entry mismatch: $p" >&2; exit 3; }
done
{
    echo 'mvp-install-v1'
    echo "installer_manifest_sha256=$(sha256sum < "$HERE/install_mvp_payload_v1.sha256" | cut -d ' ' -f1)"
    echo "agent_receipt=Agent/.install_v6_receipt"
    echo "plugins=${#installed[@]} files"
    for p in "${installed[@]}"; do echo "file=$p"; done
} > "$WORK/GCP/MvpSlots/.install_mvp_receipt"

if [[ "$MODE" == check ]]; then
    echo "CHECK: UI agent + slots + ${#installed[@]} plugin files staged in $WORK; target GCP and handoff unchanged"
    exit 0
fi

# ---- 3. 替換（兩次 rename；一般失敗與中斷可還原，斷電不保證原子性） ----
mv -T -- "$UI/GCP" "$STAGE/original-GCP"
MOVED=1
mv -T -- "$WORK/GCP" "$UI/GCP"
DOC_DONE=1
mv -T -- "$WORK/$DOC" "$UI/$DOC"
MOVED=0
echo "Installed UI agent, MVP slots and ${#installed[@]} plugin files: ${installed[*]}. No build, model, service or application was started."
