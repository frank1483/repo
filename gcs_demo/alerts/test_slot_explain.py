"""範本句＋模型選格（slot_explain）的測試。只用假後端，不連網、不呼叫模型。

python3 -m unittest gcs_demo.alerts.test_slot_explain
"""
import itertools
import re
import time
import unittest

from . import explain, sim, slot_explain as S, typed_explain as tx
from .core import contract
from .slot_test_helpers import SlotBackend
from .test_typed_explain import raised_events
from .test_v5_explain_fixtures import event


def legacy_events():
    seen = {}
    sim.run(scenario="gusty", policy="ignore", explain_fn=lambda ev: seen.setdefault(ev["key"], ev) and None)
    return [event(ev) for ev in seen.values()]


def every_path(lib_fn, max_paths=200):
    """把每一格的每個代碼都試一遍（深度優先），回傳每條路徑的結果。"""
    results, queue = [], [[]]
    while queue and len(results) < max_paths:
        path = queue.pop()
        step = [0]

        def pick(cs, user, p=path, step=step):
            i = step[0]
            step[0] += 1
            return p[i] if i < len(p) else cs[0]
        b = SlotBackend(pick)
        r = lib_fn(b)
        results.append((path, r, b))
        # 從這條路徑長出下一格的其他選擇
        for depth, user in enumerate(b.users):
            if depth == len(path):
                for c in S_codes(user)[1:]:
                    queue.append(path + [c])
    return results


def S_codes(user):
    from .slot_test_helpers import codes
    return codes(user)


class AdviceListTests(unittest.TestCase):
    def test_advice_has_no_numbers_internal_names_or_assertions(self):
        for group, items in list(S.ADVICE.items()) + [("generic", S.GENERIC_ADVICE)]:
            codes = [c for c, _ in items]
            self.assertEqual(len(codes), len(set(codes)), group)
            for code, text in items:
                with self.subTest(group=group, code=code):
                    self.assertRegex(code, r"^[A-Z_]+$")
                    self.assertFalse(re.search(r"\d|[A-Za-z]", text), text)
                    self.assertFalse(any(b in text for b in contract._BANNED), text)
                    self.assertFalse(any(ch in contract._SIMPLIFIED for ch in text), text)
                    self.assertLessEqual(len(text) + 1, contract.MAX_SENTENCE_CHARS)

    def test_every_legacy_key_has_a_list(self):
        for ev in legacy_events():
            self.assertIn(S.LEGACY_GROUP.get(ev["key"]), S.ADVICE, ev["key"])


class LegacyPathTests(unittest.TestCase):
    def test_every_choice_on_every_sim_alert_passes_the_v5_validator(self):
        n = 0
        for ev in legacy_events():
            for path, r, b in every_path(lambda backend, ev=ev: explain.explain(ev, backend)):
                with self.subTest(key=ev["key"], path=path):
                    self.assertEqual(r["source"], "llm", r["fallback_reason"])
                    self.assertIsNone(explain.validate({k: r["text"][k] for k in
                                                        ("alert_version", "selected_id", "sentences", "evidence_ids")}, ev))
                    self.assertIn(r["text"]["selected_id"], ev["allowed_ids"])
                    self.assertLessEqual(b.calls, 4)
                    n += 1
        self.assertGreater(n, 20)

    def test_model_only_ever_sees_code_lists(self):
        ev = legacy_events()[0]
        b = SlotBackend()
        explain.explain(ev, b)
        for user in b.users:
            self.assertIn("只能選：", user)
            self.assertTrue(user.rstrip().endswith('只輸出 JSON：{"value":"代碼"}'))

    def test_invalid_twice_falls_back_to_rule(self):
        ev = legacy_events()[0]
        r = explain.explain(ev, SlotBackend(raw="我覺得應該返航"))
        self.assertEqual(r["source"], "rule")
        self.assertIn("修正一次後仍無效", r["fallback_reason"])
        self.assertEqual(r["text"], explain.rule_text(ev))

    def test_one_repair_is_allowed(self):
        ev = legacy_events()[0]
        replies = iter(['{"value":"NOPE"}'])
        b = SlotBackend(raw=lambda user: next(replies, None) or '{"value":"%s"}' % S_codes(user)[0])
        r = explain.explain(ev, b)
        self.assertEqual(r["source"], "llm", r["fallback_reason"])
        self.assertTrue(any("上次錯誤" in u for u in b.users))

    def test_all_calls_share_one_deadline(self):
        ev = legacy_events()[0]
        t0 = time.monotonic()
        r = explain.explain(ev, SlotBackend(delay=0.4), timeout_s=0.6)
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual(r["source"], "rule")

    def test_backend_exception_keeps_type(self):
        class Boom(SlotBackend):
            def complete_json(self, *a, **k):
                raise TimeoutError("slow")
        r = explain.explain(legacy_events()[0], Boom())
        self.assertEqual(r["source"], "rule")
        self.assertIn("TimeoutError", r["fallback_reason"])

    def test_nothing_to_choose_keeps_rule_text(self):
        ev = legacy_events()[0]
        ev["allowed_ids"] = ev["allowed_ids"][:1]
        ev["evidence"] = ev["evidence"][:1]
        lib = explain._slots(ev, explain.rule_text(ev))
        lib.advice = S.GENERIC_ADVICE
        out, log = S.run(lib, SlotBackend(), 5)
        self.assertIsNone(out)
        self.assertEqual(log["model_calls"], 0)


class TypedPathTests(unittest.TestCase):
    def test_every_choice_on_typed_alerts_passes_the_v5_validator(self):
        for e in raised_events():
            view = tx.typed_view(e)
            for path, r, b in every_path(lambda backend, v=view: tx.explain_typed(v, backend)):
                with self.subTest(predictor=view["predictor"], path=path):
                    self.assertEqual(r["source"], "llm", r["fallback_reason"])
                    self.assertIsNone(tx.validate(r["text"], view))
                    self.assertIsNone(r["text"]["selected_id"])
                    self.assertTrue(r["text"]["sentences"][0].startswith(view["severity_zh"] + "：" + view["title_zh"]))

    def test_ambiguous_number_rows_are_cited_without_the_number(self):
        # 「預估落地電量（下界）」同時含「落地電量」與下界兩種指標，數字綁不上 → 改用不帶數字的句子
        view = next(tx.typed_view(e) for e in raised_events() if e.get("predictor") == "P1")
        low = next(e for e in view["evidence"] if e["_key"] == "low_pct")
        b = SlotBackend(lambda cs, user: low["id"] if low["id"] in cs else cs[0])
        r = tx.explain_typed(view, b)
        self.assertEqual(r["source"], "llm", r["fallback_reason"])
        self.assertEqual(r["text"]["evidence_ids"], [low["id"]])
        self.assertNotRegex(r["text"]["sentences"][0], r"\d")

if __name__ == "__main__":
    unittest.main()
