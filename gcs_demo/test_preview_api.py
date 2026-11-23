"""ADR-0002 M1 預覽端點的固定案例（預覽端點演算法說明 v1 §5）。規則版，不需要真模型。
首次執行由 Claude 負責，結果與失敗原樣保留。"""
import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest

from . import commit_layer as cl
from .energy import Vehicle, Wind
from .planner import _to_ll
from .preview_api import PreviewServer, PreviewService, SessionFeeder

O = (24.0, 121.0)
TOKEN = "t" * 40


def ll(x, y):
    a, b = _to_ll(O, (x, y))
    return {"lat": a, "lon": b}


SQUARE = [ll(0, 0), ll(100, 0), ll(100, 100), ll(0, 100)]


class FakeSession:
    def __init__(self):
        self.lock = threading.Lock()
        self.mission = {"name": "測試", "home": {"id": "H", "lat": 24.0, "lon": 121.0}, "cruise_alt_m": 50,
                        "no_fly": [], "limits": {"max_altitude_m": 120}, "targets": []}
        self.wind = Wind()
        self.current_state = None
        self.run = self.alerts = self.report = self.replans = self.plan = self.active_event = None

    def vehicle(self):
        return Vehicle()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pv_")
        root = os.path.join(self.tmp, "store")
        cl.init_store(root)
        self.coord, _ = cl.boot(root)
        self.sess = FakeSession()
        self.feeder = SessionFeeder(self.sess, self.coord)
        self.feeder.poll()
        self.svc = PreviewService(self.coord, self.feeder, os.path.join(self.tmp, "ev", "p.jsonl"), boot_epoch=7)
        self.srv = PreviewServer(("127.0.0.1", 0), self.svc, TOKEN)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.ep = 0
        self.sid = self.call("/api/session/open", {})["data"]["session_id"]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self, method, path, body=None, headers=None, raw_body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": f"127.0.0.1:{self.port}", "Authorization": "Bearer " + TOKEN,
             "Content-Type": "application/json"}
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else b"")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, json.loads(r.read() or b"{}"), dict(r.getheaders()))
        c.close()
        return out

    def call(self, path, body, expect=200, **kw):
        self.ep += 1
        b = dict({"boot_epoch": 7, "request_epoch": self.ep}, **body)
        if path != "/api/session/open":
            b.setdefault("session_id", getattr(self, "sid", None))
        st, js, _ = self.raw("POST", path, b, **kw)
        self.assertEqual(st, expect, js)
        return js

    def preview(self, reserve=25):
        a = self.call("/api/area/submit", {"polygon": SQUARE})["data"]["area_ref"]
        r = self.call("/api/preview/generate", {"area_ref": a, "spacing_m": 20})["data"]["route_ref"]
        return self.call("/api/preview/verify", {"route_ref": r, "reserve_req_pct": reserve})["data"]


class HttpGuards(Base):
    def test_no_cors_headers(self):
        _, _, h = self.raw("POST", "/api/session/open", {"boot_epoch": 7, "request_epoch": 99})
        self.assertFalse(any(k.lower().startswith("access-control") for k in h))

    def test_cross_origin_rejected(self):
        st, js, _ = self.raw("POST", "/api/session/open", {"boot_epoch": 7, "request_epoch": 1},
                             headers={"Origin": "http://evil.example"})
        self.assertEqual((st, js["error"]["code"]), (403, "ORIGIN_DENIED"))

    def test_bad_host(self):
        st, js, _ = self.raw("POST", "/api/session/open", {"boot_epoch": 7, "request_epoch": 1},
                             headers={"Host": "evil:80"})
        self.assertEqual(st, 403)

    def test_missing_and_wrong_token(self):
        st, js, _ = self.raw("POST", "/api/session/open", {"boot_epoch": 7, "request_epoch": 1},
                             headers={"Authorization": None})
        self.assertEqual((st, js["error"]["code"]), (401, "AUTH_MISSING"))
        st, js, _ = self.raw("POST", "/api/session/open", {"boot_epoch": 7, "request_epoch": 1},
                             headers={"Authorization": "Bearer nope"})
        self.assertEqual((st, js["error"]["code"]), (401, "AUTH_INVALID"))

    def test_get_and_unknown_path(self):
        self.assertEqual(self.raw("GET", "/api/preview/get")[0], 405)
        self.assertEqual(self.raw("POST", "/api/nope", {})[0], 404)

    def test_body_too_large(self):
        st, _, _ = self.raw("POST", "/api/preview/get", raw_body=b"{" + b" " * 5000 + b"}")
        self.assertEqual(st, 413)

    def test_unknown_field_nonfinite_and_old_epoch(self):
        self.call("/api/preview/get", {"artifact_id": "x", "extra": 1}, expect=400)
        st, js, _ = self.raw("POST", "/api/preview/get",
                             raw_body=b'{"boot_epoch":7,"request_epoch":50,"session_id":"%s","artifact_id":"x","n":NaN}'
                             % self.sid.encode())
        self.assertEqual(st, 400)
        js = self.call("/api/preview/get", {"artifact_id": "x", "request_epoch": 0}, expect=409)
        self.assertEqual(js["error"]["code"], "EPOCH_STALE")


