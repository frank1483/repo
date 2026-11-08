"""Time-based keyed states. Call once per NEW assessment, not once per UI poll.

UNKNOWN and gaps reset continuity. snapshot() exposes prediction_expired without
reissuing an otherwise unchanged alert. All inputs use one monotonic time domain.
"""
from dataclasses import dataclass, field
from copy import deepcopy
from . import RULE_VERSION
from .freshness import Truth, TRUE, FALSE, UNKNOWN
from .units import finite

NOTICE, WARNING, CRITICAL = 5, 4, 2
SEVERITY_ZH = {NOTICE: "注意", WARNING: "警告", CRITICAL: "嚴重"}


@dataclass
class _State:
    active: bool = False
    severity: int = NOTICE
    recommendation: str | None = None
    version: int = 0
    episode: int = 0
    last_t: float | None = None
    last_sensed_t: float | None = None
    last_recv_t: float | None = None
    last_assessment_id: str | None = None
    since_true: float | None = None
    true_count: int = 0
    since_false: float | None = None
    lower: int | None = None
    lower_since: float | None = None
    pending: str | None = None
    pending_since: float | None = None
    resolved_t: float | None = None
    resolved_severity: int = NOTICE
    prediction_expired: bool = False
    facts: dict = field(default_factory=dict)

    def reset_continuity(self):
        self.since_true = self.since_false = None
        self.true_count = 0
        self.lower = self.lower_since = None
        self.pending = self.pending_since = None


class AlertEngine:
    def __init__(self):
        self.states = {}
        self.engine_seq = 0
        self.dropped = {}

    def _event(self, key, s, kind, t, sensed_t, recv_t):
        if kind in ("raise", "update"):
            s.version += 1
        self.engine_seq += 1
        return {**deepcopy(s.facts), "key": key,
                "alert_id": f"{key}:{s.episode}", "alert_version": s.version,
                "engine_seq": self.engine_seq, "type": kind, "status": kind,
                "sensed_t": sensed_t, "recv_t": recv_t, "output_t": t,
                "predictor": s.facts.get("predictor", key), "severity": s.severity,
                "severity_zh": SEVERITY_ZH[s.severity], "rule_version": RULE_VERSION,
                "active": s.active, "recommendation": s.recommendation,
                "prediction_expired": s.prediction_expired, "source": "rule"}

    def step(self, key, t, truth, severity=NOTICE, recommendation=None,
             feasible_ids=None, *, max_gap_s=3.0, sensed_t=None, recv_t=None,
             assessment_id=None, **facts):
        """feasible_ids=None means unavailable, not an empty allowed set.

        A TRUE assessment must provide feasible_ids when it offers a recommendation.
        Required-source gating belongs to Freshness, before this call.
        """
        sensed_t = t if sensed_t is None else sensed_t
        recv_t = t if recv_t is None else recv_t
        if (not all(finite(v) for v in (t, sensed_t, recv_t, max_gap_s))
                or not sensed_t <= recv_t <= t or max_gap_s <= 0):
            raise ValueError("invalid monotonic times or continuity limit")
        if not isinstance(truth, Truth) or severity not in SEVERITY_ZH:
            raise ValueError("explicit tri-state and supported severity required")
        if not isinstance(key, str) or not key:
            raise ValueError("nonempty key required")
        if assessment_id is not None and (not isinstance(assessment_id, str) or not assessment_id):
            raise ValueError("nonempty composite assessment identity required")
        feasible = None if feasible_ids is None else set(feasible_ids)
        if recommendation is not None and (feasible is None or recommendation not in feasible):
            recommendation = None
        s = self.states.setdefault(key, _State())
        if s.last_t is not None and t <= s.last_t:
            self.dropped[key] = self.dropped.get(key, 0) + 1
            return []
        # Composite assessments include independently timed member samples.
        # Their newest timestamp need not advance when a slower member changes.
        # The caller supplies the complete source signature, never a poll counter.
        duplicate = (assessment_id == s.last_assessment_id if assessment_id is not None else
                     s.last_sensed_t is not None and
                     (sensed_t <= s.last_sensed_t or recv_t <= s.last_recv_t))
        if truth is not UNKNOWN and duplicate:
            self.dropped[key] = self.dropped.get(key, 0) + 1
            return []
        # Stale TRUE must never raise/upgrade, even when the caller missed gating.
        if t - sensed_t > max_gap_s:
            truth = UNKNOWN
        if s.last_t is not None and t - s.last_t > max_gap_s:
            s.reset_continuity()
        s.last_t = t
        if truth is not UNKNOWN:
            s.last_sensed_t, s.last_recv_t = sensed_t, recv_t
            s.last_assessment_id = assessment_id
        s.facts = deepcopy(facts)
        changed = False
        if s.active and feasible is not None and s.recommendation not in feasible:
            if s.recommendation is not None:
                s.recommendation = None
                changed = True
        if truth is UNKNOWN:
            s.reset_continuity()
            s.prediction_expired = True
        elif truth is FALSE:
            s.prediction_expired = False
            s.since_true, s.true_count = None, 0
            s.lower = s.lower_since = s.pending = s.pending_since = None
            if s.active:
                if s.since_false is None:
                    s.since_false = t
                if t - s.since_false >= 10.0:
                    s.active = False
                    s.resolved_t, s.resolved_severity = t, s.severity
                    s.recommendation = None
                    s.reset_continuity()
                    return [self._event(key, s, "resolve", t, sensed_t, recv_t)]
        else:
            s.prediction_expired = False
            s.since_false = None
            if not s.active:
                if s.since_true is None:
                    s.since_true = t
                s.true_count += 1
                confirmed = severity == CRITICAL or (s.true_count >= 3 and t - s.since_true >= 1.0)
                cooling = (s.resolved_t is not None and t - s.resolved_t < 60.0
                           and severity >= s.resolved_severity and severity != CRITICAL)
                if confirmed and not cooling:
                    s.active, s.severity, s.recommendation = True, severity, recommendation
                    s.episode += 1
                    s.reset_continuity()
                    return [self._event(key, s, "raise", t, sensed_t, recv_t)]
            else:
                if severity < s.severity:
                    s.severity = severity
                    s.lower = s.lower_since = None
                    changed = True
                elif severity > s.severity:
                    if s.lower != severity:
                        s.lower, s.lower_since = severity, t
                    elif t - s.lower_since >= 10.0:
                        s.severity = severity
                        s.lower = s.lower_since = None
                        changed = True
                else:
                    s.lower = s.lower_since = None
                if recommendation == s.recommendation:
                    s.pending = s.pending_since = None
                elif s.pending_since is None or s.pending != recommendation:
                    s.pending, s.pending_since = recommendation, t
                elif t - s.pending_since >= 3.0:
                    s.recommendation = recommendation
                    s.pending = s.pending_since = None
                    changed = True
        return [self._event(key, s, "update", t, sensed_t, recv_t)] if changed else []

    def explanation_update(self, key, expected_version, t, result):
        """Issue a presentation update without advancing assessment continuity.

        The caller validates the explanation and current feasibility. The engine
        owns sequence/version allocation; no sample timestamp is fabricated.
        """
        s = self.states.get(key)
        if (s is None or not s.active or s.prediction_expired
                or s.version != expected_version or not finite(t)
                or s.last_t is None or t < s.last_t
                or not isinstance(result, dict)
                or result.get("source") not in ("llm", "rule")
                or not isinstance(result.get("text"), dict)):
            return None
        row = self._event(key, s, "update", t, s.last_sensed_t, s.last_recv_t)
        row.update(source=result["source"], explain=deepcopy(result),
                   explanation_for_version=expected_version,
                   model_selection=(result.get("text") or {}).get("selected_id")
                   if result["source"] == "llm" else None)
        return row

    def explanation_closed(self, original, t, reason):
        """Journal a request terminal state, without changing a live alert version.

        This row belongs to the ORIGINAL episode/version. A late closure cannot
        replace a newer version in a presentation projection.
        """
        if not finite(t) or not isinstance(reason, str) or not reason:
            raise ValueError("valid explanation closure required")
        self.engine_seq += 1
        text = {"summary_zh": "此筆告警說明已結案，未套用模型結果。",
                "selected_id": None, "sentences": [], "evidence_ids": []}
        return {**deepcopy(original), "engine_seq": self.engine_seq,
                "type": "update", "status": "update", "t": t, "output_t": t,
                "active": False, "source": "rule", "model_selection": None,
                "recommendation": None, "recommendation_identity": None,
                "rule_choice": None, "rule_decision": "HOLD", "candidates": [],
                "allowed_ids": [], "closure_only": True,
                "explanation_status": "closed",
                "explanation_for_version": original["alert_version"],
                "explain": {"source": "rule", "text": text, "fallback_reason": reason}}

    def snapshot(self):
        return {k: {"active": s.active, "severity": s.severity,
                    "recommendation": s.recommendation, "alert_version": s.version,
                    "prediction_expired": s.prediction_expired}
                for k, s in self.states.items()}


