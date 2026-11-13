"""agent_loop 寬鬆前綴（lenient_prefix）：模型把「代碼 說明」整段回傳時，開頭是合法代碼就採用並記錄。"""
import unittest

from gcs_demo.agent_loop import _lenient_prefix


class LenientPrefixTests(unittest.TestCase):
    codes = ["E1", "E2", "C1", "C10", "HOLD"]

    def test_code_followed_by_explanation(self):
        self.assertEqual(_lenient_prefix("E1 預估落地電量 28.6%", self.codes), "E1")
        self.assertEqual(_lenient_prefix("  HOLD：無符合條件方案", self.codes), "HOLD")
        self.assertEqual(_lenient_prefix("C1（返航）", self.codes), "C1")

    def test_longest_code_wins(self):
        self.assertEqual(_lenient_prefix("C10 改降備降點", self.codes), "C10")

    def test_rejects_non_boundary_and_unknown(self):
        for v in ["C1x 返航", "E3 其他", "HOLDING", "預估 E1", "", "e1 小寫"]:
            self.assertIsNone(_lenient_prefix(v, self.codes), v)

    def test_mission_style_codes(self):
        self.assertEqual(_lenient_prefix("L2 LOCAL 刪選配目標（…", ["L1", "L2", "C1", "HOLD"]), "L2")


if __name__ == "__main__":
    unittest.main()