class Areas(Base):
    def test_drawn_area_without_label(self):
        d = self.call("/api/area/submit", {"polygon": SQUARE})["data"]
        self.assertTrue(d["name"].startswith("框選區域 "))
        self.assertEqual(d["checks"]["home_distance"], "OK")

    def test_drawn_concave_rejected_no_record(self):
        L = [ll(0, 0), ll(100, 0), ll(100, 50), ll(50, 50), ll(50, 100), ll(0, 100)]
        js = self.call("/api/area/submit", {"polygon": L}, expect=400)
        self.assertEqual(js["error"]["code"], "UNSUPPORTED_CONCAVE")
        self.assertEqual(self.svc.areas, {})

    def test_drawn_boundary_without_home(self):
        self.sess.mission.pop("home")
        d = self.call("/api/area/submit", {"polygon": SQUARE})["data"]
        self.assertEqual(d["checks"]["home_distance"], "PENDING")
        js = self.call("/api/preview/generate", {"area_ref": d["area_ref"], "spacing_m": 20}, expect=400)
        self.assertEqual(js["error"]["code"], "MISSING")

    def test_cross_session_area_ref_rejected(self):
        a = self.call("/api/area/submit", {"polygon": SQUARE})["data"]["area_ref"]
        other = self.call("/api/session/open", {})["data"]["session_id"]
        js = self.call("/api/preview/generate", {"area_ref": a, "spacing_m": 20, "session_id": other}, expect=403)
        self.assertEqual(js["error"]["code"], "AREA_BINDING_MISMATCH")


