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

    def test_backend_for_none_stays_none(self):
        with mock.patch.dict(os.environ, {"GCS_LLM_URL_REPORT": "http://x/v1"}, clear=True):
            self.assertFalse(llm.backend_for("report").available())


if __name__ == "__main__":
    unittest.main()
