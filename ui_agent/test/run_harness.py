"""在 Qt 6.8.3（PySide6）離屏執行模擬殼層，跑一連串意圖並檢查換頁、版面與復原結果，順便存截圖。

用法：python -I run_harness.py <輸出資料夾>
模型路徑用本機假模型伺服器（固定規則回覆）測流程，不代表真實模型表現。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QMetaObject, QObject, Q_ARG, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402,F401  讓根物件以 QQuickWindow 型別回傳（可截圖）

HERE = os.path.dirname(os.path.abspath(__file__))
QML_DIR = os.path.join(HERE, "..", "qml")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------- 假模型伺服器（OpenAI 相容）
class FakeModel(BaseHTTPRequestHandler):
    mode = "select"
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = json.loads(body["messages"][1]["content"])
        ids = [c["id"] for c in user["candidates"]]
        FakeModel.calls.append(user)
        if FakeModel.mode == "invalid":
            out = {"decision": "SELECT", "choice_id": "NAV_99", "reason_zh": "亂選", "evidence_ids": []}
        elif "飛行設定" in user["intent"]:
            out = {"decision": "SELECT", "choice_id": "NAV_8_11", "reason_zh": "飛行畫面相關設定", "evidence_ids": ["E1"]}
        elif "拍" in user["intent"] and "NAV_12" in ids:
            out = {"decision": "SELECT", "choice_id": "NAV_12", "reason_zh": "拍攝的照片在媒體庫", "evidence_ids": []}
        else:
            out = {"decision": "CLARIFY", "choice_id": "", "reason_zh": "不確定", "evidence_ids": []}
        data = json.dumps({"choices": [{"message": {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), FakeModel)
threading.Thread(target=server.serve_forever, daemon=True).start()
MODEL_URL = "http://127.0.0.1:%d/v1" % server.server_address[1]

# ---------------------------------------------------------------- 組測試用 QML 模組（模擬正式的 QGroundControl.GCP，Agent/ 子目錄）
work = tempfile.mkdtemp(prefix="agent_harness_")
mod_dir = os.path.join(work, "QGroundControl", "GCP")
os.makedirs(os.path.join(mod_dir, "Agent"))
for f in os.listdir(QML_DIR):
    shutil.copy(os.path.join(QML_DIR, f), os.path.join(mod_dir, "Agent"))
with open(os.path.join(mod_dir, "qmldir"), "w") as fh:
    fh.write("module QGroundControl.GCP\n"
             "singleton GcpAgentState 1.0 Agent/GcpAgentState.qml\n"
             "GcpAgentModule 1.0 Agent/GcpAgentModule.qml\n"
             "GcpAgentOverlay 1.0 Agent/GcpAgentOverlay.qml\n"
             "singleton GcpTheme 1.0 GcpTheme.qml\n")
shutil.copy(os.path.join(HERE, "harness", "GcpTheme.qml"), mod_dir)
shutil.copy(os.path.join(HERE, "harness", "Main.qml"), work)

app = QGuiApplication(sys.argv)
app.setOrganizationName("agent-harness-%d" % os.getpid())   # 模型設定的 Settings 寫到一次性位置
app.setApplicationName("harness")
logs = []
engine = win = shell = agent = None


def start(env):
    global engine, win, shell, agent
    engine = QQmlApplicationEngine()
    engine.addImportPath(work)
    engine.rootContext().setContextProperty("harnessEnv", env)
    engine.warnings.connect(lambda ws: [logs.append(w.toString()) for w in ws])
    engine.load(QUrl.fromLocalFile(os.path.join(work, "Main.qml")))
    if not engine.rootObjects():
        print("QML 載入失敗", logs)
        sys.exit(2)
    win = engine.rootObjects()[0]
    shell = win.findChild(QObject, "shell")
    agent = win.findChild(QObject, "agent")


start({"GCS_LLM_BACKEND": "none"})


def wait(ms=400):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def say(text, ms=500):
    QMetaObject.invokeMethod(agent, "submit", Q_ARG("QVariant", text))
    wait(ms)


def prop(obj, name):
    v = obj.property(name)
    return v.toVariant() if hasattr(v, "toVariant") else v


def page():
    return shell.property("currentPage")


def section(p):
    s = prop(shell, "sections")
    return s.get(str(p), s.get(p, -1)) if isinstance(s, dict) else -1


def mod(name):
    # Loader 換頁後舊實例可能還沒刪除，取目前可見的那個
    items = [o for o in win.findChildren(QObject, name) if o.property("visible")]
    if not items:
        return None
    item = items[-1]
    box = {"opacity": item.property("opacity")}
    # 透過 mapToItem 取得含變換後的位置與大小
    area = item.parentItem()
    p0 = item.mapToItem(area, 0, 0)
    p1 = item.mapToItem(area, item.property("width"), item.property("height"))
    box.update({"x": round(p0.x()), "y": round(p0.y()), "w": round(p1.x() - p0.x()), "h": round(p1.y() - p0.y())})
    return box


def shot(name):
    wait(300)
    win.grabWindow().save(os.path.join(OUT, name + ".png"))


results = []


def check(label, cond, detail=""):
    results.append((label, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + label + ("  " + str(detail) if detail else ""))


msg = lambda: agent.property("messageText")  # noqa: E731

wait(500)
check("首頁啟動", page() == 0)

# 1 模糊意圖 → 規則列出候選讓使用者挑
agent.setProperty("open", True)
say("我想查看飛行設定")
choices = prop(agent, "choices")
labels = [c["label_zh"] for c in choices]
check("「飛行設定」列出多個候選", len(choices) >= 3, labels)
shot("01_clarify_flight_settings")
flyview = [c for c in choices if c["id"] == "NAV_8_11"][0]
QMetaObject.invokeMethod(agent, "execute", Q_ARG("QVariant", flyview), Q_ARG("QVariant", "使用者選擇"))
wait()
check("選 Fly View 後切到系統設定第 11 子頁", page() == 8 and section(8) == 11, (page(), section(8)))
shot("02_system_flyview")

# 2 版面：從系統設定直接要求移動飛行畫面的模組 → 自動切到即時飛行再移動
before = None
say("把風速計移到左上角", 900)
w = mod("windGauge")
check("風速計移到左上角並避開任務進度條", page() == 1 and w and w["x"] == 24 and w["y"] >= 150, w)
say("小地圖放大一點", 700)
m = mod("miniView")
check("小地圖放大 1.25 倍且不超出畫面", m and m["w"] == 450 and m["h"] == 275 and m["y"] + m["h"] <= 1200, m)
say("隱藏底部遙測列", 700)
t = mod("telemetryBar")
check("底部遙測列隱藏", t and t["opacity"] == 0, t)
shot("03_layout_changed")

# 3 復原
say("復原", 700)
check("復原一步：遙測列回來", mod("telemetryBar")["opacity"] == 1)
say("復原兩步", 900)
# v4：換頁另算一步，復原兩步只退版面（小地圖、風速計），仍留在即時飛行
m = mod("miniView"); w = mod("windGauge")
check("再復原兩步：小地圖原尺寸、風速計回原位、仍在即時飛行", page() == 1 and m and m["w"] == 360 and w and w["x"] != 24, (page(), m, w))
say("復原", 900)
check("再復原一步：回到系統設定 Fly View", page() == 8 and section(8) == 11, (page(), section(8)))
say("重做", 900)
say("重做", 900)
w = mod("windGauge")
check("重做兩次：回到即時飛行且風速計在左上", page() == 1 and w and w["x"] == 24 and w["y"] >= 150, w)
say("全部復原", 900)
check("全部復原：回首頁", page() == 0, page())
shot("04_reset_all_home")
say("復原", 900)
w = mod("windGauge")
check("復原「全部復原」：回到即時飛行、風速計在左上", page() == 1 and w and w["x"] == 24 and w["y"] >= 150, (page(), w))
shot("05_undo_reset")

# 4 安全界線與權限
say("起飛")
check("「起飛」不執行、說明原因", page() == 1 and "不會送" in msg(), msg())
say("去用戶管理")
check("沒有權限的畫面不切換", page() == 1 and "權限" in msg(), msg())
shot("06_refuse_takeoff_or_denied")

# 5 模型路徑（假模型伺服器，只測流程，不代表真實模型表現）
win.close()
start({"GCS_LLM_BACKEND": "openai", "GCS_LLM_URL": MODEL_URL, "GCS_LLM_MODEL": "fake-model"})
wait(500)
say("我想查看飛行設定", 1500)
check("模型選 NAV_8_11 → 直接切到 Fly View", page() == 8 and section(8) == 11, (page(), section(8), msg()))
say("首頁", 600)
check("規則已確定時不問模型", len(FakeModel.calls) == 1, len(FakeModel.calls))
say("我想看看最近拍的東西", 1500)
check("規則沒對到 → 給模型全目錄 → 選媒體庫", page() == 12 and len(FakeModel.calls[-1]["candidates"]) > 50, (page(), msg()))
n = len(FakeModel.calls)
say("起飛", 600)
check("開模型時「起飛」也不送給模型", len(FakeModel.calls) == n and "不會送" in msg(), msg())
FakeModel.mode = "invalid"
say("我想查看飛行設定", 1500)
check("模型回不存在的 ID → 退回規則（列候選）", len(prop(agent, "choices")) >= 3 and page() == 12, msg())
shot("07_model_invalid_fallback")

server.shutdown()
ok = sum(1 for r in results if r[1])
print("\n%d/%d 通過" % (ok, len(results)))
if logs:
    print("QML 警告：")
    for line in logs:
        print("  " + line)
json.dump({"results": results, "qml_warnings": logs}, open(os.path.join(OUT, "harness_result.json"), "w"), ensure_ascii=False, indent=1)
sys.exit(0 if ok == len(results) else 1)
