"""One strict v5 output validator; returns None or a rejection reason.

This module does not adapt legacy payloads. Integrators must provide the v5
facts schema and the CURRENT active/version/feasible_ids at application time.
Numeric claims require a metric label and an unambiguous option context; when
natural language cannot be grounded, reject and retain the rule explanation.
"""
import re
from .units import finite

MAX_SENTENCE_CHARS = 60
# Preserved lists from f1fa869 explain.py / typed_explain.py, plus v5 assertions.
_SIMPLIFIED = set("电线这为时还应发达变项预备点务议机险问题实际们没过")
_BANNED = ("一定", "保證", "絕對", "完全安全", "確定安全", "所有必要目標都能完成", "風正在減弱")
_FIELD_NAMES = ("end_pct", "end_pct_raw", "missed_required", "feasible", "energy_feasible",
                "completion_pct", "choice_id", "evidence_ids", "operational_status", "rule_decision")
_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])(?:E\d+|C\d+|RTL|WP\d+)(?![A-Za-z0-9_])")
_OPTION = re.compile(r"(?<![A-Za-z0-9_])C\d+(?![A-Za-z0-9_])")
_NUMBER = re.compile(r"(?<![0-9A-Za-z_.])[+\-−]?(?:\d+(?:\.\d+)?|\.\d+)%?(?![\d.])")
_METRIC_LABELS = {"end_pct": ("落地電量",),
                  "nominal_end_pct": ("落地電量",),
                  "completion_pct": ("任務完成度",),
                  "reserve_pct": ("保留電量",),
                  "wind_speed": ("風速",), "current_a": ("電流",),
                  "voltage_v": ("電壓",), "eta_s": ("所需時間", "抵達時間")}


def _metric_family(metric):
    return "end_pct" if metric == "nominal_end_pct" else metric


def _metric_aliases(e):
    aliases = list(_METRIC_LABELS.get(e["metric"], ()))
    aliases += [e.get("metric_label", ""), e.get("text", ""), e["metric"]]
    aliases += e.get("metric_labels", [])
    # Exclude only known ambiguous aliases, including producer-supplied aliases.
    # 風速/電流/電壓 and short custom metric names remain valid full labels.
    ambiguous = {"落地", "保留", "完成度"}
    return [a.strip() for a in aliases
            if isinstance(a, str) and a.strip() and a.strip() not in ambiguous]


def _claim_clause(sentence, start, end):
    # Inspect the whole claim, including metric names AFTER the numeric value.
    return (re.split(r"[，,；;：:。！？!?]", sentence[:start])[-1]
            + sentence[start:end]
            + re.split(r"[，,；;：:。！？!?]", sentence[end:])[0])


def _mentioned_metrics(clause, evidence):
    # Inspect uncited rows and known labels too: citing only one metric cannot
    # conceal a second measurement in the same clause.
    rows = [{"metric": metric} for metric in _METRIC_LABELS] + list(evidence)
    return {_metric_family(e["metric"]) for e in rows
            if any(alias in clause for alias in _metric_aliases(e))}


def _value_token(e):
    value = e.get("value")
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and not finite(value):
        return None
    text = str(value).strip()
    # Values are scalar canonical display tokens, optionally with an explicit unit.
    unit = e.get("unit", "")
    if not isinstance(unit, str):
        return None
    if unit and not text.endswith(unit):
        text += unit
    tokens = list(_NUMBER.finditer(text))
    # A, V and other word-character units need a separator for token extraction.
    if not tokens and unit and text.endswith(unit):
        tokens = list(_NUMBER.finditer(text[:-len(unit)].strip()))
    return tokens[0].group() if len(tokens) == 1 else None


