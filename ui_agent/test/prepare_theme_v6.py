"""在 PC 上準備「已套主題」的 GCP 主題資料夾，給 run_live_ui_gateway_v6.py 的第 4 個參數用。

做什麼：從正式 UI 的 GCP 資料夾「只讀」複製 GcpTheme*.qml 到一個新資料夾，
再用純 Python（不需要 git 或 patch 指令）套上本 repo 的兩份 host patch 裡與主題有關的部分：
  - patch/elan_gcp_text_scale.patch：GcpThemeFont.qml、GcpThemeSwatches.qml
  - patch/elan_gcp_agent_theme.patch：GcpThemeColor.qml
套用前先比對原檔雜湊，套用後再比對結果雜湊（都以 CRLF→LF 後計算，與 install_into_ui.sh 相同）。
任何一步不符就停下、不留半成品。不寫入、不改動正式 UI。

用法（Windows 也可）：
  python -I ui_agent/test/prepare_theme_v6.py "<正式 UI 根目錄或其 GCP 資料夾>" <新的輸出資料夾>
例：
  python -I ui_agent/test/prepare_theme_v6.py "D:\\UAV GCP\\GCP UI圖\\elan\\ELAN_GCP_ui" gcs_demo_live\\theme_gcp_v6
然後：
  python -I ui_agent/test/run_live_ui_gateway_v6.py <新輸出> <閘道網址> <模型> gcs_demo_live\\theme_gcp_v6
"""
import hashlib
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH_DIR = os.path.join(HERE, "..", "patch")
# (檔名, 來源 patch, 原檔 LF sha256, 結果 LF sha256)
TARGETS = [
    ("GcpThemeColor.qml", "elan_gcp_agent_theme.patch",
     "0c7ee3ca010b8a029d38e3d5d4d22d9b884d2b091fdbdc224cdc0ef6aeec0f85",
     "d1ed9ee12c571675e5266ff5142a4d862f3bb78c51d7a63c9bc97e3556af76ca"),
    ("GcpThemeFont.qml", "elan_gcp_text_scale.patch",
     "0beb6b192cc2f15e9ceaf4f2404fdf904f10791835c558d3ca9b5fa3dc2e6d02",
     "c0a04e897e6f2012baa785fc587645cba524d9e76ebebe2ccf1f18c4d7d998cc"),
    ("GcpThemeSwatches.qml", "elan_gcp_text_scale.patch",
     "37cbc872f6439c243dd21c7bc9d7dae04133ebb789994b8cd9d50556b23a29d3",
     "94f22ae10555b96ff05673719d610a47722b244c874279ffc1a02e2bbbdf68fd"),
]
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_section(patch_text: str, name: str):
    """取出 patch 中 b/GCP/<name> 那一段的 hunk 行。"""
    lines = patch_text.split("\n")
    out, inside, i = [], False, 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            inside = False
        elif line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            inside = lines[i + 1].split("\t")[0].rstrip() == "+++ b/GCP/" + name
            i += 2
            continue
        elif inside:
            out.append(line)
        i += 1
    if not out:
        raise SystemExit("patch 內找不到 GCP/%s" % name)
    return out


def apply_hunks(original: str, section):
    """嚴格套用（無 fuzz、行號必須吻合）。"""
    src = original.split("\n")
    result, pos, i = [], 0, 0
    while i < len(section) and not section[i].startswith("@@"):
        i += 1
    while i < len(section):
        m = HUNK.match(section[i])
        if not m:
            if section[i] == "" and i == len(section) - 1:
                break
            raise SystemExit("無法解析 hunk 標頭：%r" % section[i][:80])
        start = int(m.group(1)) - 1 if (m.group(2) or "1") != "0" else int(m.group(1))
        i += 1
        result.extend(src[pos:start])
        pos = start
        while i < len(section) and not section[i].startswith("@@"):
            line = section[i]
            if line.startswith("\\"):
                i += 1
                continue
            tag, body = (line[:1], line[1:]) if line else (" ", "")
            if tag in (" ", "-"):
                if pos >= len(src) or src[pos] != body:
                    raise SystemExit("內容不符，第 %d 行：原檔與 patch 不同，停止（正式 UI 版本可能不同）" % (pos + 1))
                if tag == " ":
                    result.append(body)
                pos += 1
            elif tag == "+":
                result.append(body)
            else:
                raise SystemExit("未知的 patch 行：%r" % line[:80])
            i += 1
    result.extend(src[pos:])
    return "\n".join(result)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src = os.path.abspath(sys.argv[1])
    if os.path.isdir(os.path.join(src, "GCP")):
        src = os.path.join(src, "GCP")
    out = os.path.abspath(sys.argv[2])
    if not os.path.isfile(os.path.join(src, "GcpThemeColor.qml")):
        print("找不到 GcpThemeColor.qml：", src)
        return 2
    if os.path.exists(out):
        print("輸出資料夾已存在，不覆寫：", out)
        return 2
    names = sorted(f for f in os.listdir(src) if f.startswith("GcpTheme") and f.endswith(".qml"))
    tmp = tempfile.mkdtemp(prefix="theme_v6_", dir=os.path.dirname(out) or None)
    try:
        for f in names:  # 只讀複製
            with open(os.path.join(src, f), "rb") as fh:
                data = lf(fh.read())
            with open(os.path.join(tmp, f), "wb") as fh:
                fh.write(data)
        report = []
        for name, patch_name, want_before, want_after in TARGETS:
            with open(os.path.join(tmp, name), "rb") as fh:
                before = fh.read()
            if sha(before) != want_before:
                raise SystemExit("%s 原檔雜湊不符（%s…），正式 UI 版本與測試基準不同，停止" % (name, sha(before)[:12]))
            with open(os.path.join(PATCH_DIR, patch_name), "rb") as fh:
                patch_text = lf(fh.read()).decode("utf-8")
            after = apply_hunks(before.decode("utf-8"), file_section(patch_text, name)).encode("utf-8")
            if sha(after) != want_after:
                raise SystemExit("%s 套用後雜湊不符（%s…），停止" % (name, sha(after)[:12]))
            with open(os.path.join(tmp, name), "wb") as fh:
                fh.write(after)
            report.append("%s  %s → %s" % (name, want_before[:12], want_after[:12]))
        os.replace(tmp, out)
    except SystemExit as e:
        shutil.rmtree(tmp, ignore_errors=True)
        print("失敗：", e)
        return 1
    print("完成：", out)
    for line in report:
        print("  " + line)
    print("  其他主題檔原樣複製：", ", ".join(n for n in names if n not in [t[0] for t in TARGETS]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
