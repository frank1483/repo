#!/bin/bash
# 組 APK 原始碼目錄：正式 GCP 允許清單 11 檔＋字型（只複製、不改）＋GcpEnv 替身＋genui 的 qml（JS、W 元件、骨架）＋示範主畫面。
# 用法：bash make_apk_src.sh <ELAN_GCP_ui> <輸出目錄（必須不存在）> <本資料夾> <genui_m1v2 資料夾>
set -eu
R="$1"; OUT="$2"; KIT="$3"; G="$4"
bash "$KIT/../qt_widgets_verify_host04/make_host_src.sh" "$R" "$OUT" "$KIT/../qt_widgets_verify_host04" > /dev/null
cp "$KIT/GcpEnv.qml" "$OUT/GcpEnv.qml"; cp "$KIT/main.cpp" "$OUT/main.cpp"
mkdir -p "$OUT/genui/qml/widgets" "$OUT/genui/qml/skeleton" "$OUT/genui/apk_poc01"
cp "$G"/qml/*.js "$OUT/genui/qml/"; cp "$G"/qml/widgets/*.qml "$OUT/genui/qml/widgets/"; cp "$G"/qml/skeleton/*.qml "$OUT/genui/qml/skeleton/"; cp "$KIT/demo_main.qml" "$OUT/genui/apk_poc01/"
GEN=$(cd "$OUT" && find genui -type f | sort | tr '\n' ' ')
# 改寫 CMakeLists：加 GcpEnv 單例、genui 資源、Android 設定
python3 - "$OUT/CMakeLists.txt" "$GEN" <<'PY'
import sys
p, gen = sys.argv[1], sys.argv[2]; s = open(p).read()
assert "set_source_files_properties(" in s
s = s.replace("set_source_files_properties(", "set_source_files_properties(GcpEnv.qml ", 1)
assert "  QML_FILES " in s
s = s.replace("  QML_FILES ", "  QML_FILES GcpEnv.qml ", 1)
s += "qt_add_resources(genui_host genui_files PREFIX / FILES " + gen + ")\n"
s += 'set_target_properties(genui_host PROPERTIES QT_ANDROID_PACKAGE_NAME "org.thesis.genui.poc01" QT_ANDROID_VERSION_NAME "0.1-poc01" QT_ANDROID_VERSION_CODE 1)\n'
open(p, "w").write(s)
PY
(cd "$OUT" && find . -type f ! -name SRC.sha256 -print0 | sort -z | xargs -0 sha256sum > SRC.sha256)
grep -c . "$OUT/SRC.sha256"; tail -3 "$OUT/CMakeLists.txt"
