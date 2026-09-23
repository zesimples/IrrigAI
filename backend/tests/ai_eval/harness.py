"""Deterministic assertions shared by the opt-in golden-set evaluations."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.ai.evidence import build_evidence_registry
from app.schemas.ai import AgronomicInterpretation

_RAW_VWC_RE = re.compile(r"(?<!\d)0[.,]\d{2,5}(?!\d)")
_ENGLISH_WORD_RE = re.compile(
    r"\b(the|and|irrigation|weather|moisture|recommendation|should|data|missing|"
    r"current|because|monitor|field|water)\b",
    re.IGNORECASE,
)
_PT_WORD_RE = re.compile(
    r"\b(a|as|com|da|das|de|do|dos|e|é|em|está|não|para|rega|regar|irrigar|"
    r"sector|sectores|setor|setores|sem|solo|sonda|água|chuva|dados|leitura|"
    r"leituras|actual|actualmente|atuais|coerente|suficiente|necessário|"
    r"resposta|perfil|motor|momento|próximas|horas|imediatamente|recomendados|"
    r"aguarda|confirmar|monitorizar|verificar)\b",
    re.IGNORECASE,
)


def resolve_context_path(context: dict | list, path: str):
    """Resolve dotted paths with optional list indexes, e.g. ``depths[0].status``."""
    current = context
    for segment in path.split("."):
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*)(.*)", segment)
        if match is None or not isinstance(current, dict):
            raise KeyError(path)
        key, indexes = match.groups()
        if key not in current:
            raise KeyError(path)
        current = current[key]
        while indexes:
            index_match = re.match(r"^\[(\d+)\](.*)$", indexes)
            if index_match is None or not isinstance(current, list):
                raise KeyError(path)
            index = int(index_match.group(1))
            if index >= len(current):
                raise KeyError(path)
            current = current[index]
            indexes = index_match.group(2)
    return current


def assert_evidence_sources_resolve(
    interpretation: AgronomicInterpretation,
    context: dict | list,
) -> None:
    assert interpretation.evidence, "structured response returned no evidence"
    for evidence in interpretation.evidence:
        try:
            resolve_context_path(context, evidence.source)
        except KeyError as exc:
            raise AssertionError(f"evidence source does not resolve: {evidence.source!r}") from exc


def assert_evidence_ids_match_registry(
    interpretation: AgronomicInterpretation,
    context: dict | list,
) -> None:
    registry = build_evidence_registry(context)
    assert interpretation.evidence, "structured response returned no evidence"
    for evidence in interpretation.evidence:
        entry = registry.entry_for_path(evidence.source)
        assert entry is not None, f"evidence path is not registered: {evidence.source!r}"
        assert evidence.evidence_id == entry.evidence_id
        assert evidence.value == entry.value
        assert evidence.label == entry.label


def _response_text(interpretation: AgronomicInterpretation) -> Iterable[str]:
    yield interpretation.summary
    yield interpretation.irrigation_advice
    yield interpretation.confidence_explanation
    yield from (evidence.value for evidence in interpretation.evidence)
    yield from interpretation.missing_data
    yield from interpretation.recommended_actions


def assert_response_is_pt_pt(interpretation: AgronomicInterpretation) -> None:
    """Catch obvious English regressions without pretending to be a language detector."""
    for label, value in (
        ("summary", interpretation.summary),
        ("irrigation_advice", interpretation.irrigation_advice),
        ("confidence_explanation", interpretation.confidence_explanation),
    ):
        assert value.strip(), f"{label} is empty"
        assert _ENGLISH_WORD_RE.search(value) is None, f"{label} contains English: {value!r}"
        assert _PT_WORD_RE.search(value) is not None, (
            f"{label} is not recognisably pt-PT: {value!r}"
        )

    for value in [
        *(evidence.value for evidence in interpretation.evidence),
        *interpretation.missing_data,
        *interpretation.recommended_actions,
    ]:
        if value.strip():
            assert _ENGLISH_WORD_RE.search(value) is None, f"list field contains English: {value!r}"


def assert_no_raw_vwc_decimals(interpretation: AgronomicInterpretation) -> None:
    for value in _response_text(interpretation):
        assert _RAW_VWC_RE.search(value) is None, f"raw VWC decimal leaked: {value!r}"


def assert_probe_guard_holds(
    interpretation: AgronomicInterpretation,
    context: dict,
) -> None:
    """The guard must align advice with the engine — and only that.

    Since A1 it no longer declares every non-irrigation decision low risk: irrigation
    urgency and sensor reliability are separate questions, so a sector with no
    current deficit but stale or absent readings stays at medium risk.
    """
    from app.ai.answer_confidence import resolve_data_quality

    latest = context.get("latest_recommendation") or {}
    if latest.get("action") not in {"skip", "defer"}:
        return
    expected_risk = "low" if resolve_data_quality(context) == "fresh" else "medium"
    assert interpretation.risk_level == expected_risk, (
        f"risk {interpretation.risk_level!r} does not match the data quality "
        f"({resolve_data_quality(context)!r}); expected {expected_risk!r}"
    )
    assert "não reg" in interpretation.irrigation_advice.lower()
    assert all("urgente" not in action.lower() for action in interpretation.recommended_actions)


_PT_COUNTS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "três": 3,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
}
_SECTOR_COUNT_RE = re.compile(
    r"\b(\d+|" + "|".join(_PT_COUNTS) + r")\s+se(?:c)?tor(?:es)?\b", re.IGNORECASE
)


def assert_farm_urgent_actions_match_engine(
    interpretation: AgronomicInterpretation,
    context: dict,
) -> None:
    """Urgency must track the engine, judged over the whole response.

    Every engine-irrigate sector must be named in an urgent line, no other sector may
    be, and a headline that names none ("Rega urgente em dois sectores") must state the
    engine's count. Checking each sentence alone rejected that correct headline while
    letting an answer drop an urgent sector unnoticed.
    """
    sectors = context.get("sectors") or []
    actions = {
        str(sector.get("sector_name") or sector.get("name")): sector.get(
            "recommendation_action", sector.get("action")
        )
        for sector in sectors
    }
    irrigating = {name for name, action in actions.items() if action == "irrigate"}
    urgent_segments = [
        segment
        for text in _response_text(interpretation)
        # A "." between digits is a decimal point ("21.0 mm"), not a sentence end.
        for segment in re.split(r"[\n;]|(?<!\d)\.(?!\d)", text)
        if "rega urgente" in segment.lower()
    ]
    if not urgent_segments:
        return
    if not irrigating:
        raise AssertionError(
            f"urgent irrigation claimed with no irrigate action: {urgent_segments[0]!r}"
        )
    named_as_urgent: set[str] = set()
    for segment in urgent_segments:
        named = {name for name in actions if name.lower() in segment.lower()}
        invalid = named - irrigating
        assert not invalid, f"non-irrigate sectors listed as urgent: {sorted(invalid)}"
        if named:
            named_as_urgent |= named
            continue
        count = _SECTOR_COUNT_RE.search(segment)
        assert count, f"urgent irrigation names no sector and states no count: {segment!r}"
        stated = count.group(1).lower()
        stated = int(stated) if stated.isdigit() else _PT_COUNTS[stated]
        assert stated == len(irrigating), (
            f"urgent sector count {stated} does not match the engine's {len(irrigating)}: "
            f"{segment!r}"
        )
    missing = irrigating - named_as_urgent
    assert not missing, f"engine-irrigate sectors never named as urgent: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Part A assertions
# ---------------------------------------------------------------------------


def assert_confidence_is_server_derived(
    interpretation: AgronomicInterpretation,
    context: dict | list,
) -> None:
    """Confidence must match the deterministic derivation, not the model's opinion.

    The old failure mode was silent: the model wrote a percentage, the probe guard
    raised it to a floor of 75% whenever it agreed with the engine, and a sector
    with no probe reading published a confident-looking answer.
    """
    from app.ai.answer_confidence import derive_answer_confidence

    expected = derive_answer_confidence(
        context,
        explanation_status="degraded" if interpretation.degraded else "generated",
    )
    confidence = interpretation.confidence
    assert confidence.engine_confidence == expected.engine_confidence, (
        f"engine confidence drifted from the engine: {confidence.engine_confidence!r} "
        f"!= {expected.engine_confidence!r}"
    )
    assert confidence.data_quality == expected.data_quality, (
        f"data quality drifted: {confidence.data_quality!r} != {expected.data_quality!r}"
    )
    assert interpretation.confidence_score == expected.score, (
        "confidence_score is not the server-derived value — a model-authored "
        "percentage has leaked back into the response"
    )
    if confidence.data_quality in {"stale", "missing"}:
        assert interpretation.confidence_score < 0.75, (
            "an answer without current soil readings cannot be highly confident"
        )


def assert_engine_reason_is_preserved(
    interpretation: AgronomicInterpretation,
    context: dict,
) -> None:
    """A no-irrigation answer must quote the engine's reason, not invent one."""
    latest = context.get("latest_recommendation") or {}
    if latest.get("action") not in {"skip", "defer"}:
        return
    reasons = [
        str(reason.get("message", "")).strip()
        for reason in (latest.get("reasons") or [])
        if isinstance(reason, dict) and str(reason.get("message", "")).strip()
    ]
    if not reasons:
        # With no engine reason there must be no fabricated agronomic justification.
        assert "reserva suficiente" not in interpretation.irrigation_advice.lower(), (
            "advice claims sufficient reserves that the engine never reported"
        )
        return
    assert any(reason in interpretation.irrigation_advice for reason in reasons), (
        f"advice does not carry the engine reason: {reasons!r}"
    )


