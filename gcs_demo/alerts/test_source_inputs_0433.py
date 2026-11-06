"""NEW isolated source-input controls; no old entrypoint/model/device imports."""
import unittest
from .core.source_inputs import SourceInputs


class SourceInputsTests(unittest.TestCase):
    def test_absent_source_is_unknown_without_last_value(self):
        s = SourceInputs()
        result = s.readiness(("position", "link"), 10)
        self.assertEqual(result["unknown_sources"], ["position", "link"])
        self.assertIsNone(result["sources"]["position"]["value"])

    def test_one_missing_source_does_not_gate_other_consumer(self):
        s = SourceInputs()
        s.put("wind", 5, 1, 1)
        self.assertEqual(s.readiness(("wind",), 2)["status"], "ready")
        self.assertEqual(s.readiness(("position", "link"), 2)["status"], "unknown")

    def test_sensed_age_cannot_be_refreshed_by_recent_receive(self):
        s = SourceInputs()
        s.put("voltage", 15, 1, 9)
        row = s.status("voltage", 10)
        self.assertEqual(row["reason"], "expired")
        self.assertEqual((row["sensed_age_s"], row["recv_age_s"]), (9, 1))

    def test_exact_ttl_and_custom_ttl(self):
        s = SourceInputs({"current": 2})
        s.put("current", 1, 1, 1)
        self.assertEqual(s.status("current", 3)["status"], "ready")
        self.assertEqual(s.status("current", 3.001)["reason"], "expired")

    def test_duplicate_or_out_of_order_does_not_poison_latest(self):
        s = SourceInputs()
        s.put("current", 1, 2, 3)
        self.assertFalse(s.put("current", 9, 2, 4, valid=False))
        self.assertFalse(s.put("current", 9, 3, 3, valid=False))
        row = s.status("current", 4)
        self.assertEqual((row["value"], row["status"], row["dropped"]), (1, "ready", 2))

    def test_mavlink_sentinel_and_negative_current_are_distinct(self):
        for message in ("SYS_STATUS", "BATTERY_STATUS"):
            s = SourceInputs()
            limits = {"min_current_a": -1, "max_current_a": 10}  # fixture, NOT policy
            s.put_mavlink_current(-5, message, limits, 1, 1)
            self.assertEqual(s.status("current", 1)["value"], -0.05)
            self.assertEqual(s.status("current", 1)["status"], "ready")
            s.put_mavlink_current(-1, message, limits, 2, 2)
            self.assertEqual(s.status("current", 2)["reason"], "missing_current")
            self.assertIsNone(s.status("current", 2)["value"])

    def test_profile_range_only_invalidates_current(self):
        s = SourceInputs()
        s.put("wind", 3, 1, 1)
        s.put_mavlink_current(1001, "SYS_STATUS",
                              {"min_current_a": -1, "max_current_a": 10}, 1, 1)
        self.assertEqual(s.status("current", 1)["reason"], "out_of_airframe_range")
        self.assertEqual(s.readiness(("wind",), 1)["status"], "ready")

    def test_bad_protocol_and_profile_never_infer_defaults(self):
        s = SourceInputs()
        limits = {"min_current_a": -1, "max_current_a": 10}
        for raw, message in ((True, "SYS_STATUS"), (1.5, "BATTERY_STATUS"), (5, "CSV")):
            with self.assertRaises(ValueError):
                s.put_mavlink_current(raw, message, limits, 1, 1)
        with self.assertRaises((ValueError, KeyError)):
            s.put_mavlink_current(-1, "SYS_STATUS", {}, 1, 1)
        self.assertIsNone(s.status("current", 1)["value"])

    def test_future_invalid_and_reset_never_read_as_ready(self):
        s = SourceInputs()
        s.put("wind", 3, 3, 4)
        self.assertEqual(s.status("wind", 3)["reason"], "future_sample")
        s.put("wind", 7, 5, 5, valid=False, invalid_reason="sensor_invalid")
        self.assertEqual(s.status("wind", 5)["reason"], "sensor_invalid")
        s.reset()
        self.assertEqual(s.status("wind", 5)["reason"], "missing")

    def test_declarations_and_clock_errors_are_explicit(self):
        s = SourceInputs()
        for names in ((), "wind", ("wind", "wind"), ("not_declared",)):
            with self.assertRaises(ValueError):
                s.readiness(names, 1)
        with self.assertRaises(ValueError):
            s.put("wind", 2, 2, 1)
        with self.assertRaises(ValueError):
            s.status("wind", float("nan"))


if __name__ == "__main__":
    unittest.main()
