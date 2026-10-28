"""v4 驗收：在 Qt 6.8.3（PySide6）離屏執行模擬殼層，跑一連串意圖並檢查換頁、版面與復原結果，順便存截圖。

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
    bodies = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = json.loads(body["messages"][1]["content"])
        ids = [c["id"] for c in user["candidates"]]
        FakeModel.calls.append(user)
        FakeModel.bodies.append(body)
        rf = (body.get("response_format") or {}).get("type")
        if FakeModel.mode == "schema400" and rf == "json_schema":
            return self.reply(400, {"error": "json_schema not supported"})
        if FakeModel.mode == "http500":
            return self.reply(500, {"error": "boom"})
        if FakeModel.mode == "slow":
            time.sleep(1.5)
        if FakeModel.mode == "steps2":
            navs = [i for i in ids if i.startswith("NAV_")]
            out = {"decision": "SELECT", "steps": [{"choice_id": navs[0]}, {"choice_id": navs[1]}], "reason_zh": "兩步", "evidence_ids": []}
            return self.reply(200, {"choices": [{"message": {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}}]})
        if FakeModel.mode == "steps4":
            out = {"decision": "SELECT", "steps": [{"choice_id": i} for i in ids[:4]], "reason_zh": "四步", "evidence_ids": []}
            return self.reply(200, {"choices": [{"message": {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}}]})
        if FakeModel.mode == "invalid":
            out = {"decision": "SELECT", "choice_id": "NAV_99", "reason_zh": "亂選", "evidence_ids": []}
        elif "飛行設定" in user["intent"]:
            out = {"decision": "SELECT", "choice_id": "NAV_8_11", "reason_zh": "飛行畫面相關設定", "evidence_ids": ["E1"]}
        elif "拍" in user["intent"] and "NAV_12" in ids:
            out = {"decision": "SELECT", "choice_id": "NAV_12", "reason_zh": "拍攝的照片在媒體庫", "evidence_ids": []}
        else:
            out = {"decision": "CLARIFY", "choice_id": "", "reason_zh": "不確定", "evidence_ids": []}
        self.reply(200, {"choices": [{"message": {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}}]})

    def reply(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


from http.server import ThreadingHTTPServer
server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
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


def theme_scale():
    t = engine.singletonInstance("QGroundControl.GCP", "GcpTheme")
    return t.property("font").property("textScale")


def toast_action():
    # 提示列物件有 action 屬性（"undo"／"redo"），按鈕文字由它決定
    for o in win.findChildren(QObject):
        if isinstance(o.property("action"), str) and o.property("opacity") is not None:
            return o.property("action")
    return None


def unsaved():
    return bool(engine.singletonInstance("QGroundControl.GCP", "GcpAgentState").property("hasUnsavedChanges"))


wait(500)
agent.setProperty("open", True)
check("首頁啟動", page() == 0)

# 1 自動換頁另算一步；提示列復原後顯示重做
say("把風速計移到左上角", 1500)
w = mod("windGauge")
check("首頁說移風速計 → 切到即時飛行並移到左上", page() == 1 and w and w["x"] == 24, (page(), w))
say("復原", 900)
w = mod("windGauge")
check("復原第 1 次：留在即時飛行、風速計回原位", page() == 1 and w and w["x"] != 24, (page(), w, msg()))
check("復原後提示列顯示「重做」", toast_action() == "redo", toast_action())
say("復原", 900)
check("復原第 2 次：回首頁", page() == 0, (page(), msg()))
say("重做", 900)
say("重做", 1200)
w = mod("windGauge")
check("重做兩次：回即時飛行且風速計在左上", page() == 1 and w and w["x"] == 24, (page(), w))
check("重做後提示列換回「復原」", toast_action() == "undo", toast_action())

# 2 最大／最小，不誤判成地圖設定
say("小地圖放到最大", 900)
m = mod("miniView")
check("小地圖放到最大 → 兩倍、仍在即時飛行", page() == 1 and m and m["w"] == 720, (page(), m, msg()))
say("小地圖縮到最小", 900)
m = mod("miniView")
check("小地圖縮到最小 → 一半", m and m["w"] == 180, (m, msg()))

# 3 全系統文字＋接續上一句
say("將所有字縮小", 700)
labels = [c["label_zh"] for c in prop(agent, "choices")]
check("「將所有字縮小」列出全系統文字選項並記住需求", any("文字" in l for l in labels) and agent.property("pendingText"), (labels, agent.property("pendingText")))
say("整個系統的", 900)
check("補一句「整個系統的」→ 全系統文字 0.85、清掉待補", abs(theme_scale() - 0.85) < 1e-6 and not agent.property("pendingText"), (theme_scale(), agent.property("pendingText"), msg()))
say("放大一點", 600)
p1 = agent.property("pendingText")
say("取消", 600)
check("說「取消」清掉待補需求", p1 and not agent.property("pendingText"), (p1, agent.property("pendingText"), msg()))

# 4 儲存與重開
check("有變更時顯示「未儲存」", unsaved())
say("儲存版面", 900)
check("儲存後「未儲存」消失", not unsaved(), msg())
say("風速計放大一點", 900)
check("儲存後再改 → 又顯示「未儲存」", unsaved())
shot("v4_01_before_restart")
win.close()
start({"GCS_LLM_BACKEND": "none"})
wait(800); agent.setProperty("open", True)
check("重開後停在首頁，文字比例套回 0.85", page() == 0 and abs(theme_scale() - 0.85) < 1e-6, (page(), theme_scale()))
say("切到即時飛行", 1200)
w = mod("windGauge"); m = mod("miniView")
check("重開後套回已儲存版面：風速計左上原尺寸、小地圖一半", w and w["x"] == 24 and w["w"] == 180 and m and m["w"] == 180, (w, m))
check("重開後沒有版面復原紀錄、也沒有未儲存變更", not unsaved(), unsaved())
shot("v4_02_after_restart")

ok = sum(1 for r in results if r[1])
print("\n%d/%d 通過" % (ok, len(results)))
if logs:
    print("QML 警告：")
    for line in logs:
        print("  " + line)
json.dump({"results": results, "qml_warnings": logs}, open(os.path.join(OUT, "harness_v4_result.json"), "w"), ensure_ascii=False, indent=1)
server.shutdown()
sys.exit(0 if ok == len(results) else 1)