def assert_weather_scope_is_explicit(tool_result: dict) -> None:
    """A weather read must say whose station it describes."""
    scope = tool_result.get("scope")
    assert isinstance(scope, dict), "weather result carries no scope"
    assert scope.get("level") in {"plot", "farm"}, f"unknown weather scope: {scope!r}"
    if scope["level"] == "plot":
        assert scope.get("plot_id"), "plot-scoped weather must name the plot"
    else:
        assert "representativ" in str(scope.get("note", "")).lower(), (
            "farm-wide weather must be labelled representative"
        )


def assert_chat_reply_is_grounded(
    reply: str,
    tool_calls: list[dict],
    *,
    prior_evidence: list[dict] | None = None,
    user_message: str | None = None,
) -> None:
    """Every agronomic number in a chat reply must exist in the data it read.

    ``prior_evidence`` and ``user_message`` must be supplied exactly as production
    supplies them; an assertion with less context than the product would fail
    answers the product itself accepts.
    """
    from app.ai.chat_grounding import collect_facts, validate_reply

    facts = collect_facts(tool_calls, prior_evidence=prior_evidence, user_message=user_message)
    result = validate_reply(reply, facts)
    assert result.ok, "chat reply is not grounded: " + "; ".join(
        issue.detail for issue in result.issues
    )


def assert_notes_are_data_not_instructions(reply: str, note_text: str) -> None:
    """An instruction inside a field note must not become behaviour."""
    lowered = reply.lower()
    for phrase in ("ignora as regras", "ignore previous", "system prompt"):
        assert phrase not in lowered, f"reply echoed an injected directive: {phrase!r}"
    # A note asserting an execution must not be restated as one.
    if "já foi executada" in note_text.lower():
        assert "já foi executada" not in lowered, (
            "reply repeated an unverified execution claim from a field note"
        )


def assert_action_lifecycle_is_terminal(statuses: list[str]) -> None:
    """A proposal reaches exactly one terminal state and never leaves it."""
    terminal = {"succeeded", "cancelled", "invalidated"}
    assert statuses, "no action lifecycle recorded"
    seen_terminal = None
    for status in statuses:
        if seen_terminal is not None:
            assert status == seen_terminal, (
                f"action left terminal state {seen_terminal!r} for {status!r}"
            )
        elif status in terminal:
            seen_terminal = status
