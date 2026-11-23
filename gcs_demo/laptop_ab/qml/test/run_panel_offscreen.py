"""AiAgent 面板離屏測試（PySide6，假服務、假 UI agent 狀態、假 missionController；不是 live）。
用法：QT_QPA_PLATFORM=offscreen python gcs_demo/laptop_ab/qml/test/run_panel_offscreen.py [A|B]
把面板與 UI agent 的 Core／Palette／HostPolicy 複製到暫存的 GCP/AiAgent、GCP/Agent，和正式 UI 裡的相對位置相同。"""
import json
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QEventLoop, QMetaObject, QObject, QUrl, Q_ARG, Q_RETURN_ARG
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine

PLAN = sys.argv[1] if len(sys.argv) > 1 else "A"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
PROPS = [
    {"index": 0, "action": "PROPOSE_HOME_ROUTE", "state": "PROPOSED", "supported": True, "label": "航線",
     "ui": {"kind": "route", "points": [{"lat": 24.0, "lon": 121.0, "alt": 50}, {"lat": 24.001, "lon": 121.0, "alt": 50},
                                        {"lat": 24.001, "lon": 121.001, "alt": 60}], "evaluation": {"result": "pass", "est_end_pct": 85.3}}},
    {"index": 1, "action": "UI_LAYOUT_PROPOSE", "state": "PROPOSED", "supported": True, "label": "風速計放大",
     "ui": {"id": "AB_LAY_windGauge_SCALE_125", "kind": "layout", "module": "windGauge", "op": "scale", "factor": 1.25, "label_zh": "風速計放大"}},
    {"index": 2, "action": "UI_LAYOUT_PROPOSE", "state": "PROPOSED", "supported": True, "label": "文字大",
     "ui": {"id": "AB_TEXT_SCALE_115", "kind": "text_scale", "value": 1.15, "label_zh": "全域文字大小改為「大」"}},
    {"index": 3, "action": "UI_THEME_PROPOSE", "state": "PROPOSED", "supported": True, "label": "淺色", "ui": {"kind": "theme", "theme": "light"}},
    {"index": 4, "action": "UI_LAYOUT_PROPOSE", "state": "PROPOSED", "supported": True, "label": "隱藏姿態儀（應被擋）",
     "ui": {"id": "AB_LAY_attitude_HIDE", "kind": "layout", "module": "attitude", "op": "hide", "label_zh": "隱藏姿態儀"}},
    {"index": 5, "action": "MODEL_SWITCH_PROPOSE", "state": "PROPOSED", "supported": True, "label": "模型",
     "ui": {"kind": "model", "model_id": "M001", "name": "gemma4:e2b"}},
    {"index": 6, "action": "UI_THEME_PROPOSE", "state": "PROPOSED", "supported": True, "label": "高對比", "ui": {"kind": "theme", "theme": "high_contrast"}},
    {"index": 7, "action": "X", "state": "PROPOSED", "supported": False, "label": "不支援", "ui": None},
]
VIEW = {"ok": True, "task_id": "t0001", "plan": PLAN, "text": "測試", "reply": "預覽驗算合格。", "reply_source": "fallback:format",
        "reply_template": "預覽驗算合格（模板）", "polish": {"calls": 1, "reason": "format"}, "polish_calls": 1,
        "directions": ["plan", "ui"], "dir_status": {"plan": "DONE", "ui": "DONE"},
        "steps": [{"direction": "plan", "action": "QUERY_AREA", "ids": ["A001"], "source": "rule"}], "replans": 0,
        "outcomes": {"route_preview": "合格"}, "manual": {"verdict": "ok", "refs": [{"manual": "qgc", "chunk_id": "c1", "title": "Compass"}]},
        "qa": None, "report": None, "flight_notice": None, "proposals": PROPS, "model_calls": 3, "embed_calls": 1,
        "t_pre_summary_s": 1.2, "elapsed_s": 1.5}
