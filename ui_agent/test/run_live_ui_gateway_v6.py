"""UI agent 接真模型的冒煙測試（MVP，llm_contract v0.3）。只準備，由使用者同意後在 PC 跑一次。

做什麼：在 Qt 離屏模擬殼層（test/harness/Main.qml）載入真正的 GcpAgentOverlay，
經共用 LLM 閘道（預設 http://127.0.0.1:8090/f/ui/v1，openai 模式，gemma4:e2b）送 10 句意圖，
每句記錄規則結果、模型回覆、是否退回規則、確認卡、最後畫面與延遲。
不送任何飛行指令，不碰真機；模擬殼層只有假畫面。

前提：
  1. 閘道已啟動：python -m gcs_demo.llm_gateway（後面接 Ollama gemma4:e2b）
  2. Python 有 PySide6 6.8.x
用法：
  python -I ui_agent/test/run_live_ui_gateway_v6.py <新的輸出資料夾> [閘道網址] [模型名]
輸出：<輸出資料夾>/live_results.json、decisions.jsonl、screens/*.png、inputs.json、versions.json
規則：跑一次就好，保留首次結果；輸出資料夾必須不存在。
"""
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QMetaObject, QObject, Q_ARG, QUrl, qVersion  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
QML_DIR = os.path.join(HERE, "..", "qml")
if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(2)
OUT = os.path.abspath(sys.argv[1])
URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8090/f/ui/v1"
MODEL = sys.argv[3] if len(sys.argv) > 3 else "gemma4:e2b"
if os.path.exists(OUT):
    print("輸出資料夾已存在，為保留首次結果不覆寫：", OUT)
    sys.exit(2)
os.makedirs(os.path.join(OUT, "screens"))

# 10 句：換頁、版面、多步、模型候選、CLARIFY、復原、重做、飛行指令（應拒絕）
INTENTS = [
    {"id": "L01", "text": "我想看電池的保護設定", "expect": "nav", "note": "換頁，規則或模型選電池失效保護"},
    {"id": "L02", "text": "把風速計放大一點", "expect": "layout", "note": "單一版面動作"},
    {"id": "L03", "text": "復原", "expect": "undo", "note": "復原上一步"},
    {"id": "L04", "text": "重做", "expect": "redo", "note": "重做"},
    {"id": "L05", "text": "去設定", "expect": "clarify", "note": "泛稱設定 → CLARIFY"},
    {"id": "L06", "text": "先回首頁再打開告警中心", "expect": "multi", "note": "多步，出確認卡"},
    {"id": "L07", "text": "我想調整飛行畫面相關的東西", "expect": "model", "note": "規則不確定，交給模型挑"},
    {"id": "L08", "text": "把小地圖移到右上角", "expect": "layout", "note": "移動版面"},
    {"id": "L09", "text": "全部復原", "expect": "reset", "note": "整串還原"},
    {"id": "L10", "text": "幫我起飛", "expect": "hold", "note": "飛行指令，必須拒絕"},
]
WAIT_S = 45  # 閘道 ui 預算 20 s，agent 逾時預設 60 s；每句最多等 45 s 後記錄現況

work = tempfile.mkdtemp(prefix="agent_live_")
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


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


sources = {f: sha(os.path.join(QML_DIR, f)) for f in sorted(os.listdir(QML_DIR))}
sources["test/run_live_ui_gateway_v6.py"] = sha(os.path.abspath(__file__))
sources["test/harness/Main.qml"] = sha(os.path.join(HERE, "harness", "Main.qml"))
json.dump({"url": URL, "model": MODEL, "intents": INTENTS, "wait_s": WAIT_S},
          open(os.path.join(OUT, "inputs.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump({"qt": qVersion(), "python": sys.version, "platform": platform.platform(), "sources_sha256": sources},
          open(os.path.join(OUT, "versions.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

app = QGuiApplication(sys.argv)
app.setOrganizationName("agent-live-%d" % os.getpid())  # 設定寫到一次性位置，不動使用者設定
app.setApplicationName("live")
warnings = []
engine = QQmlApplicationEngine()
engine.addImportPath(work)
engine.rootContext().setContextProperty("harnessEnv", {
    "GCS_LLM_BACKEND": "openai", "GCS_LLM_URL": URL, "GCS_LLM_MODEL": MODEL, "GCS_LLM_TIMEOUT_MS": "30000"})
engine.warnings.connect(lambda ws: [warnings.append(w.toString()) for w in ws])
engine.load(QUrl.fromLocalFile(os.path.join(work, "Main.qml")))
if not engine.rootObjects():
    print("QML 載入失敗", warnings)
    sys.exit(2)
win = engine.rootObjects()[0]
shell = win.findChild(QObject, "shell")
agent = win.findChild(QObject, "agent")
log = []
agent.decisionLogged.connect(lambda e: log.append(e.toVariant() if hasattr(e, "toVariant") else e))


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_idle(limit):
    t0 = time.time()
    pump(0.2)
    while agent.property("busy") and time.time() - t0 < limit:
        pump(0.05)
    pump(0.3)
    return time.time() - t0


def jsonable(v):
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


rows = []
for item in INTENTS:
    start_log = len(log)
    page_before = shell.property("currentPage")
    t0 = time.time()
    QMetaObject.invokeMethod(agent, "submit", Q_ARG("QVariant", item["text"]))
    waited = wait_idle(WAIT_S)
    card = agent.property("_confirmation")
    card_info = None
    if card:
        card_info = jsonable(card.toVariant() if hasattr(card, "toVariant") else card)
        win.grabWindow().save(os.path.join(OUT, "screens", item["id"] + "_card.png"))
        QMetaObject.invokeMethod(agent, "confirmIntent")  # 冒煙測試：卡片一律按「對」，記錄卡片內容
        wait_idle(10)
    win.grabWindow().save(os.path.join(OUT, "screens", item["id"] + ".png"))
    rows.append({
        "id": item["id"], "text": item["text"], "expect": item["expect"], "note": item["note"],
        "page_before": page_before, "page_after": shell.property("currentPage"),
        "seconds": round(time.time() - t0, 2), "busy_wait_s": round(waited, 2),
        "still_busy": bool(agent.property("busy")),
        "confirmation_card": card_info,
        "message": agent.property("messageText"), "model_notice": agent.property("modelNotice"),
        "decisions": [jsonable(e) for e in log[start_log:]],
    })
    print(item["id"], item["text"], "→ page", rows[-1]["page_after"], "|", rows[-1]["model_notice"] or "", "|",
          rows[-1]["message"])

with open(os.path.join(OUT, "decisions.jsonl"), "w", encoding="utf-8") as fh:
    for e in log:
        fh.write(json.dumps(jsonable(e), ensure_ascii=False) + "\n")
summary = {"total": len(rows), "qml_warnings": warnings, "rows": rows,
           "note": "冒煙測試：記錄真模型經閘道的行為，不判定論文成績；首次結果保留。"}
json.dump(summary, open(os.path.join(OUT, "live_results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(json.dumps({"total": len(rows), "qml_warnings": len(warnings), "out": OUT}, ensure_ascii=False))
