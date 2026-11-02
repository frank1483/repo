"""typed 編排的 LLM 說明入口與非同步補說明（MVP，契約 v0.3）。"""
import os
import threading
import time
import unittest
from unittest import mock

from gcs_demo import llm
from gcs_demo.alerts import explain, typed_explain as tx
from gcs_demo.test_typed_orchestration import feed, measurement, request


def raised_events():
    f = feed()
    out = None
    for i in range(6):
        out = f.tick(i, measurement(i, 90 if i < 4 else 0), request())
    return [e for e in out["events"] if e["type"] == "raise"]


class FakeBackend:
    name, model = "fake", "fake"

    def __init__(self, reply=None, delay=0.0, gate=None):
        self.reply, self.delay, self.gate, self.calls = reply, delay, gate, 0

    def complete_json(self, system, user, schema, timeout_s=None):
        self.calls += 1
        if self.gate:
            self.gate.wait(5)
        time.sleep(self.delay)
        data = self.reply(user) if callable(self.reply) else self.reply
        return {"ok": True, "data": data, "raw": "", "latency_s": self.delay, "error": None}


def good_reply(view):
    e1 = view["evidence"][0]
    return {"alert_version": view["alert_version"], "selected_id": None,
            "sentences": [f"{e1['text']}為 {e1['value']}。", "請操作員評估是否提早返航。"],
            "evidence_ids": [e1["id"]]}


class TypedViewTests(unittest.TestCase):
    def setUp(self):
        self.events = raised_events()
        self.view = tx.typed_view(self.events[0])

    def test_view_has_zh_labels_no_internal_keys(self):
        self.assertTrue(self.view["evidence"])
        facts = tx._facts(self.view)
        text = str(facts)
        for key in ("nominal_end_pct", "low_pct", "reserve_pct", "_key"):
            self.assertNotIn(key, text)
        self.assertEqual(facts["allowed_ids"], [])
        self.assertIn(self.view["severity_zh"], ("注意", "警告", "嚴重"))

    def test_resolve_and_inactive_not_explained(self):
        ev = dict(self.events[0], type="resolve")
        self.assertIsNone(tx.typed_view(ev))
        self.assertIsNone(tx.typed_view(dict(self.events[0], active=False)))

    def test_rule_text_passes_own_validator(self):
        self.assertIsNone(tx.validate(tx.rule_text(self.view), self.view))

    def test_valid_model_reply_used(self):
        r = tx.explain_typed(self.view, FakeBackend(good_reply(self.view)))
        self.assertEqual(r["source"], "llm", r["fallback_reason"])

    def _bad(self, **change):
        d = dict(good_reply(self.view), **change)
        return tx.explain_typed(self.view, FakeBackend(d))

    def test_rejections_fall_back_to_rule(self):
        cases = {
            "selected": self._bad(selected_id="C1"),
            "version": self._bad(alert_version="old"),
            "three": self._bad(sentences=["一。", "二。", "三。"]),
            "long": self._bad(sentences=["很" * 61, "二。"]),
            "evidence": self._bad(evidence_ids=["E9"]),
            "number": self._bad(sentences=["預估落地剩 37.5%。", "請注意。"]),
            "assert": self._bad(sentences=["這樣一定能安全返航。", "請注意。"]),
            "field": self._bad(sentences=["nominal_end_pct 偏低。", "請注意。"]),
        }
        for name, r in cases.items():
            self.assertEqual(r["source"], "rule", name)
            self.assertTrue(r["fallback_reason"], name)

    def test_backend_failure_and_exception_fall_back(self):
        class Boom(FakeBackend):
            def complete_json(self, *a, **k):
                raise OSError("connection refused")
        self.assertEqual(tx.explain_typed(self.view, Boom())["source"], "rule")
        none = tx.explain_typed(self.view, llm.LLMBackend())
        self.assertEqual(none["source"], "rule")