MARKS = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _j(self, o):
        raw = json.dumps(o, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._j({"ok": True, "plan": PLAN, "plan_name": "方案 " + PLAN, "mode": "fake", "model": None})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path.endswith("/mark"):
            MARKS.append(body)
            return self._j({"ok": True})
        self._j(VIEW)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Agent").mkdir()
    (tmp / "AiAgent").mkdir()
    (tmp / "test").mkdir()
    for f in ("GcpAgentCore.js", "GcpAgentThemePalette.js", "GcpAgentThemeColorMath.js", "GcpAgentThemeHostPolicy.js"):
        shutil.copy(REPO / "ui_agent/qml" / f, tmp / "Agent" / f)
    for f in ("GcpAiAgentPanel.qml", "GcpAiAgentRouteSink.qml", "GcpAiAgentCore.js", "GcpAiAgentBus.js"):
        shutil.copy(HERE.parent / f, tmp / "AiAgent" / f)
    (tmp / "AiAgent/GcpAiAgentBuild.js").write_text((HERE.parent / "GcpAiAgentBuild.js.in").read_text(encoding="utf-8")
                                                    .replace("@PLAN@", PLAN).replace("@PORT@", "1"), encoding="utf-8")
    shutil.copy(HERE / "AgentHarness.qml", tmp / "test/AgentHarness.qml")

    app = QGuiApplication(sys.argv[:1])
    eng = QQmlEngine()
    comp = QQmlComponent(eng, QUrl.fromLocalFile(str(tmp / "test/AgentHarness.qml")))
    root = comp.create()
    if root is None:
        print("\n".join(e.toString() for e in comp.errors()))
        return 2
    root.setProperty("api", f"http://127.0.0.1:{srv.server_address[1]}")

    def pump(sec):
        t = time.time() + sec
        while time.time() < t:
            app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(0.01)

    def wait(cond, sec=5):
        t = time.time() + sec
        while time.time() < t and not cond():
            pump(0.05)
        return cond()

    def tov(v):
        return v.toVariant() if hasattr(v, "toVariant") else v

    def call(obj, name, *args):
        if args:
            return QMetaObject.invokeMethod(obj, name, Q_RETURN_ARG("QVariant"), *[Q_ARG("QVariant", a) for a in args])
        return QMetaObject.invokeMethod(obj, name, Q_RETURN_ARG("QVariant"))

    panel = root.findChild(QObject, "aiAgentPanel")
    state = root.findChild(QObject, "fakeState")
    fails = []

    def check(name, ok, extra=""):
        print(("PASS " if ok else "FAIL ") + name + (" " + str(extra) if extra else ""))
        if not ok:
            fails.append(name)

    panel.setProperty("open", True)
    check("online", wait(lambda: panel.property("online")))
    call(root, "seed", 2)
    call(panel, "send", "測試")
    check("view", wait(lambda: tov(panel.property("view")) is not None))

    def prop(i):
        return tov(panel.property("view"))["proposals"][i]

    def msg():
        return panel.property("message")

    # 航線：切到規劃頁 → 寫 3 點 → 復原回 2 點
    call(panel, "apply", prop(0))
    check("route applied", wait(lambda: prop(0)["state"] == "APPLIED"), msg())
    check("route coords", len(tov(call(root, "coords"))) == 3 and tov(call(root, "coords"))[2][2] == 60, tov(call(root, "coords")))
    call(panel, "undo", prop(0))
    check("route undone", wait(lambda: prop(0)["state"] == "UNDONE") and len(tov(call(root, "coords"))) == 2, msg())
    # 版面：會切回即時飛行頁並放大
    call(panel, "apply", prop(1))
    check("layout applied", wait(lambda: prop(1)["state"] == "APPLIED"), msg())
    check("layout scale", tov(state.property("overrides")).get("windGauge", {}).get("scale") == 1.25, tov(state.property("overrides")))
    # 文字大小
    call(panel, "apply", prop(2))
    check("text scale", wait(lambda: prop(2)["state"] == "APPLIED") and abs(state.property("textScale") - 1.15) < 1e-9, msg())
    # 較早的版面不能越過較新的變更復原
    call(panel, "undo", prop(1))
    check("undo order guarded", prop(1)["state"] == "APPLIED" and "其他變更" in msg(), msg())
    call(panel, "undo", prop(2))
    check("text undone", prop(2)["state"] == "UNDONE" and abs(state.property("textScale") - 1.0) < 1e-9)
    call(panel, "undo", prop(1))
    check("layout undone", prop(1)["state"] == "UNDONE" and "windGauge" not in tov(state.property("overrides")))
    # 淺色主題（真的 Palette 對比檢查）
    call(panel, "apply", prop(3))
    check("light theme", wait(lambda: prop(3)["state"] in ("APPLIED", "APPLY_FAILED")), msg())
    check("light theme applied", prop(3)["state"] == "APPLIED" and tov(state.property("themeGroups")).get("text"), (msg(), tov(state.property("themeGroups"))))
    call(panel, "undo", prop(3))
    check("light undone", tov(state.property("themeGroups")) == {})
    # 鎖定元件
    call(panel, "apply", prop(4))
    check("locked blocked", prop(4)["state"] == "APPLY_FAILED" and "LOCKED_MODULE" in msg(), msg())
    # 模型與高對比
    call(panel, "apply", prop(5))
    check("model", prop(5)["state"] == "APPLIED" and panel.property("selectedModel") == "gemma4:e2b")
    call(panel, "apply", prop(6))
    check("high contrast", prop(6)["state"] == "APPLIED" and tov(state.property("themeGroups")).get("background") == "#000000")
    call(panel, "apply", prop(7))
    check("unsupported ignored", prop(7)["state"] == "PROPOSED")
    pump(0.3)
    states = [(m["index"], m["state"]) for m in MARKS]
    check("marks sent", (0, "APPLIED") in states and (0, "UNDONE") in states and (4, "APPLY_FAILED") in states, states)
    print(json.dumps({"plan": PLAN, "fails": fails, "marks": states}, ensure_ascii=False))
    srv.shutdown()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
