"""New offline tests only. Apply patch to f1fa869 before unittest discovery.

No network, model, telemetry hardware or old research-script execution.
"""
import unittest
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
import json

from gcs_demo.alerts.core.units import (parse_current, parse_current_csv,
    check_current_range, CurrentLimits, energy_from_nominal)
from gcs_demo.alerts.core.freshness import Freshness, TRUE, FALSE, UNKNOWN
from gcs_demo.alerts.core.state_machine import (AlertEngine, merge_groups,
    NOTICE, WARNING, CRITICAL)
from gcs_demo.alerts.core.contract import validate
from gcs_demo.alerts.core.log import AlertLog, audit


class UnitsTests(unittest.TestCase):
    def test_sentinel_and_negative_current(self):
        self.assertIsNone(parse_current(-1, "SYS_STATUS"))
        self.assertIsNone(parse_current(-1, "BATTERY_STATUS"))
        amps = parse_current(-5, "SYS_STATUS")
        self.assertEqual(amps, -0.05)
        limits = CurrentLimits(-0.1, 100)
        self.assertEqual(check_current_range(amps, limits), "valid")
        self.assertEqual(check_current_range(-0.11, limits), "invalid")
        self.assertEqual(check_current_range(None, limits), "invalid")

    def test_csv_explicit_units(self):
        self.assertEqual(parse_current_csv(-1, "A"), -1)
        self.assertEqual(parse_current_csv(-5, "10mA"), -0.05)
        self.assertIsNone(parse_current_csv("--.--", "mA"))
        for value, unit in ((1, "guess"), (float("nan"), "A"), (True, "A")):
            with self.subTest(value=value, unit=unit), self.assertRaises(ValueError):
                parse_current_csv(value, unit)

    def test_capacity_fraction_once_and_no_fc_alias(self):
        energy = energy_from_nominal(100, 0.5, 0.9, fc_pct=80)
        self.assertEqual((energy.fc_pct, energy.nominal_ratio, energy.usable_wh), (80, 0.5, 45))
        self.assertEqual(energy_from_nominal(100, 0.5, 0.9).usable_wh, 45)
        with self.assertRaises(ValueError):
            energy_from_nominal(energy, 0.5, 0.9)


class FreshnessTests(unittest.TestCase):
    def test_missing_expired_and_invalid_are_local(self):
        f = Freshness()
        self.assertIsNone(f.get("wind", 0))
        f.put("position", (0, 0), 0, 0)
        f.put("voltage", 24, 0, 0)
        f.put("current", -0.5, 0, 0, valid=False)
        self.assertIs(f.evaluate(("voltage", "current"), 0, lambda x: True), UNKNOWN)
        self.assertIs(f.evaluate(("position",), 0, lambda x: True), TRUE)
        self.assertIs(f.evaluate(("position",), 3.001, lambda x: False), UNKNOWN)

    def test_ordering_count_and_sensed_age(self):
        f = Freshness()
        self.assertTrue(f.put("wind", 3, 1, 2))
        self.assertFalse(f.put("wind", 4, 1, 3))
        self.assertFalse(f.put("wind", 4, 0, 4))
        self.assertEqual(f.dropped["wind"], 2)
        self.assertIsNone(f.get("wind", 11.01))
        f.reset()
        self.assertIsNone(f.get("wind", 0))

    def test_ttl_override(self):
        f = Freshness({"wind": 1})
        f.put("wind", 3, 0, 0)
        self.assertIsNotNone(f.get("wind", 1))
        self.assertIsNone(f.get("wind", 1.001))


