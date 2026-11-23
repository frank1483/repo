#!/usr/bin/env bash
# 方案 A／B 安裝器（說明 v3）：在「已裝好 MVP（UI agent＋插槽＋AiAlerts＋AiMission）」的 UI 副本上，再裝第 3 個外掛 AiAgent。
#   bash install_ab_into_ui.sh <A|B> <埠> <UI 副本根目錄>
# 只動副本。先在預演目錄組好結果，全部檢查通過才替換 GCP；任何一步失敗副本維持原樣。不編譯、不啟動任何東西。
# 加的東西：GCP/AiAgent/（面板、航線接收端、共用登記、純函式、編譯時寫死方案的 GcpAiAgentBuild.js）、
#           主畫面一個 Loader（浮動層，z 90，在 UI agent 之下）、任務規劃頁一個看不見的航線接收端 Loader、CMake 清單 5 行。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
QML="$HERE/qml"
[[ $# == 3 && "$1" =~ ^[AB]$ && "$2" =~ ^[0-9]{4,5}$ ]] || { echo 'usage: bash install_ab_into_ui.sh <A|B> <agent-port> <UI-copy-root>' >&2; exit 2; }
PLAN="$1"; PORT="$2"; UI="$(cd -- "$3" && pwd -P)"
CMAKE_MARKER='        # MVP plugin files (install_mvp_into_ui.sh inserts AiMission/AiAlerts entries below)'
SHELL_ANCHOR='    // UI agent：每個畫面都能叫出（右側 AI 按鈕）；只換頁與調整版面，所有變更可復原'
PLAN_ANCHOR='                        when: mvpMissionSlot.item !== null && ("activeVehicle" in mvpMissionSlot.item)'
FILES=(GcpAiAgentPanel.qml GcpAiAgentRouteSink.qml GcpAiAgentCore.js GcpAiAgentBus.js)
for tool in sha256sum cp mv mkdir mktemp grep sed awk; do command -v "$tool" >/dev/null; done

# ---- 1. 檢查（還沒動任何東西） ----
[[ -f "$UI/GCP/MvpSlots/.install_mvp_receipt" && -f "$UI/GCP/Agent/GcpAgentState.qml" ]] || { echo 'UI copy has no MVP installation (run install_mvp_into_ui.sh first)' >&2; exit 2; }
[[ ! -e "$UI/GCP/AiAgent" && ! -L "$UI/GCP/AiAgent" && ! -e "$UI/.ab-install.lock" ]] || { echo 'prior AiAgent installation or lock found; use a fresh copy' >&2; exit 2; }
[[ -z "$(find "$UI/GCP" -type l -print -quit)" ]] || { echo 'GCP symlinks refused' >&2; exit 2; }
n=0
while read -r expected relative; do
    [[ -z "$expected" ]] && continue
    [[ "$expected" =~ ^[a-f0-9]{64}$ && "$relative" =~ ^[A-Za-z0-9_.]+$ && -f "$QML/$relative" && ! -L "$QML/$relative" ]] || { echo "bad payload line: $relative" >&2; exit 2; }
    actual="$(sed 's/\r$//' "$QML/$relative" | sha256sum)"
    [[ "${actual%% *}" == "$expected" ]] || { echo "LF checksum mismatch: qml/$relative" >&2; exit 2; }
    n=$((n+1))
done < <(sed 's/\r$//' "$HERE/install_ab_payload_v1.sha256")
[[ "$n" == 5 ]] || { echo 'expected 5 payload entries' >&2; exit 2; }
for f in "${FILES[@]}" GcpAiAgentBuild.js; do
    [[ -z "$(find "$UI/GCP" -type f -name "$f" -print -quit)" ]] || { echo "$f already exists in the UI (QML type clash)" >&2; exit 2; }
done
SH="$UI/GCP/GcpMainShell.qml"; PL="$UI/GCP/GcpMissionPlannerPage.qml"; CM="$UI/GCP/CMakeLists.txt"
[[ "$(sed 's/\r$//' "$SH" | grep -Fxc "$SHELL_ANCHOR")" == 1 ]] || { echo 'shell anchor not found exactly once' >&2; exit 2; }
[[ "$(sed 's/\r$//' "$PL" | grep -Fxc "$PLAN_ANCHOR")" == 1 ]] || { echo 'planner anchor not found exactly once' >&2; exit 2; }
[[ "$(sed 's/\r$//' "$CM" | grep -Fxc "$CMAKE_MARKER")" == 1 ]] || { echo 'CMake marker not found exactly once' >&2; exit 2; }

# ---- 2. 預演 ----
LOCK="$UI/.ab-install.lock"
mkdir -- "$LOCK"
STAGE="$(mktemp -d "$UI/.ab-install.XXXXXX")"
MOVED=0
finish() {
    local status=$?
    trap - EXIT HUP INT TERM
    set +e
    if (( status != 0 && MOVED )); then
        [[ ! -e "$UI/GCP" ]] || mv -T -- "$UI/GCP" "$STAGE/failed-GCP"
        mv -T -- "$STAGE/original-GCP" "$UI/GCP" || { echo "rollback failed; original at $STAGE/original-GCP" >&2; exit 90; }
    fi
    echo "staging/backup retained: $STAGE" >&2
    rmdir -- "$LOCK"
    exit "$status"
}
trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
W="$STAGE/GCP"
cp -a -- "$UI/GCP" "$W"
mkdir -- "$W/AiAgent"
for f in "${FILES[@]}"; do sed 's/\r$//' "$QML/$f" > "$W/AiAgent/$f"; done
sed 's/\r$//' "$QML/GcpAiAgentBuild.js.in" | sed "s/@PLAN@/$PLAN/; s/@PORT@/$PORT/" > "$W/AiAgent/GcpAiAgentBuild.js"
grep -Fxq "var PLAN = \"$PLAN\"" "$W/AiAgent/GcpAiAgentBuild.js" && grep -Fxq "var AGENT_URL = \"http://127.0.0.1:$PORT\"" "$W/AiAgent/GcpAiAgentBuild.js"

cat > "$STAGE/shell.block" <<'EOF'
    // 方案 A／B 插槽（install_ab_into_ui.sh）：AI Agent 面板，蓋在頁面之上、UI agent 之下；按鈕在 UI agent 的 AI 按鈕下方。
    // 版面、文字大小、主題透過 GcpAgentState 與 UI agent 的檢查執行；航線交給任務規劃頁的接收端。
    Loader {
        id: abAgentSlot
        anchors.fill: parent
        z: 91
        visible: AuthService.state === AuthService.Authenticated || root._devPreview
        source: "AiAgent/GcpAiAgentPanel.qml"
        onLoaded: {
            item.shell = root
            item.agentState = GcpAgentState
            item.apiBase = GcpEnv.value("GCS_AB_AGENT_URL", item.apiBase)
            item.envValue = function (name, fallback) { return GcpEnv.value(name, fallback) }
        }
    }

EOF
cat > "$STAGE/planner.block" <<'EOF'
                    // 方案 A／B 插槽（install_ab_into_ui.sh）：看不見的航線接收端；AI Agent 面板只透過它寫或還原航點。
                    Loader {
                        id: abRouteSinkSlot
                        source: "AiAgent/GcpAiAgentRouteSink.qml"
                        onLoaded: item.missionController = root._missionController
                    }
EOF
sed 's/\r$//' "$UI/GCP/GcpMainShell.qml" | awk -v anchor="$SHELL_ANCHOR" -v f="$STAGE/shell.block" '
    $0 == anchor { while ((getline l < f) > 0) print l } { print }' > "$W/GcpMainShell.qml"
# planner：錨點那行之後的下一行（Binding 的右大括號）之後插入
sed 's/\r$//' "$UI/GCP/GcpMissionPlannerPage.qml" | awk -v anchor="$PLAN_ANCHOR" -v f="$STAGE/planner.block" '
    { print } hit == 1 { while ((getline l < f) > 0) print l; hit = 2 } $0 == anchor { hit = 1 }' > "$W/GcpMissionPlannerPage.qml"
printf '        AiAgent/%s\n' "${FILES[@]}" GcpAiAgentBuild.js > "$STAGE/cmake.lines"
sed 's/\r$//' "$UI/GCP/CMakeLists.txt" | awk -v marker="$CMAKE_MARKER" -v f="$STAGE/cmake.lines" '
    { print } $0 == marker { while ((getline l < f) > 0) print l }' > "$W/CMakeLists.txt"
[[ "$(grep -c 'abAgentSlot' "$W/GcpMainShell.qml")" == 1 && "$(grep -c 'abRouteSinkSlot' "$W/GcpMissionPlannerPage.qml")" == 1 ]] || { echo 'slot insertion check failed' >&2; exit 3; }
[[ "$(grep -A1 -Fx "$PLAN_ANCHOR" "$W/GcpMissionPlannerPage.qml" | tail -1)" == '                    }' ]] || { echo 'planner anchor is not followed by the Binding close brace' >&2; exit 3; }
for f in "${FILES[@]}" GcpAiAgentBuild.js; do [[ "$(grep -Fxc "        AiAgent/$f" "$W/CMakeLists.txt")" == 1 ]] || { echo "CMake entry missing: $f" >&2; exit 3; }; done
{
    echo 'ab-install-v1'
    echo "plan=$PLAN"; echo "agent_url=http://127.0.0.1:$PORT"
    echo "payload_manifest_sha256=$(sha256sum < "$HERE/install_ab_payload_v1.sha256" | cut -d ' ' -f1)"
    for f in "${FILES[@]}" GcpAiAgentBuild.js; do echo "file=AiAgent/$f $(sha256sum < "$W/AiAgent/$f" | cut -d ' ' -f1)"; done
} > "$W/AiAgent/.install_ab_receipt"

# ---- 3. 替換 ----
mv -T -- "$UI/GCP" "$STAGE/original-GCP"
MOVED=1
mv -T -- "$W" "$UI/GCP"
MOVED=0
echo "Installed AiAgent (plan $PLAN, http://127.0.0.1:$PORT) into $UI/GCP. Nothing was built or started."