class Flow(Base):
    def _confirm(self, p):
        ch = self.call("/api/preview/apply_check", {"preview_ref": p["preview_ref"], "draft_id": "d1", "draft_rev": 1,
                                                    "target_slot_id": "home",
                                                    "target_generation": self.coord.word.current().root_gen})["data"]["check"]
        tok = self.call("/api/preview/presented", {"shown_hash": ch["shown_hash"], "apply_intent_id": ch["apply_intent_id"],
                                                   "target_slot_id": "home", "window_id": "w1", "frame_id": "f1"})["data"]
        return ch, tok["confirm_token"]

    def test_verify_uses_planned_100_without_telemetry(self):
        p = self.preview()
        self.assertEqual(p["takeoff_source"], "planned")
        self.assertEqual(p["evaluation"]["result"], "pass")

    def test_full_apply_and_idempotent_resend(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        body = {"target_slot_id": "home", "nonce": "n1", "apply_intent_id": ch["apply_intent_id"],
                "shown_hash": ch["shown_hash"], "confirm_token": tok}
        r1 = self.call("/api/preview/commit", body)["data"]
        self.assertEqual(r1["transaction"]["action"], "WRITE")
        r2 = self.call("/api/preview/commit", body)["data"]          # 回應遺失後重送
        self.assertEqual(r1, r2)
        self.assertIsNotNone(self.coord.word.current().route("home"))
        js = self.call("/api/preview/commit", dict(body, shown_hash="x" * 64), expect=400)
        self.assertEqual(js["error"]["code"], "NONCE_CONFLICT")

    def test_replayed_old_token_rejected(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        b = {"target_slot_id": "home", "nonce": "n1", "apply_intent_id": ch["apply_intent_id"],
             "shown_hash": ch["shown_hash"], "confirm_token": tok}
        self.call("/api/preview/commit", b)
        js = self.call("/api/preview/commit", dict(b, nonce="n2"), expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")

    def test_second_window_revokes_first_token(self):
        p = self.preview()
        ch1, tok1 = self._confirm(p)
        ch2, tok2 = self._confirm(p)
        js = self.call("/api/preview/commit", {"target_slot_id": "home", "nonce": "a", "apply_intent_id": ch1["apply_intent_id"],
                                               "shown_hash": ch1["shown_hash"], "confirm_token": tok1}, expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")
        r = self.call("/api/preview/commit", {"target_slot_id": "home", "nonce": "b", "apply_intent_id": ch2["apply_intent_id"],
                                              "shown_hash": ch2["shown_hash"], "confirm_token": tok2})["data"]
        self.assertEqual(r["transaction"]["action"], "WRITE")

    def test_battery_drop_before_write_blocks(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        self.sess.current_state = {"battery_pct": 20.0}
        r = self.call("/api/preview/commit", {"target_slot_id": "home", "nonce": "n1", "apply_intent_id": ch["apply_intent_id"],
                                              "shown_hash": ch["shown_hash"], "confirm_token": tok})["data"]
        self.assertEqual(r["transaction"]["action"], "BLOCK")
        self.assertIsNone(self.coord.word.current().route("home"))

    def test_significant_change_redisplays_then_limit(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        acts = []
        for i, batt in enumerate((90.0, 80.0, 70.0)):
            self.sess.current_state = {"battery_pct": batt}
            r = self.call("/api/preview/commit", {"target_slot_id": "home", "nonce": f"n{i}",
                                                  "apply_intent_id": ch["apply_intent_id"], "shown_hash": ch["shown_hash"],
                                                  "confirm_token": tok})["data"]
            acts.append(r["transaction"]["action"])
            if r["transaction"]["action"] == "REDISPLAY":
                ch = dict(ch, shown_hash=r["redisplay"]["shown_hash"])
                tok = self.call("/api/preview/presented", {"shown_hash": ch["shown_hash"], "apply_intent_id": ch["apply_intent_id"],
                                                           "target_slot_id": "home", "window_id": "w1", "frame_id": "f2"})["data"]["confirm_token"]
        self.assertEqual(acts, ["REDISPLAY", "REDISPLAY", "BLOCK"])
        self.assertIsNone(self.coord.word.current().route("home"))

    def test_new_nfz_blocks_with_new_preview_hint(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        self.sess.mission["no_fly"] = [{"id": "Z9", **ll(50, 30), "radius_m": 5.0}]
        r = self.call("/api/preview/commit", {"target_slot_id": "home", "nonce": "n1", "apply_intent_id": ch["apply_intent_id"],
                                              "shown_hash": ch["shown_hash"], "confirm_token": tok})["data"]
        self.assertEqual(r["transaction"]["action"], "BLOCK")
        self.assertIn("NFZ_CROSSING", r["transaction"]["reasons"])

    def test_undo_after_apply(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        self.call("/api/preview/commit", {"target_slot_id": "home", "nonce": "n1", "apply_intent_id": ch["apply_intent_id"],
                                          "shown_hash": ch["shown_hash"], "confirm_token": tok})
        g = self.coord.word.current().root_gen
        r = self.call("/api/preview/undo", {"target_slot_id": "home", "target_generation": g, "transaction_id": "x",
                                            "nonce": "u1"})["data"]
        self.assertEqual(r["transaction"]["action"], "WRITE")
        self.assertIsNone(self.coord.word.current().route("home"))


class Concurrency(Base):
    def test_ac6_busy_session_lock_and_no_session_writes(self):
        snap_before = json.dumps([self.sess.run, self.sess.alerts, self.sess.report, self.sess.replans,
                                  self.sess.current_state, self.sess.active_event], default=str)
        self.sess.lock.acquire()                    # 模擬 /api/start 長時間持鎖
        try:
            js = self.call("/api/area/submit", {"polygon": SQUARE}, expect=503)
            self.assertEqual(js["error"]["code"], "BUSY_RETRY")
        finally:
            self.sess.lock.release()
        self.preview()
        snap_after = json.dumps([self.sess.run, self.sess.alerts, self.sess.report, self.sess.replans,
                                 self.sess.current_state, self.sess.active_event], default=str)
        self.assertEqual(snap_before, snap_after)
        self.assertTrue(any(w >= 0.19 for w in self.feeder.waits))   # 等待時間有記錄


if __name__ == "__main__":
    unittest.main()