def merge_groups(assessments, *, p11_wind_explained=False):
    """Merge declarative assessments before debouncing; never merge merely by title.

    Each row has predictor/truth/severity/title/evidence/options. P1 alone owns
    battery options. Missing P1 produces no options, never substitutes P2/P3.
    """
    groups = {}
    wind_active = any(r["predictor"] == "P5" and r["truth"] is TRUE for r in assessments)
    for row in assessments:
        pred = row["predictor"]
        key = ("battery" if pred in ("P1", "P2", "P3") else
               "wind" if pred == "P5" or (pred == "P11" and p11_wind_explained
                                          and wind_active and row["truth"] is TRUE) else pred)
        groups.setdefault(key, []).append(row)
    result = []
    for key, rows in groups.items():
        active = [r for r in rows if r["truth"] is TRUE]
        truth = TRUE if active else UNKNOWN if any(r["truth"] is UNKNOWN for r in rows) else FALSE
        lead = min(active or rows, key=lambda r: (r["severity"], r["predictor"]))
        owner = next((r for r in rows if r["predictor"] == ("P1" if key == "battery" else "P5")), lead)
        options = [] if key == "battery" and owner["predictor"] != "P1" else owner.get("options", [])
        evidence = []
        for row in rows:
            if row["truth"] is UNKNOWN:
                continue
            for original in row.get("evidence", []):
                evidence.append({**deepcopy(original), "source_predictor": row["predictor"],
                                 "source_evidence_id": original.get("id"),
                                 "id": f"E{len(evidence) + 1}"})
        result.append({**deepcopy(lead), "key": key, "truth": truth,
                       "predictor": key, "members": [r["predictor"] for r in rows],
                       "evidence": evidence,
                       "options": deepcopy(options)})
    return result