class StateTests(unittest.TestCase):
    def test_two_and_five_hz_same_confirmation_time(self):
        for hz in (2, 5):
            e, emitted = AlertEngine(), []
            for i in range(hz + 1):
                emitted += e.step("P4", i / hz, TRUE, WARNING)
            with self.subTest(hz=hz):
                self.assertEqual(len(emitted), 1)
                self.assertEqual(emitted[0]["output_t"], 1)
                self.assertEqual(emitted[0]["status"], "raise")

    def test_three_samples_required_even_after_one_second(self):
        e = AlertEngine()
        self.assertEqual(e.step("k", 0, TRUE, WARNING), [])
        self.assertEqual(e.step("k", 1, TRUE, WARNING), [])
        self.assertEqual(e.step("k", 1.1, TRUE, WARNING)[0]["status"], "raise")

    def test_critical_and_cooldown(self):
        for new_severity in (WARNING, CRITICAL):
            e = AlertEngine()
            self.assertEqual(e.step("k", 0, TRUE, CRITICAL)[0]["severity"], CRITICAL)
            for t in range(1, 12):
                resolved = e.step("k", t, FALSE)
            self.assertEqual(resolved[0]["status"], "resolve")
            emitted = []
            for t in (12, 12.5, 13):
                emitted += e.step("k", t, TRUE, new_severity)
            self.assertEqual(len(emitted), int(new_severity == CRITICAL))

    def test_higher_warning_bypasses_notice_cooldown(self):
        e = AlertEngine()
        for t in (0, 0.5, 1):
            e.step("k", t, TRUE, NOTICE)
        for t in range(2, 13):
            e.step("k", t, FALSE)
        out = []
        for t in (13, 13.5, 14):
            out += e.step("k", t, TRUE, WARNING)
        self.assertEqual(len(out), 1)

    def test_unknown_resets_clear_and_marks_expired_without_duplicate(self):
        e = AlertEngine()
        e.step("k", 0, TRUE, CRITICAL)
        e.step("k", 1, FALSE)
        self.assertEqual(e.step("k", 2, UNKNOWN), [])
        self.assertTrue(e.snapshot()["k"]["prediction_expired"])
        for t in range(3, 13):
            self.assertEqual(e.step("k", t, FALSE), [])
        self.assertEqual(e.step("k", 13, FALSE)[0]["status"], "resolve")

    def test_gap_cannot_clear_or_confirm(self):
        e = AlertEngine()
        e.step("k", 0, TRUE, CRITICAL)
        e.step("k", 1, FALSE)
        self.assertEqual(e.step("k", 20, FALSE), [])
        self.assertTrue(e.snapshot()["k"]["active"])
        other = AlertEngine()
        other.step("k", 0, TRUE, WARNING)
        other.step("k", 0.5, TRUE, WARNING)
        self.assertEqual(other.step("k", 10, TRUE, WARNING), [])

    def test_downgrade_ten_seconds_upgrade_immediate(self):
        e = AlertEngine()
        e.step("k", 0, TRUE, CRITICAL)
        for t in range(1, 11):
            self.assertEqual(e.step("k", t, TRUE, WARNING), [])
        down = e.step("k", 11, TRUE, WARNING)[0]
        self.assertEqual(down["severity"], WARNING)
        up = e.step("k", 11.1, TRUE, CRITICAL)[0]
        self.assertEqual(up["severity"], CRITICAL)
        self.assertGreater(up["alert_version"], down["alert_version"])

    def test_recommendation_each_option_has_own_continuity(self):
        e = AlertEngine()
        ids = ["C1", "C3", "C4"]
        e.step("k", 0, TRUE, CRITICAL, "C1", ids)
        for t, choice in ((1, "C4"), (2, "C3"), (3, "C4"),
                          (4, "C3"), (5, "C3"), (6, "C3")):
            self.assertEqual(e.step("k", t, TRUE, CRITICAL, choice, ids), [])
        self.assertEqual(e.step("k", 7, TRUE, CRITICAL, "C3", ids)[0]["recommendation"], "C3")

    def test_infeasible_recommendation_removed_immediately(self):
        e = AlertEngine()
        e.step("k", 0, TRUE, CRITICAL, "C1", ["C1", "C3"])
        out = e.step("k", 1, TRUE, CRITICAL, "C3", ["C3"])[0]
        self.assertEqual(out["status"], "update")
        self.assertIsNone(out["recommendation"])
        e.step("k", 2, TRUE, CRITICAL, "C3", ["C3"])
        e.step("k", 3, TRUE, CRITICAL, "C3", ["C3"])
        self.assertEqual(e.step("k", 4, TRUE, CRITICAL, "C3", ["C3"])[0]["recommendation"], "C3")

    def test_stale_critical_and_repeated_sample_rejected(self):
        e = AlertEngine()
        self.assertEqual(e.step("k", 10, TRUE, CRITICAL, sensed_t=0), [])
        e.step("q", 0, TRUE, WARNING)
        self.assertEqual(e.step("q", 0.5, TRUE, WARNING, sensed_t=0), [])
        self.assertEqual(e.dropped["q"], 1)

    def test_global_engine_sequence_and_deduplication(self):
        e = AlertEngine()
        a = e.step("a", 0, TRUE, CRITICAL)[0]
        b = e.step("b", 0, TRUE, CRITICAL)[0]
        self.assertEqual((a["engine_seq"], b["engine_seq"]), (1, 2))
        self.assertEqual(e.step("a", 1, TRUE, CRITICAL), [])


class MergeTests(unittest.TestCase):
    def row(self, pred, severity):
        return {"predictor": pred, "truth": TRUE, "severity": severity,
                "title": pred, "evidence": [{"id": pred}], "options": [pred]}

    def test_battery_highest_title_all_evidence_p1_options(self):
        merged = merge_groups([self.row("P1", WARNING), self.row("P2", CRITICAL)])
        self.assertEqual(len(merged), 1)
        row = merged[0]
        self.assertEqual((row["key"], row["severity"], row["title"]), ("battery", CRITICAL, "P2"))
        self.assertEqual(len(row["evidence"]), 2)
        self.assertEqual(row["options"], ["P1"])
        self.assertEqual(merge_groups([self.row("P2", CRITICAL)])[0]["options"], [])

    def test_wind_merge_requires_explicit_causality(self):
        rows = [self.row("P5", WARNING), self.row("P11", CRITICAL)]
        self.assertEqual(len(merge_groups(rows)), 2)
        self.assertEqual(len(merge_groups(rows, p11_wind_explained=True)), 1)


