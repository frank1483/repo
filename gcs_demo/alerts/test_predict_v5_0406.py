"""0406 partial wiring regressions. Fixtures only; no model/hardware IO."""
import unittest
from unittest.mock import patch

from . import typed_explain as tx
from .core import contract
from .display import landing_pct_text
from .energy_api import default_vehicle, Wind
from .predict import PredictiveAlertEngine, Telemetry, Finding


def engine():
    return PredictiveAlertEngine([(100, 0, 60)], (0, 0, 0), default_vehicle())


class Qualification0406(unittest.TestCase):
    def test_first_retention_loss_recovery_and_independent_options(self):
        eng = engine()
        for pct, expected in ((20, True), (20, True), (19.99, False),
                              (20, False), (21.99, False), (22, True), (20, True)):
            self.assertEqual(eng._is_feasible(pct, "C1"), expected)
        self.assertTrue(eng._is_feasible(20, "C4"))
        eng._active["battery_route"] = Finding("battery_route", True)
        self.assertTrue(eng._is_feasible(20, "C6"))

    def test_invalid_does_not_rewrite_qualification_memory(self):
        eng = engine()
        self.assertTrue(eng._is_feasible(20, "C1"))
        for raw in (float("nan"), float("inf"), None, True):
            self.assertFalse(eng._is_feasible(raw, "C1"))
            self.assertTrue(eng._is_feasible(20, "C1"))

    def test_advisory_options_do_not_share_battery_ids(self):
        eng = engine()
        self.assertFalse(eng._is_feasible(19, "C2"))
        self.assertTrue(eng._is_feasible(20, "wind_trend:C2"))
        self.assertTrue(eng._is_feasible(20, "link_route:C2"))
        self.assertFalse(eng._is_feasible(21.9, "C2"))

    def test_candidates_use_their_own_ids(self):
        eng = engine()
        tm = Telemetry(0, (0, 0, 60), (0, 0, 0), 50, 22, 10, 0, 6, 0, 95, Wind(0, 0))
        self.assertFalse(eng._is_feasible(19, "C1"))
        # Every candidate has the same 21% estimate, isolating qualification memory.
        walk = [(0, 0, 0, 0), (1, 0, 0, 0)]
        with patch.object(eng, "_walk", return_value=walk), patch(
                "gcs_demo.alerts.predict.leg_energy", return_value={"energy_wh": 0}):
            cands = eng._candidates(tm, [(0, 0, 60), (100, 0, 60)], walk,
                                    eng.v.battery_wh * .21, 0, None, tm.wind)
        by_id = {c["id"]: c for c in cands}
        self.assertFalse(by_id["C1"]["energy_feasible"])
        self.assertTrue(by_id["C4"]["energy_feasible"])
        self.assertFalse(by_id["C5"]["feasible"])  # unknown landing environment


class Landing0406(unittest.TestCase):
    def test_display_preserves_negative_estimate_and_small_shortage(self):
        self.assertEqual(landing_pct_text(-1), "低於 0%（短缺 1.0%）")
        self.assertEqual(landing_pct_text(-.001), "低於 0%（短缺 小於 0.1%）")
        self.assertEqual(landing_pct_text(0), "0.0%")
        self.assertEqual(landing_pct_text(22), "22.0%")

    def test_predict_rule_value_has_shortage_and_signed_evidence(self):
        eng = engine()
        tm = Telemetry(0, (0, 0, 60), (0, 0, 0), 10, 22, 10, 0, 6, 0, 95, Wind(0, 0))
        walk = [(0, 0, 0, 0), (1, eng.v.battery_wh * .11, 10, 0)]
        with patch.object(eng, "_walk", return_value=walk), patch.object(eng, "_candidates", return_value=[]):
            findings = eng._battery_route(tm, eng.v.battery_wh * .1, "soc", None)
        self.assertIn("低於 0%（短缺 1.0%）", findings[0].value)
        self.assertLess(eng.last_state["end_pct"], 0)
        self.assertEqual(findings[0].evidence[0]["value"], "-1.0%")

    def test_typed_rule_display_retains_canonical_numeric_value(self):
        view = tx.typed_view({"key": "P1", "predictor": "P1", "type": "raise", "active": True,
                              "sequence": 1, "mission_version": "m1", "severity": 4,
                              "evidence": [{"value": {"nominal_end_pct": -1.0}}]})
        self.assertEqual(view["evidence"][0]["value"], "-1.0%")
        self.assertIn("低於 0%（短缺 1.0%）", tx.rule_text(view)["sentences"][0])


class Categorical0406(unittest.TestCase):
    def fixture(self, **extra):
        row = {"id": "E1", "option_id": None, "metric": "generic_probe_identity",
               "value": "A7", "unit": "", "segment": None, "relation": "observed",
               "text": "回程探查點", "value_kind": "categorical_id", **extra}
        facts = {"alert_version": 1, "allowed_ids": [], "evidence": [row]}
        answer = {"alert_version": 1, "selected_id": None,
                  "sentences": ["回程探查點為 A7。", "請操作員評估。"], "evidence_ids": ["E1"]}
        return answer, facts, {"active": True, "alert_version": 1, "feasible_ids": []}

    def test_flag_allows_predictor_independent_categorical_ids(self):
        self.assertIsNone(contract.validate(*self.fixture()))

    def test_old_metric_name_alone_does_not_grant_an_exception(self):
        args = self.fixture(metric="first_sampled_infeasible_id")
        del args[1]["evidence"][0]["value_kind"]
        self.assertIsNotNone(contract.validate(*args))

    def test_flag_keeps_context_citation_unit_and_option_guards(self):
        for extra in ({"option_id": "C1"}, {"unit": "A"}, {"value_kind": "number"},
                      {"value": "B7"}, {"text": "另一探查點"}):
            with self.subTest(extra=extra):
                self.assertIsNotNone(contract.validate(*self.fixture(**extra)))
        for text in ("回程探查點為 A7 SE。", "回程探查點為 A7 5。", "探查點為 A7。"):
            args = self.fixture()
            args[0]["sentences"][0] = text
            self.assertIsNotNone(contract.validate(*args))


if __name__ == "__main__":
    unittest.main()
