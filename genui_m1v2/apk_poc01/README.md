# apk_poc01：APK 最小測試包（固定情境示範版）

範圍（11/20 定）：獨立小主程式＋正式 GCP 主題與字型＋W1～W5＋骨架工作區（含轉場）；用固定情境 base／near／long 每 6 秒切換。不接模型、不連飛控、不連板子、不安裝到板子。第一版 APK 期限 11/30，這是提前做的最小測試。
- GcpEnv：正式的是 C++ 單例，沒編入；GcpEnv.qml 是替身，只回預設值（GcpThemeLayout 在 Android 上才會呼叫）。
- 原檔只複製、不改、不進 repo。

## 第 1 段：桌面冒煙（不需下載，現在可跑）
在本資料夾執行，只跑一次：
```
R=~/elan_gcp_ui_official_20261120/ELAN_GCP_ui; S=~/genui_apk_src_poc01_20261120; BD=~/genui_apk_build_desktop_poc01_20261120
bash make_apk_src.sh "$R" "$S" "$PWD" "$PWD/.." > make_src.txt 2>&1; echo "exit=$?" >> make_src.txt
bash ../qt_widgets_verify_host04/build_host.sh "$S" "$BD" > build_desktop.txt 2>&1; echo "exit=$?" >> build_desktop.txt
QT_QPA_PLATFORM=offscreen timeout 20 "$BD/genui_host" > smoke_desktop.txt 2>&1; echo "exit=$?" >> smoke_desktop.txt
cp "$S/SRC.sha256" "$S/CMakeLists.txt" .
```
判定：make_src、build 為 0；smoke 預期 exit=124（timeout 結束，示範畫面不會自己關），且 smoke_desktop.txt 沒有任何帶「file://…:行號」、TypeError、ReferenceError、Cannot load 的行。

## 第 2 段：Android APK（要使用者先同意下載 Gradle 8.10 與 AGP 8.6.0 相依套件後才跑）
```
QA=~/Qt/6.8.3/android_arm64_v8a; BA=~/genui_apk_build_android_poc01_20261120
NJ=$(ls ~/Qt/Tools/Ninja/ninja 2>/dev/null || command -v ninja)
JAVA_HOME=~/android_env_v1/jdk17 "$QA/bin/qt-cmake" -S "$S" -B "$BA" -G Ninja -DCMAKE_MAKE_PROGRAM="$NJ" -DQT_HOST_PATH=~/Qt/6.8.3/gcc_64 \
  -DANDROID_SDK_ROOT=~/android_env_v1/sdk -DANDROID_NDK_ROOT=~/android_env_v1/sdk/ndk/27.2.12479018 -DCMAKE_BUILD_TYPE=Debug > cfg_android.txt 2>&1; echo "exit=$?" >> cfg_android.txt
JAVA_HOME=~/android_env_v1/jdk17 cmake --build "$BA" --target apk > build_android.txt 2>&1; echo "exit=$?" >> build_android.txt
find "$BA" -name "*.apk" -exec ls -l {} \; -exec sha256sum {} \; > apk_list.txt
du -sh ~/.gradle > gradle_downloaded.txt 2>&1; find ~/.gradle/wrapper/dists ~/.gradle/caches/modules-2/files-2.1 -maxdepth 2 -type d >> gradle_downloaded.txt 2>&1
```
下載只來自 services.gradle.org、dl.google.com、repo.maven.apache.org；實際下載的內容記在 gradle_downloaded.txt。不安裝到任何裝置、不執行 adb。失敗原樣保留，修正另開 poc02。
