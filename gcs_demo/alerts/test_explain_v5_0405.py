"""0405 defect regressions: local fixtures, no model or hardware calls."""
import unittest
from . import explain, typed_explain as tx
from .test_explain_v5_wiring import event
from .test_v5_explain_fixtures import answer


class Contract0405Tests(unittest.TestCase):
    def test_unbound_leading_decimal_in_either_sentence_is_rejected(self):
        ev = event()
        for value in (".5%", "+.5%", "-.5%", "−.5%", ".50%"):
            for index in (0, 1):
                with self.subTest(value=value, index=index):
                    sentences = ["請操作員評估。", "請持續留意。"]
                    sentences[index] = f"C1 落地電量 {value}。"
                    self.assertIsNotNone(explain.validate(
                        answer(ev, "C1", sentences, ["E1"]), ev))

    def test_exact_bound_leading_decimal_is_accepted(self):
        ev = event()
        ev["evidence"][0]["value"] = ".5"
        d = answer(ev, "C1", ["C1 落地電量 .5%。", "請操作員評估。"], ["E1"])
        self.assertIsNone(explain.validate(d, ev))
        d["sentences"][0] = "C1 落地電量 0.5%。"
        self.assertIsNotNone(explain.validate(d, ev))

    def test_malformed_numbers_cannot_disappear_from_binding(self):
        ev = event()
        for value in ("..5%", "1.2.3%", "15.%", "15.0.0%"):
            with self.subTest(value=value):
                self.assertIsNotNone(explain.validate(answer(
                    ev, "C1", [f"C1 落地電量 {value}。", "請操作員評估。"], ["E1"]), ev))

    def test_unicode_minus_cannot_borrow_positive_evidence(self):
        ev = event()
        d = answer(ev, "C1", ["C1 落地電量 −15.0%。", "請操作員評估。"], ["E1"])
        self.assertIsNotNone(explain.validate(d, ev))

    def test_cited_first_probe_label_is_accepted(self):
        ev = {"key": "P2", "predictor": "P2", "type": "raise", "active": True,
              "sequence": 1, "mission_version": "m1", "severity": 4,
              "evidence": [{"value": {"first_sampled_infeasible_id": "A"}}]}
        view = tx.typed_view(ev)
        d = answer(view, sentences=["第一個不可行的回程探查點為 A。", "請操作員評估。"], evidence_ids=["E1"])
        self.assertIsNone(tx.validate(d, view))
        for text in ("第一個不可行的回程探查點為 B。", "探查點為 A。"):
            with self.subTest(text=text):
                d["sentences"][0] = text
                self.assertIsNotNone(tx.validate(d, view))

    def test_label_exception_requires_citation_and_exact_text(self):
        ev = event()
        ev["evidence"][1]["text"] = "第一個不可行的回程探查點"
        d = answer(ev, "C1", ["第一個不可行的回程探查點。", "請操作員評估。"], ["E1"])
        self.assertIsNotNone(explain.validate(d, ev))
        d["evidence_ids"] = ["E1", "E2"]
        self.assertIsNone(explain.validate(d, ev))
        d["sentences"][0] = "第一個不可行的回程探查點，另有一個。"
        self.assertIsNotNone(explain.validate(d, ev))

    def test_masking_label_does_not_hide_its_arabic_digits(self):
        ev = event()
        ev["evidence"][0]["text"] = "第一個探查點 37"
        d = answer(ev, "C1", ["第一個探查點 37。", "請操作員評估。"], ["E1"])
        self.assertIsNotNone(explain.validate(d, ev))


if __name__ == "__main__":
    unittest.main()
