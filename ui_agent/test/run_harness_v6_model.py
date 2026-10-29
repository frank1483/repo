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


# ---------------------------------------------------------------- 假模型伺服器：OpenAI 與 Ollama 兩種路徑，可設定延遲
class FakeModel(BaseHTTPRequestHandler):
    delay = 0.0
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeModel.calls.append({"path": self.path, "body": body})
        time.sleep(FakeModel.delay)
        out = {"decision": "SELECT", "choice_id": "NAV_8_11", "reason_zh": "飛行畫面相關設定", "evidence_ids": []}
        content = json.dumps(out, ensure_ascii=False)
        if self.path.endswith("/api/chat"):
            payload = {"message": {"role": "assistant", "content": content}, "done": True}
        else:
            payload = {"choices": [{"message": {"role": "assistant", "content": content}}]}
        data = json.dumps(payload).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            pass

    def log_message(self, *a):
        pass


from http.server import ThreadingHTTPServer  # noqa: E402
server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE_URL = "http://127.0.0.1:%d" % server.server_address[1]

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





def wait(ms=400):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)



results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)))
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(detail) if not ok else ""))


def page():
    return shell.property("currentPage")


def notice():
    return agent.property("modelNotice") or ""


def say(text, ms=500):
    QMetaObject.invokeMethod(agent, "submit", Q_ARG("QVariant", text))
    wait(ms)


# 1 OpenAI 相容端點逾時：1.5 秒上限、假端延遲 4 秒
start({"GCS_LLM_BACKEND": "openai", "GCS_LLM_URL": BASE_URL + "/v1", "GCS_LLM_MODEL": "fake", "GCS_LLM_TIMEOUT_MS": "1500"})
wait(500)
FakeModel.delay = 4.0
p0 = page()
say("我想查看飛行設定", 2500)
check("逾時：顯示「模型未完成…已改用規則判斷」", "已改用規則判斷" in notice(), notice())
check("逾時：不自動套用後備、不出確認卡", page() == p0 and not agent.property("_confirmation"), (page(), agent.property("messageText")))
wait(3500)
check("逾時後晚到的回覆被忽略", page() == p0 and not agent.property("_confirmation"), page())
check("只送出一次請求", len(FakeModel.calls) == 1, len(FakeModel.calls))

# 2 Ollama 端點：format 帶本回合候選 schema
win.close()
FakeModel.delay = 0.0
FakeModel.calls = []
start({"GCS_LLM_BACKEND": "ollama", "GCS_LLM_URL": BASE_URL, "GCS_LLM_MODEL": "qwen2.5:3b"})
wait(500)
say("我想查看飛行設定", 2000)
call = FakeModel.calls[0] if FakeModel.calls else {}
fmt = call.get("body", {}).get("format")
check("Ollama 走 /api/chat", call.get("path") == "/api/chat", call.get("path"))
check("Ollama format 是含候選 enum 的 schema", isinstance(fmt, dict) and "NAV_8_11" in json.dumps(fmt), str(fmt)[:200])
check("Ollama 回覆後出確認卡（模型選的動作）", bool(agent.property("_confirmation")), agent.property("messageText"))
QMetaObject.invokeMethod(agent, "confirmIntent")
wait(800)
check("按「對」後切到系統設定", page() == 8, page())

# 3 面板設定優先於環境變數
ok = agent.setModelTimeout("2500") if hasattr(agent, "setModelTimeout") else None
QMetaObject.invokeMethod(agent, "setModelTimeout", Q_ARG("QVariant", "2500"))
check("面板設定 2500 ms 優先於環境變數", agent.resolvedModelTimeoutMs() == 2500 if hasattr(agent, "resolvedModelTimeoutMs") else False, "")

server.shutdown()
ok = sum(1 for r in results if r[1])
print("\n%d/%d 通過" % (ok, len(results)))
json.dump({"results": results, "qml_warnings": logs}, open(os.path.join(OUT, "harness_v6_model.json"), "w"), ensure_ascii=False, indent=1)
sys.exit(0 if ok == len(results) else 1)
