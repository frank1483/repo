import unittest
from harness_wait_v6 import wait_until, wait_agent_idle


class Clock:
    def __init__(self):
        self.now = 0.0
        self.pumps = 0

    def clock(self):
        return self.now

    def pause(self, seconds):
        self.now += seconds

    def processEvents(self):
        self.pumps += 1


class WaitControls(unittest.TestCase):
    def run_wait(self, c, predicate, timeout=100):
        return wait_until(c, predicate, timeout, "injected", clock=c.clock, pause=c.pause,
                          diagnostic=lambda: "pending injected")

    def test_immediate_requires_two_pumps(self):
        c = Clock()
        self.run_wait(c, lambda: True)
        self.assertEqual(c.pumps, 2)

    def test_delayed_condition(self):
        c = Clock()
        self.run_wait(c, lambda: c.pumps >= 4)
        self.assertEqual(c.pumps, 5)

    def test_transient_true_does_not_complete(self):
        c = Clock()
        self.run_wait(c, lambda: c.pumps in (1, 3, 4))
        self.assertEqual(c.pumps, 4)

    def test_timeout_retains_diagnostic(self):
        c = Clock()
        with self.assertRaisesRegex(TimeoutError, "pending injected"):
            self.run_wait(c, lambda: False)

    def test_predicate_error_is_not_swallowed(self):
        c = Clock()
        def broken():
            raise RuntimeError("predicate failure")
        with self.assertRaisesRegex(RuntimeError, "predicate failure"):
            self.run_wait(c, broken)

    def test_pump_exceeding_deadline_cannot_pass(self):
        c = Clock()
        def pump():
            c.now += 0.2
        c.processEvents = pump
        with self.assertRaises(TimeoutError):
            self.run_wait(c, lambda: True)

    def test_nonfinite_timeout(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                self.run_wait(Clock(), lambda: True, value)

    def test_agent_property_conversion_and_idle(self):
        class Variant:
            def __init__(self, v):
                self.v = v
            def toVariant(self):
                return self.v
        class Agent:
            def property(self, name):
                return Variant(False if name == "busy" else None)
        class App:
            def processEvents(self):
                pass
        wait_agent_idle(App(), Agent(), 100, "idle")

    def test_missing_busy_property_rejected(self):
        class Missing:
            def property(self, name):
                return None
            def processEvents(self):
                pass
        with self.assertRaisesRegex(TypeError, "busy"):
            wait_agent_idle(Missing(), Missing(), 100, "missing")

    def test_invalid_timeout(self):
        c = Clock()
        with self.assertRaises(ValueError):
            self.run_wait(c, lambda: True, 0)


if __name__ == "__main__":
    unittest.main()
