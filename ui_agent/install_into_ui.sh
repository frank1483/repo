#!/usr/bin/env bash
# 把 UI agent 裝進「正式 UI 的副本」（不要對原始工作目錄執行）。
# 用法：./install_into_ui.sh <ELAN_GCP_ui 副本根目錄>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UI="${1:?請給 ELAN_GCP_ui 副本的根目錄}"
[ -f "$UI/GCP/GcpMainShell.qml" ] || { echo "找不到 $UI/GCP/GcpMainShell.qml"; exit 1; }
if [ -d "$UI/GCP/Agent" ]; then echo "已安裝過（$UI/GCP/Agent 存在），不重複安裝"; exit 1; fi

# 先試套用，失敗就不動任何檔案
for P in elan_gcp_ui_agent.patch elan_gcp_home_modules.patch elan_gcp_text_scale.patch; do
    patch -p1 -d "$UI" --dry-run < "$HERE/patch/$P"
done
for P in elan_gcp_ui_agent.patch elan_gcp_home_modules.patch elan_gcp_text_scale.patch; do
    patch -p1 -d "$UI" < "$HERE/patch/$P"
done
mkdir -p "$UI/GCP/Agent"
cp "$HERE"/qml/GcpAgentCore.js "$HERE"/qml/GcpAgentState.qml "$HERE"/qml/GcpAgentModule.qml "$HERE"/qml/GcpAgentOverlay.qml "$UI/GCP/Agent/"
echo "完成：GCP/Agent/ 4 個檔案，修改 GCP/CMakeLists.txt、GCP/GcpMainShell.qml、GCP/Flight/GcpLiveFlightScreen.qml、GCP/Home/GcpHomeScreen.qml"
