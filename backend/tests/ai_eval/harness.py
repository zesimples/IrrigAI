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
    latest = context.get("latest_recommendation") or {}
    if latest.get("action") not in {"skip", "defer"}:
        return
    assert interpretation.risk_level == "low"
    assert "não reg" in interpretation.irrigation_advice.lower()
    assert all("urgente" not in action.lower() for action in interpretation.recommended_actions)


def assert_farm_urgent_actions_match_engine(
    interpretation: AgronomicInterpretation,
    context: dict,
) -> None:
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
        for segment in re.split(r"[\n.;]", text)
        if "rega urgente" in segment.lower()
    ]
    for segment in urgent_segments:
        if not irrigating:
            raise AssertionError(f"urgent irrigation claimed with no irrigate action: {segment!r}")
        named = {name for name in actions if name.lower() in segment.lower()}
        assert named, f"urgent irrigation does not identify an engine-irrigate sector: {segment!r}"
        invalid = named - irrigating
        assert not invalid, f"non-irrigate sectors listed as urgent: {sorted(invalid)}"
