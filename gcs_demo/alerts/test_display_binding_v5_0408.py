"""0408 regressions: source display spans, signed raw values and every rule view."""
from copy import deepcopy
import unittest

from .core import contract
from . import typed_explain as tx


def view_for(predictor, values):
    return tx.typed_view({"type": "raise", "active": True, "key": predictor,
                          "predictor": predictor, "severity": 4, "sequence": 1,
                          "mission_version": "m1", "evidence": [{"value": values}]})


class DisplayBindingTests(unittest.TestCase):
    def setUp(self):
        self.view = view_for("P1", {"nominal_end_pct": -1.0})

    def reply(self, first):
        return {"alert_version": self.view["alert_version"], "selected_id": None,
                "sentences": [first, "請操作員評估。"], "evidence_ids": ["E1"]}

    def test_complete_display_and_signed_raw_are_both_accepted(self):
        for value in ("低於 0%（短缺 1.0%）", "-1.0%"):
            with self.subTest(value=value):
                self.assertIsNone(tx.validate(self.reply("預估落地電量（中值） " + value + "。"), self.view))
        self.assertEqual(self.view["evidence"][0]["value"], "-1.0%")
        self.assertIsNone(tx.validate(tx.rule_text(self.view), self.view))

    def test_display_reply_is_used_through_model_adapter_without_network(self):
        reply = self.reply("預估落地電量（中值）低於 0%（短缺 1.0%）。")

        class StubBackend:
            name, model = "fixture", "fixture"

            def complete_json(self, *args, **kwargs):
                return {"ok": True, "data": reply, "raw": "", "latency_s": 0, "error": None}

        result = tx.explain_typed(self.view, StubBackend())
        self.assertEqual(result["source"], "llm", result["fallback_reason"])

    def test_isolated_zero_wrong_shortage_and_partial_display_are_rejected(self):
        for value in ("0%", "短缺 1.0%", "低於 0%（短缺 2.0%）",
                      "低於 0%（短缺 1.0%）及 0%", "低於 0%（短缺 1.0%）及短缺 2.0%"):
            with self.subTest(value=value):
                self.assertIsNotNone(tx.validate(self.reply("預估落地電量（中值） " + value + "。"), self.view))

    def test_display_requires_same_clause_metric_and_actual_citation(self):
        for text in ("低於 0%（短缺 1.0%）。", "風速低於 0%（短缺 1.0%）。",
                     "預估落地電量（中值），低於 0%（短缺 1.0%）。"):
            self.assertIsNotNone(tx.validate(self.reply(text), self.view))
        view = view_for("P1", {"nominal_end_pct": -1.0, "reserve_pct": 20})
        reply = self.reply("預估落地電量（中值）低於 0%（短缺 1.0%）。")
        reply["evidence_ids"] = ["E2"]
        self.assertIsNotNone(tx.validate(reply, view))

    def test_display_requires_same_option(self):
        facts = tx._facts(self.view)
        facts["allowed_ids"] = ["C1", "C2"]
        facts["evidence"][0]["option_id"] = "C1"
        current = {"active": True, "alert_version": facts["alert_version"], "feasible_ids": ["C1", "C2"]}
        reply = self.reply("C1 預估落地電量（中值）低於 0%（短缺 1.0%）。")
        reply["selected_id"] = "C1"
        self.assertIsNone(contract.validate(reply, facts, current))
        reply["sentences"][0] = reply["sentences"][0].replace("C1", "C2")
        self.assertIsNotNone(contract.validate(reply, facts, current))

    def test_equal_display_with_ambiguous_metric_is_rejected(self):
        facts = tx._facts(self.view)
        duplicate = dict(facts["evidence"][0], id="E2", metric="other_energy")
        facts["evidence"].append(duplicate)
        reply = self.reply("預估落地電量（中值）低於 0%（短缺 1.0%）。")
        reply["evidence_ids"].append("E2")
        self.assertIsNotNone(contract.validate(reply, facts, {"active": True,
                             "alert_version": facts["alert_version"], "feasible_ids": []}))

    def test_small_negative_and_multiple_display_spans(self):
        for value in (-0.001, -1.0):
            view = view_for("P1", {"nominal_end_pct": value})
            self.assertIsNone(tx.validate(tx.rule_text(view), view))
        reply = self.reply("預估落地電量（中值）低於 0%（短缺 1.0%），落地電量低於 0%（短缺 1.0%）。")
        self.assertIsNone(tx.validate(reply, self.view))

    def test_other_guards_still_apply(self):
        for extra in (" 5", " SE", " 1.2.3", "保證"):
            reply = self.reply("預估落地電量（中值）低於 0%（短缺 1.0%）" + extra + "。")
            self.assertIsNotNone(tx.validate(reply, self.view))
        reply = self.reply("預估落地電量（中值）低於 0%（短缺 1.0%）。")
        reply["alert_version"] = "stale"
        self.assertIsNotNone(tx.validate(reply, self.view))

    def test_missing_display_keeps_raw_binding_only(self):
        view = deepcopy(self.view)
        del view["evidence"][0]["display_value"]
        self.assertIsNone(tx.validate(self.reply("預估落地電量（中值）-1.0%。"), view))
        self.assertIsNotNone(tx.validate(self.reply("預估落地電量（中值）低於 0%（短缺 1.0%）。"), view))


class EveryTypedRuleTests(unittest.TestCase):
    def test_p1_p2_p3_and_nonfirst_evidence_pass(self):
        for predictor, values in (("P1", {"reserve_pct": 20, "nominal_end_pct": -1.0}),
                                  ("P2", {"sample_count": 10, "first_sampled_infeasible_id": "A"}),
                                  ("P3", {"sample_count": 10, "capacity_ratio": 0.6})):
            with self.subTest(predictor=predictor):
                view = view_for(predictor, values)
                reply = tx.rule_text(view)
                self.assertEqual(reply["evidence_ids"], ["E2"])
                self.assertIsNone(tx.validate(reply, view))

    def test_p2_full_label_is_required_for_categorical_id(self):
        view = view_for("P2", {"first_sampled_infeasible_id": "A"})
        reply = tx.rule_text(view)
        self.assertIn("第一個不可行的回程探查點 A", reply["sentences"][0])
        self.assertIsNone(tx.validate(reply, view))
        reply["sentences"][0] = "探查點 A 的回程電量不足。"
        self.assertIsNotNone(tx.validate(reply, view))


if __name__ == "__main__":
    unittest.main()
