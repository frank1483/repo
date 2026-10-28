"""v3 驗收（v4 起換頁另算一步復原）：在 Qt 6.8.3（PySide6）離屏執行模擬殼層，跑一連串意圖並檢查換頁、版面與復原結果，順便存截圖。

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


wait(500)
agent.setProperty("open", True)
check("首頁啟動", page() == 0)
base_w = mod  # noqa

# A 一句兩步（規則）＋一次復原退整組
say("切到即時飛行然後把風速計移到左上角", 1500)
w = mod("windGauge")
check("兩步：切到即時飛行且風速計在左上", page() == 1 and w and w["x"] == 24, (page(), w, msg()))
say("復原", 900)
check("v4：第一次復原留在即時飛行、風速計回原位", page() == 1 and mod("windGauge")["x"] != 24, (page(), msg()))
say("復原", 900)
check("v4：第二次復原回首頁", page() == 0, (page(), msg()))
say("重做", 900)
say("重做", 1500)
w = mod("windGauge")
check("重做整組：回到即時飛行且風速計在左上", page() == 1 and w and w["x"] == 24, (page(), w))

# B 鎖定模組不可隱藏
say("隱藏指令區", 600)
check("鎖定的指令區不能隱藏", "鎖定" in msg() or "不可" in msg(), msg())

# C 相對位置：視窗縮小後仍在畫面內
win.setProperty("width", 1500); wait(600)
w = mod("windGauge")
area_w = 1500 - 220
check("視窗縮小後風速計仍在畫面內", w and w["x"] >= 0 and w["x"] + w["w"] <= area_w, (w, area_w))
win.setProperty("width", 1920); wait(600)
w = mod("windGauge")
check("視窗恢復後風速計回到左上", w and w["x"] == 24, w)

# D 命名版面
say("把現在的版面存成任務模式", 700)
check("存成任務模式", "任務模式" in msg(), msg())
say("切回預設版面", 1200)
w = mod("windGauge")
check("切回預設版面：風速計回原位", page() == 1 and w and w["x"] != 24, (page(), w, msg()))
say("切到任務模式", 1500)
w = mod("windGauge")
check("切到任務模式：風速計回左上", w and w["x"] == 24, (w, msg()))
say("復原", 1200)
w = mod("windGauge")
check("復原載入任務模式", w and w["x"] != 24, (w, msg()))
shot("v3_01_named_layout")

# E 模型：格式約束、400 退一次、500 不重送、多步、超過三步
win.close()
start({"GCS_LLM_BACKEND": "openai", "GCS_LLM_URL": MODEL_URL, "GCS_LLM_MODEL": "fake-model"})
wait(500); agent.setProperty("open", True)
FakeModel.mode = "select"; n0 = len(FakeModel.bodies)
say("我想查看飛行設定", 1500)
b = FakeModel.bodies[-1]
rf = b.get("response_format", {})
enum_ok = False
try:
    sch = rf["json_schema"]["schema"]
    enum_ok = "NAV_8_11" in json.dumps(sch)
except Exception:
    pass
check("送出 json_schema 且候選 ID 在 schema 內", rf.get("type") == "json_schema" and enum_ok, json.dumps(rf, ensure_ascii=False)[:200])
check("模型選 Fly View → 切過去", page() == 8 and section(8) == 11, (page(), section(8), msg()))

say("首頁", 800)
FakeModel.mode = "schema400"; n0 = len(FakeModel.bodies)
say("我想查看飛行設定", 2000)
types = [x.get("response_format", {}).get("type") for x in FakeModel.bodies[n0:]]
check("schema 400 → 改送 json_object 一次並成功", types == ["json_schema", "json_object"] and page() == 8, (types, page(), msg()))

say("首頁", 800)
FakeModel.mode = "http500"; n0 = len(FakeModel.bodies)
say("我想查看飛行設定", 1500)
check("HTTP 500 不重送、退回規則列候選", len(FakeModel.bodies) - n0 == 1 and len(prop(agent, "choices")) >= 3 and page() == 0, (len(FakeModel.bodies) - n0, page(), msg()))

FakeModel.mode = "steps2"
say("我想查看飛行設定", 1500)
p_after = (page(), section(page()))
check("模型回兩步 → 兩步都執行", p_after[0] in (5, 8, 3) and page() != 0, (p_after, msg()))
say("復原", 1200)
say("復原", 1200)
check("兩個換頁各算一步，復原兩次 → 回首頁", page() == 0, (page(), msg()))

FakeModel.mode = "steps4"
say("我想查看飛行設定", 1500)
check("模型回四步 → 無效、退回規則列候選", page() == 0 and len(prop(agent, "choices")) >= 3, (page(), msg()))

# F 過期結果與取消
FakeModel.mode = "slow"
say("我想查看飛行設定", 200)
QMetaObject.invokeMethod(shell, "agentGoTo", Q_ARG("QVariant", 5), Q_ARG("QVariant", -1))
wait(2200)
check("等待中換頁 → 結果丟棄", page() == 5 and "已改變" in msg(), (page(), msg()))
say("首頁", 800)
say("我想查看飛行設定", 200)
QMetaObject.invokeMethod(agent, "cancelWaiting")
wait(2200)
check("取消 → 不套用、可再輸入", page() == 0 and not agent.property("busy") and "取消" in msg(), (page(), msg()))
shot("v3_02_model_paths")

server.shutdown()
ok = sum(1 for r in results if r[1])
print("\n%d/%d 通過" % (ok, len(results)))
if logs:
    print("QML 警告：")
    for line in logs:
        print("  " + line)
json.dump({"results": results, "qml_warnings": logs}, open(os.path.join(OUT, "harness_v3_result.json"), "w"), ensure_ascii=False, indent=1)
sys.exit(0 if ok == len(results) else 1)
