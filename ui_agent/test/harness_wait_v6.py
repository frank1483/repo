# Bounded condition polling for ordinary harness operations; no Qt import or network.
import math
import time


def wait_until(app, predicate, timeout_ms, description, *, clock=time.monotonic,
               pause=time.sleep, diagnostic=lambda: ""):
    if not math.isfinite(timeout_ms) or timeout_ms <= 0:
        raise ValueError("finite positive condition timeout required")
    deadline = clock() + timeout_ms / 1000.0
    stable = 0
    while True:
        app.processEvents()
        ready = bool(predicate())
        if clock() >= deadline:
            raise TimeoutError("condition timeout: %s; %s" % (description, diagnostic()))
        stable = stable + 1 if ready else 0
        if stable >= 2:
            return
        pause(min(0.01, max(0.0, deadline - clock())))


def wait_agent_idle(app, agent, timeout_ms, description):
    def value(name):
        v = agent.property(name)
        return v.toVariant() if hasattr(v, "toVariant") else v

    def idle():
        busy = value("busy")
        if not isinstance(busy, bool):
            raise TypeError("agent busy property must be a bool")
        return not busy and not value("_transaction")

    wait_until(app, idle,
               timeout_ms, description,
               diagnostic=lambda: repr({k: value(k) for k in
                                        ("busy", "_transaction", "statusText", "messageText")}))
