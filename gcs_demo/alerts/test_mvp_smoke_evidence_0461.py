"""New 0461 controls. Claude owns first Python execution and keeps its result."""
from copy import deepcopy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .core.contract import validate
from .core.ranked_facts import fact, option_evidence
from . import mvp_smoke, sim
from .test_ranked_facts_0455 import engine, finding, candidate


class Evidence0461Tests(unittest.TestCase):
    def test_merge_exact_rows_keeps_first_id_and_both_source_times(self):
        first = fact("E1", "目前風速", "wind_speed", "3.2", "m/s", "current",
                     source_predictor="P1", source_evidence_id="E7", sensed_t=1., recv_t=2.)
        second = dict(first, id="E9", source_predictor="P2", sensed_t=3., recv_t=4.)
        source = [first, second]
        before = deepcopy(source)
        rows = option_evidence(source, [], "battery")
        self.assertEqual(source, before)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "E1")
        self.assertEqual(rows[0]["members"], ["P1", "P2"])
        self.assertEqual([x["sensed_t"] for x in rows[0]["member_sources"]], [1., 3.])

    def test_rounding_does_not_merge_distinct_raw_measurements(self):
        rows = option_evidence([
            fact("E1", "風速", "wind_speed", 3.21, "m/s", "current"),
            fact("E2", "風速", "wind_speed", 3.22, "m/s", "current"),
            fact("E3", "風速", "wind_speed", 3.21, "m/s", "remaining_route")], [], "wind")
        self.assertEqual(len(rows), 3)
        self.assertEqual([e["value"] for e in rows], ["3.2"] * 3)
        self.assertEqual([e["raw_value"] for e in rows], [3.21, 3.22, 3.21])

    def test_display_precision_and_option_names(self):
        rows = option_evidence([
            fact("E1", "電量", "end_pct", "18.632%", "%", "route", option_id="C3", raw_value=18.632),
            fact("E2", "能量", "usable_wh", 123.7, "Wh", "current"),
            fact("E3", "倍率", "calibration_ratio", 1.2367, "倍", "current")],
            [dict(candidate("C3", 18.632), label="飛完 WP13 後返航")], "battery")
        self.assertEqual([e["value"] for e in rows[:3]], ["18.6%", "124", "1.24"])
        self.assertEqual(rows[0]["raw_value"], 18.632)
        self.assertTrue(all(e["text"].startswith("C3 飛完 WP13 後返航：")
                            for e in rows if e["option_id"] == "C3"))

    def test_rounded_number_binds_and_raw_precision_is_rejected(self):
        eng = engine()
        row = eng._debounce(0., finding([candidate("C1", 28.632)], "C1"))[0]
        e = next(e for e in row["evidence"] if e.get("option_id") == "C1" and e["metric"] == "end_pct")
        self.assertIn("C1", row["allowed_ids"])
        reply = {"alert_version": row["alert_version"], "selected_id": "C1",
                 "sentences": ["C1 預估落地電量 28.6%。", "請操作員確認。"], "evidence_ids": [e["id"]]}
        self.assertIsNone(validate(reply, row, eng.current_state("battery")))
        reply["sentences"][0] = "C1 預估落地電量 28.632%。"
        self.assertIsNotNone(validate(reply, row, eng.current_state("battery")))

    def test_seconds_and_degrees_round_display_and_keep_raw_values(self):
        values = [(57.35163646142176, "s", "57"),
                  (0.8333333333228379, "s", "1"),
                  (263.169, "s", "263"), (59.499, "s", "59"),
                  (123.7, "°", "124"), (-12.7, "°", "-13"),
                  (0.0, "°", "0"), (57.0, "s", "57")]
        for raw, unit, expected in values:
            for suffixed in (False, True):
                with self.subTest(raw=raw, unit=unit, suffixed=suffixed):
                    value = str(raw) + unit if suffixed else raw
                    source = fact("E1", "量測", "measurement", value, unit, "current")
                    before = deepcopy(source)
                    row = option_evidence([source], [], "wind")[0]
                    self.assertEqual(row["value"], expected + (unit if suffixed else ""))
                    self.assertEqual(row["raw_value"], raw)
                    self.assertEqual(source, before)

    def test_sim_defaults_and_explicit_capacity_forwarding(self):
        from .predict import PredictiveAlertEngine
        for supplied, expected in (({}, True), ({"capacity_check": False}, False)):
            with patch.object(sim, "PredictiveAlertEngine", wraps=PredictiveAlertEngine) as ctor:
                sim.run(max_t=0, **supplied)
            self.assertIs(ctor.call_args.kwargs["capacity_check"], expected)

    def test_typed_smoke_is_p1_p2_only(self):
        outputs = mvp_smoke._typed_outputs()
        self.assertTrue(any(e["type"] == "raise" for o in outputs for e in o["events"]))
        for out in outputs:
            self.assertEqual(set(out["predictors"]), {"P1", "P2"})
            self.assertTrue(all(e["predictor"] in ("P1", "P2") for e in out["events"]))

    def test_s1_disables_capacity_and_source_evidence_is_unique(self):
        events = []
        real_run = sim.run

        def capture(*args, **kwargs):
            self.assertIs(kwargs["capacity_check"], False)
            result = real_run(*args, **kwargs)
            events.extend(result["events"])
            return result

        # No backend calls: collect evidence at the synchronous boundary.
        class Explainer:
            discarded = []

            def __init__(self, backend):
                self.async_ = self

            def __call__(self, event):
                return {"source": "rule"}

            def close(self, wait=True):
                pass

            def poll(self):
                return []

        with patch.object(mvp_smoke.tx, "LegacyAlertExplainer", Explainer), \
             patch.object(sim, "run", side_effect=capture):
            mvp_smoke.s1_legacy(None, [])
        batteries = [e for e in events if e["key"] == "battery" and e["type"] != "resolve"]
        self.assertTrue(batteries)
        for event in batteries:
            evidence = event["evidence"]
            triples = [(e["metric"], json.dumps(e["segment"], sort_keys=True), e["option_id"]) for e in evidence]
            self.assertEqual(len(triples), len(set(triples)))
            self.assertFalse(any("P3" in e.get("members", []) or e.get("source_predictor") == "P3" for e in evidence))
            self.assertFalse(any(e["metric"] in ("estimated_capacity_wh", "nominal_capacity_wh", "fc_pct", "estimated_remaining_pct") for e in evidence))
            for e in evidence:
                places = {"%": 1, "m/s": 1, "Wh": 0, "倍": 2, "s": 0, "°": 0}.get(e["unit"])
                if places is not None:
                    token = str(e["value"]).removesuffix(e["unit"])
                    self.assertRegex(token, r"^-?\d+" + (r"\.\d{" + str(places) + "}" if places else "") + r"$")


if __name__ == "__main__":
    unittest.main()