class ContractTests(unittest.TestCase):
    def setUp(self):
        def row(eid, option, metric, value):
            return {"id": eid, "option_id": option, "metric": metric, "value": value,
                    "unit": "%", "segment": "landing", "relation": "estimate"}
        self.facts = {"alert_version": 1, "allowed_ids": ["C1", "C4"], "evidence": [
            row("E1", "C1", "end_pct", 20), row("E2", "C4", "end_pct", 15),
            row("E3", "C1", "completion_pct", 70)]}
        self.current = {"active": True, "alert_version": 1, "feasible_ids": ["C1", "C4"]}
        self.output = {"alert_version": 1, "selected_id": "C1",
                       "sentences": ["C1落地電量20%。", "請操作員確認。"], "evidence_ids": ["E1"]}

    def test_grounded_output_accepted(self):
        self.assertIsNone(validate(self.output, self.facts, self.current))

    def test_wrong_option_value_rejected(self):
        self.output.update(sentences=["C1落地電量15%。", "請操作員確認。"], evidence_ids=["E1", "E2"])
        self.assertIsNotNone(validate(self.output, self.facts, self.current))

    def test_wrong_metric_value_rejected(self):
        self.output.update(sentences=["C1落地電量70%。", "請操作員確認。"], evidence_ids=["E1", "E3"])
        self.assertIsNotNone(validate(self.output, self.facts, self.current))

    def test_empty_allowed_requires_explicit_null(self):
        self.facts["allowed_ids"] = []
        self.assertIsNotNone(validate(self.output, self.facts, self.current))
        self.output["selected_id"] = None
        self.assertIsNone(validate(self.output, self.facts, self.current))
        del self.output["selected_id"]
        self.assertIsNotNone(validate(self.output, self.facts, self.current))

    def test_recheck_active_version_feasibility(self):
        for key, value in (("active", False), ("alert_version", 2), ("feasible_ids", [])):
            current = {**self.current, key: value}
            self.assertIsNotNone(validate(self.output, self.facts, current))

    def test_language_internal_fields_assertions_and_sentence_count(self):
        for text in ("一定安全。", "end_pct為20%。", "电量不足。", "第一句。第二句。"):
            output = {**self.output, "sentences": [text, "請操作員確認。"]}
            self.assertIsNotNone(validate(output, self.facts, self.current))

    def test_uncited_value_cannot_license_claim(self):
        self.output["evidence_ids"] = ["E2"]
        self.assertIsNotNone(validate(self.output, self.facts, self.current))

    def test_chinese_numerals_cannot_bypass_grounding(self):
        self.output["sentences"] = ["C1落地電量百分之九十九。", "請操作員確認。"]
        self.assertIsNotNone(validate(self.output, self.facts, self.current))


class LogTests(unittest.TestCase):
    def events(self):
        e = AlertEngine()
        return [e.step(key, 0, TRUE, CRITICAL)[0] for key in ("a", "b", "c")]

    def test_missing_row_and_core_defect_use_engine_denominator(self):
        events = self.events()
        rows = deepcopy(events)
        del rows[1]
        del rows[0]["predictor"]
        result = audit(events, rows)
        self.assertEqual(result["missing_sequences"], [2])
        self.assertEqual(result["core_valid_rate"], 1 / 3)

    def test_duplicate_cannot_inflate_rate_and_empty_undefined(self):
        events = self.events()
        result = audit(events, events + [events[0]])
        self.assertEqual(result["duplicate_sequences"], [1])
        self.assertEqual(result["core_valid_rate"], 2 / 3)
        self.assertIsNone(audit([], [])["core_valid_rate"])

    def test_extended_validity(self):
        events = self.events()
        rows = [{**e, "route_version": 1, "data_status": {"energy": "valid"},
                 "landing": {"median_pct": 20, "conservative_pct": 15, "optimistic_pct": 25},
                 "evidence": [{"id": "E1", "option_id": "C1", "metric": "end_pct", "value": 20,
                               "unit": "%", "segment": "landing", "relation": "estimate"}],
                 "reason_codes": [], "model_selection": None, "operator_disposition": None}
                for e in events]
        self.assertEqual(audit(events, rows)["extended_valid_rate"], 1)
        del rows[0]["data_status"]
        self.assertEqual(audit(events, rows)["extended_valid_rate"], 2 / 3)

    def test_jsonl_snapshots_do_not_allocate_sequence(self):
        events = self.events()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts.jsonl"
            log = AlertLog(path)
            for event in events:
                log.append(event)
            self.assertIsNotNone(log.snapshot(0, {}))
            self.assertIsNone(log.snapshot(9.99, {}))
            self.assertIsNotNone(log.snapshot(10, {}))
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 5)
            self.assertEqual(audit(events, rows)["core_valid_rate"], 1)
            self.assertNotIn("engine_seq", rows[-1])


if __name__ == "__main__":
    unittest.main()
