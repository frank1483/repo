# apk_poc02：Android APK 編譯（apk_poc01 第 2 段的修正版）

apk_poc01 第 2 段 run1（11/20 22:11）失敗在 qt-cmake 設定：README 在「-D參數=~/...」寫了 ~，bash 不展開，CMake 找不到 NDK toolchain。沒有啟動 Gradle，下載量 0；原樣保留在 PC apk_poc01_20261120\run2_laptop_android\。
本版只改指令：路徑全用 $HOME 展開、換新的建置目錄、先記錄 cmake 版本。原始碼沿用 apk_poc01 第 1 段產生的 ~/genui_apk_src_poc01_20261120（不重建）。
需要使用者在討論串親打下載同意（poc02）。下載來源只限 services.gradle.org、dl.google.com、repo.maven.apache.org。不安裝到任何裝置、不執行 adb。只跑一次，失敗原樣保留，修正另開 poc03。

```
A=$HOME/android_env_v1; Q=$HOME/Qt/6.8.3; S=$HOME/genui_apk_src_poc01_20261120; BA=$HOME/genui_apk_build_android_poc02_20261120
[ -e "$BA" ] && { echo "$BA exists"; exit 3; }
NJ=$(ls $HOME/Qt/Tools/Ninja/ninja 2>/dev/null || command -v ninja)
(cmake --version; "$NJ" --version; ls "$A/sdk/ndk/27.2.12479018/build/cmake/android.toolchain.cmake") > tools.txt 2>&1
JAVA_HOME="$A/jdk17" "$Q/android_arm64_v8a/bin/qt-cmake" -S "$S" -B "$BA" -G Ninja -DCMAKE_MAKE_PROGRAM="$NJ" -DQT_HOST_PATH="$Q/gcc_64" \
  -DANDROID_SDK_ROOT="$A/sdk" -DANDROID_NDK_ROOT="$A/sdk/ndk/27.2.12479018" -DCMAKE_BUILD_TYPE=Debug > cfg_android.txt 2>&1; echo "exit=$?" >> cfg_android.txt
JAVA_HOME="$A/jdk17" ANDROID_SDK_ROOT="$A/sdk" cmake --build "$BA" --target apk > build_android.txt 2>&1; echo "exit=$?" >> build_android.txt
find "$BA" -name "*.apk" -exec ls -l {} \; -exec sha256sum {} \; > apk_list.txt
(du -sh $HOME/.gradle; find $HOME/.gradle/wrapper/dists $HOME/.gradle/caches/modules-2/files-2.1 -maxdepth 2 -type d) > gradle_downloaded.txt 2>&1
```
cfg 失敗就停，不跑 build。cmake 是 3.22（Qt 6.8 Android 建議 3.24 以上）；若因版本報錯，原樣保留，再問使用者是否下載新版 CMake。
