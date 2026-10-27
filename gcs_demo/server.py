"""Demo 伺服器（只用標準庫）：python -m gcs_demo.server --port 8765
畫面：瀏覽器開 http://127.0.0.1:8765/
QGC/QML 之後可直接打同一組 JSON API（XMLHttpRequest）。
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import scenario as S
from .energy import Vehicle, Wind
from .llm import get_backend
from .planner import plan_mission, replan
from .report import make_report
from .sim import MissionRun
from .alert_bridge import AlertFeed, battery_raise

WEB = os.path.join(os.path.dirname(__file__), "web")


class Session:
    """單人 demo 的狀態。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.calib = 1.0
        self.reset()

    def reset(self):
        self.mission = S.mission()
        self.wind = Wind(**S.WIND)
        self.plan = None
        self.chosen = None
        self.run = None
        self.replans = []
        self.alerts = []

    def vehicle(self):
        return Vehicle(calib=self.calib)


SESSION = Session()


def _find(cands, cid):
    for c in cands:
        if c["id"] == cid:
            return c
    raise KeyError(cid)


def _alert_view(ev, cand):
    """告警引擎事件 → 畫面與報告用的精簡格式；航點編號換成目標名稱。"""
    names = [p["id"] for p in cand["path"][1:-1]]
    ex = ev.get("explain") or {}
    text = (ex.get("text") or {}).get("summary_zh") or f"{ev['title']}：{ev['value']}"
    for i in range(len(names), 0, -1):
        text = text.replace(f"WP{i}", f"WP{i}（{names[i-1]}）")
    return {"t_s": ev["t"], "key": ev["key"], "severity": ev["severity"], "title": ev["title"],
            "value": ev["value"], "lead_s": ev.get("lead_s"), "text_zh": text,
            "source": (ex.get("source") or "rule"), "level": "crit" if ev["severity"] <= 2 else "warn"}


def handle(path, body):
    s = SESSION
    with s.lock:
        if path == "/api/scenario":
            b = get_backend()
            return {"mission": s.mission, "wind": {"speed_mps": s.wind.speed_mps, "from_deg": s.wind.from_deg},
                    "vehicle": s.vehicle().to_dict(),
                    "llm": {"backend": b.name, "model": b.model, "url": b.url, "available": b.available()}}
        if path == "/api/reset":
            s.reset()
            return {"ok": True}
        if path == "/api/plan":
            if "wind" in body:
                s.wind = Wind(**body["wind"])
            if "calib" in body:
                s.calib = float(body["calib"])
            s.plan = plan_mission(s.mission, s.vehicle(), s.wind)
            s.run, s.replans, s.alerts = None, [], []
            return s.plan
        if path == "/api/start":
            s.chosen = _find(s.plan["candidates"], body["choice_id"])
            s.run = MissionRun(s.vehicle(), s.wind, S.TRUE_CALIB, S.WIND_EVENTS)
            feed = AlertFeed(s.mission["home"], s.chosen["path"], s.vehicle())
            # 飛到告警引擎發出「電量不足以飛完／即將到最晚返航點」的預測告警為止
            state = s.run.fly(s.chosen, on_tick=lambda rec, i: battery_raise(feed.tick(rec, i)) is not None)
            s.alerts = [_alert_view(e, s.chosen) for e in feed.events if e["type"] != "resolve"]
            out = {"state": state, "telemetry": s.run.log, "alerts": s.alerts}
            if state["done"]:
                out.update({"report": make_report(s.run, s.mission, s.chosen, [], s.alerts),
                            "planned_curve": _curve(s.chosen)})
                return out
            trig = battery_raise(feed.events) or {}
            w = s.run._wind_now()
            event = {"type": "wind", "speed_mps": w.speed_mps, "from_deg": w.from_deg,
                     "text_zh": f"預測告警「{trig.get('title', '電量')}：{trig.get('value', '')}」"}
            r = replan(s.mission, s.vehicle(), s.wind, state, event)
            s.replans.append(r)
            out.update({"alert": _alert_view(trig, s.chosen) if trig else None, "replan": r})
            return out
        if path == "/api/continue":
            r = s.replans[-1]
            cand = _find(r["candidates"], body["choice_id"])
            r["final_choice"] = body["choice_id"]
            n0 = len(s.run.log)
            state = s.run.fly(cand)
            rep = make_report(s.run, s.mission, s.chosen, s.replans, s.alerts)
            return {"state": state, "telemetry": s.run.log[n0:], "report": rep,
                    "planned_curve": _curve(s.chosen)}
        if path == "/api/apply_calib":
            s.calib = float(body["calib"])
            return {"calib": s.calib}
    raise KeyError(path)


def _curve(cand):
    t, out = 0.0, [{"t_s": 0, "pct": 100.0}]
    for leg in cand["legs"]:
        t += leg["time_s"]
        out.append({"t_s": round(t, 1), "pct": leg["pct_after"]})
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, data, ctype="application/json; charset=utf-8"):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(WEB, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if self.path.startswith("/api/"):
            return self._api(self.path, {})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        self._api(self.path, body)

    def _api(self, path, body):
        try:
            self._send(200, handle(path, body))
        except KeyError as exc:
            self._send(400, {"error": f"unknown {exc}"})
        except Exception as exc:  # demo：錯誤直接回給畫面
            self._send(500, {"error": repr(exc)})

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    b = get_backend()
    print(f"GCS 任務規劃 demo：http://{a.host}:{a.port}/  （LLM 後端：{b.name} {b.model or ''}）")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
