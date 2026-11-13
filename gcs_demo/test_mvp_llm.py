"""MVP 預設接閘道：功能專用網址、逾時與 --rules-only。"""
import os
import unittest
from unittest import mock

from . import llm
from . import server as srv


class MvpLlmDefaults(unittest.TestCase):
    def test_defaults_do_not_override_existing_env(self):
        env = {"GCS_LLM_MODEL": "other"}
        srv.apply_mvp_llm_defaults(False, env)
        self.assertEqual(env["GCS_LLM_MODEL"], "other")
        self.assertEqual(env["GCS_LLM_BACKEND"], "openai")
        self.assertEqual(env["GCS_LLM_URL"], "http://127.0.0.1:8090/f/mission/v1")
        self.assertEqual(env["GCS_LLM_URL_REPORT"], "http://127.0.0.1:8090/f/report/v1")

    def test_rules_only(self):
        env = {"GCS_LLM_BACKEND": "openai"}
        srv.apply_mvp_llm_defaults(True, env)
        self.assertEqual(env["GCS_LLM_BACKEND"], "none")

    def test_backend_for_report_uses_feature_url_and_timeout(self):
        env = {}
        srv.apply_mvp_llm_defaults(False, env)
        with mock.patch.dict(os.environ, env, clear=True):
            mission, report = llm.backend_for("mission"), llm.backend_for("report")
        self.assertEqual(mission.url, "http://127.0.0.1:8090/f/mission/v1")
        self.assertEqual(report.url, "http://127.0.0.1:8090/f/report/v1")
        self.assertEqual(report.model, "gemma4:e2b")
        self.assertEqual(report.timeout_s, 90.0)
        self.assertFalse(hasattr(mission, "timeout_s"))

    def test_backend_for_alerts_uses_alerts_url(self):
        env = {}
        srv.apply_mvp_llm_defaults(False, env)
        with mock.patch.dict(os.environ, env, clear=True):
            alerts = llm.backend_for("alerts")
        self.assertEqual(alerts.url, "http://127.0.0.1:8090/f/alerts/v1")
        self.assertEqual(alerts.model, "gemma4:e2b")

    def test_backend_for_none_stays_none(self):
        with mock.patch.dict(os.environ, {"GCS_LLM_URL_REPORT": "http://x/v1"}, clear=True):
            self.assertFalse(llm.backend_for("report").available())


class AlertExplanationsArriveLater(unittest.TestCase):
    def test_start_shows_pending_then_poll_fills_in(self):
        import time
        from copy import deepcopy
        with mock.patch.dict(os.environ, {"GCS_LLM_BACKEND": "none"}):
            srv.SESSION.reset()
            try:
                p = srv.handle("/api/plan", {})
                r = srv.handle("/api/start", {"choice_id": p["pick"]["choice_id"] or p["rule_choice"],
                                              "mission_version": p["mission_version"]})
                self.assertTrue(r["alerts"])
                self.assertTrue(all(a["source"] in ("rule_pending", "rule") for a in r["alerts"]))
                original = deepcopy(srv.SESSION.feed.events)
                for _ in range(50):
                    out = srv.handle("/api/alerts", {})
                    if not out["pending"]:
                        break
                    time.sleep(0.1)
                self.assertFalse(out["pending"])
                self.assertEqual({a["source"] for a in out["alerts"]}, {"rule"})
                ids = [a["alert_id"] for a in out["alerts"]]
                self.assertTrue(all(ids))
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(srv.SESSION.feed.events[:len(original)], original)
            finally:
                srv.SESSION.reset()


if __name__ == "__main__":
    unittest.main()