def _mask_cited_probe_ids(text, cited):
    """Mask only exact categorical probe IDs alongside their cited metric label.

    An evidence producer may declare a categorical ID, such as A. It is a source value,
    never a unit or a blanket permission for arbitrary Latin words/numbers.
    Preserve offsets so numeric coverage can share this mask.
    """
    for e in cited:
        value = e.get("value")
        if (e.get("value_kind") != "categorical_id"
                or e.get("option_id") is not None or e.get("unit") != ""
                or not isinstance(value, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,31}", value)):
            continue
        labels = [e.get("metric_label"), e.get("text")]
        if not any(isinstance(label, str) and label and label in text for label in labels):
            continue
        pattern = r"(?<![A-Za-z0-9_-])" + re.escape(value) + r"(?![A-Za-z0-9_-])"
        text = re.sub(pattern, lambda m: " " * len(m.group()), text)
    return text


def _mask_bound_display_values(sentence, cited, selected, evidence):
    """Bind a complete shortage display to one cited option/metric, never its parts.

    The producer retains the canonical signed value. Only its exact shortage
    display may cover extra digits (zero and magnitude); scalar binding below
    remains unchanged for canonical values and every other numeric claim.
    """
    displays = {e.get("display_value") for e in cited
                if isinstance(e.get("display_value"), str)
                and e.get("unit") == "%"
                and re.fullmatch(r"[-−]\d+(?:\.\d+)?%", _value_token(e) or "")
                and re.fullmatch(r"低於 0%（短缺 (?:小於 )?\d+(?:\.\d+)?%）",
                                 e["display_value"])}
    masked = list(sentence)
    for display in displays:
        for match in re.finditer(re.escape(display), sentence):
            before = sentence[:match.start()]
            clause = _claim_clause(sentence, match.start(), match.end())
            metrics = _mentioned_metrics(clause, evidence)
            options = list(_OPTION.finditer(before))
            option = options[-1].group() if options else selected
            bindings = set()
            for e in cited:
                if e.get("display_value") != display or e["option_id"] != option:
                    continue
                if metrics == {_metric_family(e["metric"])}:
                    bindings.add((e["option_id"], e["metric"]))
            if len(bindings) != 1:
                return sentence, "顯示值無法綁定同一選項與指標"
            masked[match.start():match.end()] = " " * (match.end() - match.start())
    return "".join(masked), None


def validate(output, facts, current):
    """Evidence rows: id, option_id (nullable), metric, value, unit, segment, relation.

    text/metric_label/metric_labels may supply exact display aliases for the metric.
    current is mandatory: {active, alert_version, feasible_ids}. Never substitute
    a stale request's allowed_ids for current feasibility.
    """
    if not isinstance(output, dict) or not isinstance(facts, dict) or not isinstance(current, dict):
        return "輸出、facts 與目前狀態必須是物件"
    if ("alert_version" not in output or "alert_version" not in facts
            or current.get("active") is not True
            or output["alert_version"] != facts["alert_version"]
            or output["alert_version"] != current.get("alert_version")):
        return "告警不存在或版本已變更"
    allowed, feasible = facts.get("allowed_ids"), current.get("feasible_ids")
    if (not isinstance(allowed, list) or not isinstance(feasible, (list, tuple, set))
            or any(not isinstance(x, str) for x in [*allowed, *feasible])):
        return "允許集合與目前可行集合格式錯誤"
    if "selected_id" not in output:
        return "缺 selected_id"
    selected = output["selected_id"]
    if allowed:
        if not isinstance(selected, str) or selected not in allowed or selected not in feasible:
            return "selected_id 不在目前允許且可行集合"
    elif selected is not None:
        return "沒有允許選項時 selected_id 必須是 null"
    sentences = output.get("sentences")
    if (not isinstance(sentences, list) or len(sentences) != 2
            or any(not isinstance(s, str) or not s.strip() or len(s) > MAX_SENTENCE_CHARS
                   or len([p for p in re.split(r"[。！？!?]+", s) if p.strip()]) > 1
                   for s in sentences)):
        return "sentences 必須正好兩句、非空且各不超過60字"
    rows = facts.get("evidence")
    if not isinstance(rows, list) or any(not isinstance(e, dict) for e in rows):
        return "依據格式錯誤"
    required = {"id", "option_id", "metric", "value", "unit", "segment", "relation"}
    if any(not required <= e.keys() or not isinstance(e["id"], str)
           or not re.fullmatch(r"E\d+", e["id"]) or not isinstance(e["metric"], str)
           or not e["metric"] or (e["option_id"] is not None and
                                  not isinstance(e["option_id"], str)) for e in rows):
        return "依據缺少v5綁定欄位"
    evidence = {e["id"]: e for e in rows}
    if len(evidence) != len(rows):
        return "依據ID重複"
    ids = output.get("evidence_ids")
    if (not isinstance(ids, list) or not ids or
            any(not isinstance(x, str) or x not in evidence for x in ids)):
        return "evidence_ids 必須非空且全部存在"
    cited = [evidence[x] for x in ids]
    text = "\n".join(sentences)
    fields = set(_FIELD_NAMES) | {e["metric"] for e in rows if "_" in e["metric"]}
    if any(f in text for f in fields) or re.search(r"\b[A-Za-z]+_[A-Za-z_]+\b", text):
        return "說明寫出內部欄位名稱"
    if any(ch in _SIMPLIFIED for ch in text):
        return "說明用了簡體字"
    # Only cited, exact evidence labels may contain ordinal words such as 第一個.
    # Keep the original text for all other checks, including numeric binding.
    quantity_text = text
    labels = {e.get(key) for e in cited for key in ("metric_label", "text")
              if isinstance(e.get(key), str) and e.get(key)}
    for label in sorted(labels, key=len, reverse=True):
        quantity_text = quantity_text.replace(label, " " * len(label))
    if re.search(r"百分之[零〇一二兩三四五六七八九十百千萬億]+|[零〇一二兩三四五六七八九十百千萬億]+(?:%|秒|安培|伏特|公尺|瓦時|成|個|筆)", quantity_text):
        return "數字須使用依據的原樣數字，不接受中文數字換寫"
    assertions = {a for e in cited for a in e.get("assertions", []) if isinstance(a, str)}
    if any(b in text and b not in assertions for b in _BANNED):
        return "說明含沒有依據的斷言"
    # Latin identifiers are restricted to public IDs and units actually in evidence.
    public = _IDENTIFIER.sub("", "\n".join(_mask_cited_probe_ids(s, cited) for s in sentences))
    units = {e["unit"] for e in cited if isinstance(e["unit"], str) and e["unit"]}
    for unit in sorted(units, key=len, reverse=True):
        public = public.replace(unit, "")
    if re.search(r"[A-Za-z_]", public):
        return "說明含未允許的內部識別字"
    for sentence in sentences:
        display_text, display_reason = _mask_bound_display_values(sentence, cited, selected, facts["evidence"])
        if display_reason:
            return display_reason
        # All masks preserve offsets into the original sentence.
        numeric_text = _IDENTIFIER.sub(lambda m: " " * len(m.group()),
                                       _mask_cited_probe_ids(display_text, cited))
        matches = list(_NUMBER.finditer(numeric_text))
        covered = {i for match in matches for i in range(match.start(), match.end())}
        # Malformed numbers must not vanish between token boundaries (.5, 1.2.3).
        if any(ch.isdecimal() and i not in covered for i, ch in enumerate(numeric_text)):
            return "說明含無法辨識或綁定的數字"
        for match in matches:
            number = match.group()
            before = sentence[:match.start()]
            # Commas delimit claims, but an earlier C ID can scope later clauses.
            clause = _claim_clause(sentence, match.start(), match.end())
            metrics = _mentioned_metrics(clause, facts["evidence"])
            option_matches = list(_OPTION.finditer(before))
            option = option_matches[-1].group() if option_matches else selected
            candidates = []
            for e in cited:
                if e["option_id"] != option or _value_token(e) != number:
                    continue
                if metrics != {_metric_family(e["metric"])}:
                    continue
                unit = e["unit"]
                after = sentence[match.end():].lstrip()
                if unit == "%" and not number.endswith("%"):
                    continue
                if unit and unit != "%" and not after.startswith(unit):
                    continue
                candidates.append(e)
            # A value alone is insufficient: the metric/option binding must be unique.
            if len({(e["option_id"], e["metric"]) for e in candidates}) != 1:
                return f"數字無法綁定同一選項與指標：{number}"
    return None