class AsyncTests(unittest.TestCase):
    def test_rule_shown_immediately_model_later(self):
        events = raised_events()
        backend = FakeBackend(lambda user: None, delay=0.3)
        ex = tx.TypedAlertExplainer(backend)
        views = {}
        backend.reply = lambda user: good_reply(next(v for v in views.values() if v["alert_version"] in user))
        for e in events:
            v = tx.typed_view(e)
            views[v["key"]] = v
        t0 = time.perf_counter()
        shown = ex.on_output({"events": events})
        self.assertLess(time.perf_counter() - t0, 0.1)          # 不等模型
        self.assertTrue(shown and all(s["result"]["source"] == "rule_pending" for s in shown))
        ex.close(wait=True)
        got = ex.poll()
        self.assertEqual(len(got), len(shown))
        self.assertTrue(all(g["result"]["source"] == "llm" for g in got))

    def test_stale_reply_discarded_after_resolve(self):
        events = raised_events()[:1]
        gate = threading.Event()
        view = tx.typed_view(events[0])
        ex = tx.TypedAlertExplainer(FakeBackend(good_reply(view), gate=gate))
        ex.on_output({"events": events})
        ex.on_output({"events": [dict(events[0], type="resolve", active=False)]})
        gate.set()
        ex.close(wait=True)
        self.assertEqual(ex.poll(), [])
        self.assertEqual(len(ex.async_.discarded), 1)

    def test_newer_version_supersedes(self):
        ev = raised_events()[0]
        gate = threading.Event()
        ex = tx.TypedAlertExplainer(FakeBackend(lambda user: None, gate=gate))
        v1, v2 = tx.typed_view(ev), tx.typed_view(dict(ev, sequence=99, type="update"))
        ex._backend.reply = lambda user: good_reply(v1 if v1["alert_version"] in user else v2)
        ex.on_output({"events": [ev]})
        ex.on_output({"events": [dict(ev, sequence=99, type="update")]})
        gate.set()
        ex.close(wait=True)
        got = ex.poll()
        self.assertEqual([g["version"] for g in got], [v2["alert_version"]])

    def test_legacy_explainer_non_blocking(self):
        ev = {"key": "battery_route", "t": 10, "type": "raise", "title": "電量", "value": "預估落地 5%",
              "evidence": [{"id": "E1", "text": "預估落地", "value": "5%"}],
              "candidates": [{"id": "C1", "label": "立即返航", "feasible": True, "end_pct": 25.0}],
              "rule_choice": "C1"}
        reply = {"decision": "SELECT", "choice_id": "C1", "reason_zh": "可行。", "evidence_ids": ["E1"],
                 "summary_zh": "預估落地 5%，建議立即返航。"}
        ex = tx.LegacyAlertExplainer(FakeBackend(reply, delay=0.3))
        t0 = time.perf_counter()
        r = ex(ev)
        self.assertLess(time.perf_counter() - t0, 0.1)
        self.assertEqual(r["source"], "rule_pending")
        ex.close(wait=True)
        self.assertEqual(ex.poll()[0]["result"]["source"], "llm")


class AlertFeedDefaultTests(unittest.TestCase):
    def test_alert_feed_default_is_async_and_poll_applies(self):
        from gcs_demo.alert_bridge import AlertFeed
        from gcs_demo.energy import load_airframe
        home = {"lat": 23.0, "lon": 120.0, "alt": 0}
        path = [home, {**home, "lat": 23.001, "alt": 30}, home]
        f = AlertFeed(home, path, load_airframe("x500"))
        self.assertIsInstance(f.explain_fn, tx.LegacyAlertExplainer)
        self.assertIsNone(AlertFeed(home, path, load_airframe("x500"), explain_fn=None).explain_fn)
        ev = {"key": "battery_route", "t": 3, "type": "raise", "title": "電量", "value": "預估落地 5%",
              "evidence": [{"id": "E1", "text": "預估落地", "value": "5%"}],
              "candidates": [{"id": "C1", "label": "立即返航", "feasible": True}], "rule_choice": "C1"}
        reply = {"decision": "SELECT", "choice_id": "C1", "reason_zh": "可行。", "evidence_ids": ["E1"],
                 "summary_zh": "預估落地 5%，建議立即返航。"}
        f.explain_fn = tx.LegacyAlertExplainer(FakeBackend(reply))
        ev["explain"] = f.explain_fn(ev)
        f.events.append(ev)
        self.assertEqual(ev["explain"]["source"], "rule_pending")
        f.explain_fn.close(wait=True)
        self.assertEqual(len(f.poll_explanations()), 1)
        self.assertEqual(ev["explain"]["source"], "llm")


class DefaultBackendTests(unittest.TestCase):
    def test_default_is_gateway(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            b = explain.get_backend()
        self.assertEqual(b.name, "openai")
        self.assertEqual(b.url, "http://127.0.0.1:8090/f/alerts/v1")
        self.assertEqual(b.model, "gemma4:e2b")

    def test_env_overrides_and_none_disables(self):
        with mock.patch.dict(os.environ, {"GCS_LLM_BACKEND": "none"}, clear=True):
            self.assertEqual(explain.get_backend().name, "none")
        env = {"GCS_LLM_URL": "http://h:1/v1", "GCS_LLM_MODEL": "m"}
        with mock.patch.dict(os.environ, env, clear=True):
            b = explain.get_backend()
        self.assertEqual((b.url, b.model), ("http://h:1/v1", "m"))


if __name__ == "__main__":
    unittest.main()
