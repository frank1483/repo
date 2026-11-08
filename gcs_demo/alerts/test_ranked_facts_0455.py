"""0455 controls: new code only; Python first execution belongs to Claude."""
from copy import deepcopy
from dataclasses import replace
import unittest

from .core.contract import validate
from .core.ranked_facts import fact, option_evidence, ranked_ids
from .predict import Finding
from .test_predict_sources_0447 import engine, telemetry
from .energy_api import Wind


def candidate(ident, raw=30., completion=50., missed=0, **extra):
    return {"id": ident, "action": "A_CONTINUE", "label": ident, "feasible": True,
            "energy_feasible": True, "end_pct_raw": raw, "end_pct": round(raw, 1),
            "completion_pct": completion, "missed_required": missed, **extra}


def finding(candidates, choice=None):
    return Finding("battery", True, severity=2, title="電量告警", value="請評估",
                   evidence=[fact("E1", "落地保留電量", "reserve_pct", "20%", "%", "configuration")],
                   candidates=candidates, rule_choice=choice)


class RankedFacts0455Tests(unittest.TestCase):
    def assert_bound(self, rows):
        required = {"id", "option_id", "metric", "value", "unit", "segment", "relation"}
        self.assertTrue(rows)
        self.assertEqual(len({e["id"] for e in rows}), len(rows))
        for e in rows:
            self.assertTrue(required <= e.keys(), e)
            self.assertRegex(e["id"], r"^E\d+$")
            self.assertTrue(e["metric"] and e["segment"] and e["relation"])

    def test_rank_prioritizes_required_then_completion_then_landing(self):
        rows = [candidate("C1", 90., 100., 1), candidate("C2", 90., 49.),
                candidate("C3", 30., 50.), candidate("C4", 32., 50.)]
        self.assertEqual(ranked_ids(rows), ["C4"])

    def test_ties_use_strict_one_point_and_do_not_chain(self):
        rows = [candidate("C1", 30.), candidate("C2", 29.25),
                candidate("C3", 28.5), candidate("C4", 29.)]
        self.assertEqual(ranked_ids(rows), ["C1", "C2"])

    def test_raw_values_not_rounded_values_decide_ties(self):
        self.assertEqual(ranked_ids([candidate("C1", 30.04), candidate("C2", 29.05)]), ["C1", "C2"])

    def test_infeasible_and_landing_never_enter_allowed(self):
        rows = [candidate("C1", feasible=False), candidate("C5", 99.),
                candidate("C6", 99., action="A_LAND_NOW")]
        self.assertEqual(ranked_ids(rows), [])

    def test_nonflight_without_landing_estimates_can_tie(self):
        rows = [{"id": "C1", "action": "A_CONTINUE_MONITOR", "feasible": True},
                {"id": "C2", "action": "A_USE_VOLTAGE_ESTIMATE", "feasible": True}]
        self.assertEqual(ranked_ids(rows), ["C1", "C2"])

    def test_monitoring_advice_does_not_become_a_zero_completion_flight(self):
        eng = engine()
        monitor = {"id": "C1", "action": "A_CONTINUE_MONITOR", "label": "持續觀察", "feasible": True}
        rtl = candidate("C2", 30., completion=50., action="A_RTL_NOW")
        row = eng._debounce(0., replace(finding([monitor, rtl], "C1"), key="link_route"))[0]
        self.assertEqual((row["allowed_ids"], row["rule_choice"]), (["C1", "C2"], "C1"))

    def test_allowed_tie_does_not_override_eligible_rule_choice(self):
        eng = engine()
        first = eng._debounce(0., finding([candidate("C1", 29.5)], "C1"))[0]
        self.assertEqual(first["allowed_ids"], ["C1"])
        candidates = [candidate("C1", 29.5), candidate("C2", 30.)]
        for t in (1., 2., 3.):
            self.assertEqual(eng._debounce(t, finding(candidates, "C2")), [])
            self.assertEqual(eng.active()["battery"].rule_choice, "C1")
            self.assertEqual(eng.current_state("battery")["allowed_ids"], ["C1", "C2"])
        row = eng._debounce(4., finding(candidates, "C2"))[0]
        self.assertEqual((row["rule_choice"], row["allowed_ids"]), ("C2", ["C1", "C2"]))

    def test_qualified_rule_choice_can_be_outside_ranked_allowed(self):
        eng = engine()
        row = eng._debounce(0., finding([candidate("C1", 30.), candidate("C2", 32.)], "C1"))[0]
        self.assertEqual((row["rule_choice"], row["allowed_ids"]), ("C1", ["C2"]))
        self.assertEqual(eng.current_state("battery")["allowed_ids"], ["C2"])

    def test_wind_return_rule_replaces_monitor_after_three_seconds(self):
        eng = engine()
        monitor = {"id": "C1", "action": "A_CONTINUE_MONITOR", "label": "持續觀察", "feasible": True}
        rtl = candidate("C2", 37.3, action="A_RTL_NOW")
        def sample(choice):
            return replace(finding([monitor, rtl], choice), key="wind_trend")
        eng._debounce(520., sample("C1"))
        for t in (523., 524., 525.):
            self.assertEqual(eng._debounce(t, sample("C2")), [])
            self.assertEqual(eng.active()["wind_trend"].rule_choice, "C1")
        row = eng._debounce(526., sample("C2"))[0]
        self.assertEqual((row["rule_choice"], row["allowed_ids"]), ("C2", ["C1", "C2"]))

    def test_fallback_retains_committed_identity_within_ranked_tie(self):
        eng = engine()
        eng._debounce(0., finding([candidate("C2", 30.)], "C2"))
        candidates = [candidate("C1", 30.5), candidate("C2", 30.)]
        for t in (1., 2., 3., 4.):
            self.assertEqual(eng._debounce(t, finding(candidates, "C9")), [])
            self.assertEqual(eng.active()["battery"].rule_choice, "C2")
        self.assertEqual(eng.current_state("battery")["allowed_ids"], ["C1", "C2"])

    def test_fallback_without_committed_tie_uses_first_ranked_option(self):
        eng = engine()
        row = eng._debounce(0., finding([candidate("C2", 30.), candidate("C1", 30.5)], "C9"))[0]
        self.assertEqual((row["rule_choice"], row["allowed_ids"]), ("C2", ["C2", "C1"]))

    def test_fallback_does_not_retain_candidate_outside_ranking(self):
        eng = engine()
        eng._debounce(0., finding([candidate("C1", 30.)], "C1"))
        candidates = [candidate("C1", 30.), candidate("C2", 32.)]
        for t in (1., 2., 3.):
            self.assertEqual(eng._debounce(t, finding(candidates, "C9")), [])
            self.assertEqual(eng.active()["battery"].rule_choice, "C1")
        row = eng._debounce(4., finding(candidates, "C9"))[0]
        self.assertEqual((row["rule_choice"], row["allowed_ids"]), ("C2", ["C2"]))

    def test_infeasible_rule_choice_cannot_override_ranked_fallback(self):
        eng = engine()
        row = eng._debounce(0., finding([candidate("C1", 90., feasible=False),
                                       candidate("C2", 30.)], "C1"))[0]
        self.assertEqual((row["rule_choice"], row["allowed_ids"]), ("C2", ["C2"]))

    def test_superior_option_still_waits_three_seconds(self):
        eng = engine()
        eng._debounce(0., finding([candidate("C1", 30.)], "C1"))
        for t in (1., 2., 3.):
            self.assertEqual(eng._debounce(t, finding([candidate("C1", 30.), candidate("C2", 32.)], "C2")), [])
            self.assertEqual(eng.active()["battery"].rule_choice, "C1")
        row = eng._debounce(4., finding([candidate("C1", 30.), candidate("C2", 32.)], "C2"))[0]
        self.assertEqual((row["rule_choice"], row["allowed_ids"]), ("C2", ["C2"]))

    def test_same_id_different_physical_option_does_not_retain_tie(self):
        eng = engine()
        eng._debounce(0., finding([candidate("C3", option_identity="old")], "C3"))
        rows = eng._debounce(1., finding([candidate("C1"), candidate("C3", option_identity="new")], "C1"))
        self.assertEqual(rows[0]["rule_choice"], None)
        self.assertEqual(eng._states.states["battery"].pending, "C1")

    def test_admission_keeps_existing_twenty_twenty_two_policy(self):
        eng = engine()
        row = eng._debounce(0., finding([candidate("C1", 21.), candidate("C2", 23.)], "C1"))[0]
        self.assertEqual((row["allowed_ids"], row["rule_choice"]), (["C2"], "C2"))
        eng._debounce(1., finding([candidate("C2", 21.)], "C2"))
        self.assertEqual(eng.current_state("battery")["allowed_ids"], ["C2"])

    def test_hold_has_empty_allowed_and_never_promotes_emergency_candidate(self):
        eng = engine()
        row = eng._debounce(0., finding([candidate("C4", 15., feasible=False)], "C4"))[0]
        self.assertEqual((row["allowed_ids"], row["rule_choice"], row["rule_decision"]), ([], None, "HOLD"))

    def test_live_rank_rejects_late_model_choice_even_with_same_version(self):
        eng = engine()
        row = eng._debounce(0., finding([candidate("C1", 30.), candidate("C2", 30.5)], "C1"))[0]
        eng._debounce(1., finding([candidate("C1", 30.), candidate("C2", 32.)], "C2"))
        self.assertEqual(eng.current_state("battery")["alert_version"], row["alert_version"])
        result = {"source": "llm", "text": {"alert_version": row["alert_version"], "selected_id": "C1",
                  "sentences": ["請評估 C1。", "請操作員確認。"], "evidence_ids": ["E1"]}}
        self.assertIsNone(eng.apply_explanation("battery", row["alert_version"], result))

    def test_candidate_evidence_is_option_scoped_and_source_is_unchanged(self):
        original = [fact("E7", "風速", "wind_speed", "2.0", "m/s", "current",
                         source_predictor="P3", source_evidence_id="E2", sensed_t=0., recv_t=.1)]
        snapshot = deepcopy(original)
        rows = option_evidence(original, [candidate("C1", 30.), candidate("C2", 32.)], "battery")
        self.assertEqual(original, snapshot)
        self.assertEqual(rows[0], original[0])
        self.assert_bound(rows)
        values = {(e["option_id"], e["metric"]): e["value"] for e in rows}
        self.assertEqual((values["C1", "end_pct"], values["C2", "end_pct"]), (30., 32.))

    def test_production_battery_and_capacity_rows_have_complete_bindings(self):
        eng = engine()
        for f in eng._battery_route(telemetry(), eng.v.battery_wh * .5, "soc", None):
            if f.evidence:
                self.assert_bound(f.evidence)
        p3 = eng._battery_capacity(telemetry(), eng.v.battery_wh * .3, eng.v.battery_wh * .8)
        self.assertTrue(p3.active)
        self.assertEqual([c["action"] for c in p3.candidates], ["A_USE_VOLTAGE_ESTIMATE", "A_CONTINUE_MONITOR"])
        self.assert_bound(p3.evidence)
        self.assertTrue(all(e["option_id"] is None for e in p3.evidence))

    def test_production_wind_has_scalar_trend_and_fit_rows(self):
        eng = engine()
        f = eng._wind(replace(telemetry(), wind=Wind(15., 90.)))
        self.assert_bound(f.evidence)
        self.assertEqual(f.evidence[2]["value"], f"{eng.cfg.wind_limit_mps:.0f} m/s")
        self.assertEqual({e["metric"] for e in f.evidence},
                         {"wind_speed", "wind_trend_per_min", "wind_limit", "wind_r_squared", "eta_s"})

    def test_production_link_splits_composite_measurements(self):
        eng = engine()
        eng.set_route([(2000., 0., 50.)])
        eng._link_hist.extend((float(d), 100. - .1 * d) for d in range(0, 590, 10))
        f = eng._link(replace(telemetry(), pos=(590., 0., 50.), link_pct=41.))
        self.assertTrue(f.active)
        self.assert_bound(f.evidence)
        self.assertEqual(len(f.evidence), 8)
        self.assertEqual(f.evidence[6]["value"], "WP1")

    def test_core_accepts_bound_option_value_and_rejects_cross_option_number(self):
        eng = engine()
        row = eng._debounce(0., finding([candidate("C1", 30.), candidate("C2", 30.5)], "C1"))[0]
        evidence = next(e for e in row["evidence"] if e.get("option_id") == "C1" and e["metric"] == "end_pct")
        reply = {"alert_version": row["alert_version"], "selected_id": "C1",
                 "sentences": ["C1 預估落地電量 30.0%。", "請操作員確認。"], "evidence_ids": [evidence["id"]]}
        current = eng.current_state("battery")
        self.assertIsNone(validate(reply, row, current))
        reply["sentences"][0] = "C1 預估落地電量 30.5%。"
        self.assertIsNotNone(validate(reply, row, current))


if __name__ == "__main__":
    unittest.main()
