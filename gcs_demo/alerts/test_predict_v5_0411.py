"""0411 adapter regressions: local fixtures, no model or hardware calls."""
from dataclasses import replace
import unittest

from .energy_api import default_vehicle
from .predict import Config, Finding, PredictiveAlertEngine
from .core import contract
from .test_display_binding_v5_0408 import view_for
from . import typed_explain as tx


def engine():
    return PredictiveAlertEngine([(100, 0, 60)], (0, 0, 0), default_vehicle(),
                                 Config(raise_ticks=99, clear_ticks=99))


def finding(active=True, severity=4, choice="C1", feasible=("C1", "C4")):
    return Finding("battery_route", active, severity=severity, title="電量",
                   candidates=[{"id": c, "feasible": c in feasible}
                               for c in ("C1", "C4")], rule_choice=choice)


class PredictSeconds0411(unittest.TestCase):
    def test_two_and_five_hz_wait_for_a_full_second(self):
        for times in ((0, .5, 1), (0, .2, .4, .6, .8, 1)):
            eng = engine()
            rows = [row for t in times for row in eng._debounce(t, finding())]
            self.assertEqual([(r["type"], r["t"]) for r in rows], [("raise", 1)])

    def test_critical_immediate_and_version_sequence(self):
        eng = engine()
        first = eng._debounce(0, finding(severity=2))[0]
        self.assertEqual((first["engine_seq"], first["alert_version"]), (1, 1))
        self.assertEqual(first["severity_zh"], "嚴重")
        self.assertEqual(first["sensed_t"], first["recv_t"])

    def test_clear_waits_ten_seconds_and_cooling_has_critical_exception(self):
        eng = engine()
        eng._debounce(0, finding(severity=2))
        rows = [r for t in range(1, 12) for r in eng._debounce(t, finding(False))]
        resolved = [r for r in rows if r["type"] == "resolve"]
        self.assertEqual([r["t"] for r in resolved], [11])
        self.assertEqual([r for t in (12, 12.5, 13) for r in eng._debounce(t, finding())], [])
        again = eng._debounce(14, finding(severity=2))[0]
        self.assertNotEqual(again["alert_id"], resolved[0]["alert_id"])
        self.assertGreater(again["engine_seq"], resolved[0]["engine_seq"])

    def test_unknown_resets_clear_and_marks_active_expired(self):
        eng = engine()
        eng._debounce(0, finding(severity=2))
        for t in range(1, 6):
            eng._debounce(t, finding(False))
        eng._unknown_all(6)
        self.assertTrue(eng.active()["battery_route"].prediction_expired)
        for t in range(7, 17):
            self.assertFalse(any(r["type"] == "resolve" for r in eng._debounce(t, finding(False))))
        self.assertEqual(eng._debounce(17, finding(False))[0]["type"], "resolve")

    def test_gap_does_not_accumulate_raise_time(self):
        eng = engine()
        rows = [r for t in (0, .2, 4, 4.5, 5) for r in eng._debounce(t, finding())]
        self.assertEqual([r["t"] for r in rows], [5])

    def test_downgrade_ten_seconds_upgrade_immediate(self):
        eng = engine()
        eng._debounce(0, finding(severity=2))
        for t in range(1, 11):
            self.assertEqual(eng._debounce(t, finding()), [])
            self.assertEqual(eng.active()["battery_route"].severity, 2)
        self.assertEqual(eng._debounce(11, finding())[0]["severity"], 4)
        self.assertEqual(eng._debounce(12, finding(severity=2))[0]["severity"], 2)

    def test_recommendation_waits_three_seconds(self):
        eng = engine()
        eng._debounce(0, finding(severity=2))
        for t in (1, 2, 3):
            self.assertEqual(eng._debounce(t, finding(severity=2, choice="C4")), [])
            self.assertEqual(eng.active()["battery_route"].rule_choice, "C1")
        row = eng._debounce(4, finding(severity=2, choice="C4"))[0]
        self.assertEqual((row["rule_choice"], row["alert_version"]), ("C4", 2))

    def test_infeasible_recommendation_withdrawn_immediately(self):
        eng = engine()
        eng._debounce(0, finding(severity=2))
        row = eng._debounce(1, finding(severity=2, choice="C4", feasible=("C4",)))[0]
        self.assertEqual(row["type"], "update")
        self.assertIsNone(row["rule_choice"])
        self.assertIsNone(eng.active()["battery_route"].rule_choice)

    def test_duplicate_and_reordered_do_not_mutate_active(self):
        eng = engine()
        eng._debounce(10, finding(severity=2))
        old = eng.active()["battery_route"]
        for t in (10, 9):
            self.assertEqual(eng._debounce(t, replace(finding(), title="錯誤")), [])
            self.assertEqual(eng.active()["battery_route"], old)

    def test_sequence_is_global_across_keys(self):
        eng = engine()
        a = eng._debounce(0, finding(severity=2))[0]
        b = eng._debounce(0, replace(finding(severity=2), key="wind_trend"))[0]
        self.assertEqual((a["engine_seq"], b["engine_seq"]), (1, 2))


class MetricBinding0411(unittest.TestCase):
    def check(self, text, values=None, cited=None):
        view = view_for("P1", values or {"nominal_end_pct": -1.0, "reserve_pct": 20})
        facts = tx._facts(view)
        reply = {"alert_version": facts["alert_version"], "selected_id": None,
                 "sentences": [text, "請操作員評估。"], "evidence_ids": cited or ["E1"]}
        return contract.validate(reply, facts, {"active": True,
                                 "alert_version": facts["alert_version"], "feasible_ids": []})

    def test_short_alias_and_compound_wrong_metric_rejected(self):
        for label in ("落地", "落地保留電量"):
            for value in ("-1.0%", "低於 0%（短缺 1.0%）"):
                self.assertIsNotNone(self.check(label + value + "。"))

    def test_two_metrics_rejected_even_when_second_is_uncited(self):
        for text in ("落地電量與保留電量-1.0%。",
                     "落地電量-1.0%與保留電量。",
                     "落地電量與保留電量低於 0%（短缺 1.0%）。",
                     "落地電量低於 0%（短缺 1.0%）與保留電量。"):
            self.assertIsNotNone(self.check(text))

    def test_known_uncited_metric_without_row_still_rejected(self):
        self.assertIsNotNone(self.check("落地電量與風速-1.0%。"))

    def test_correct_raw_display_and_separate_clauses_accepted(self):
        for text in ("預估落地電量（中值）-1.0%。",
                     "預估落地電量（中值）低於 0%（短缺 1.0%）。"):
            self.assertIsNone(self.check(text))
        self.assertIsNone(self.check("落地電量-1.0%，保留電量20.0%。", cited=["E1", "E2"]))
