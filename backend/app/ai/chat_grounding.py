"""Deterministic grounding checks for free-form chat answers.

Card surfaces have carried a server-resolved evidence registry since P2, but chat
prose went back to the user verbatim. Nothing stopped the model from inventing a
dose, repeating an unverified farmer note as a measurement, or advising irrigation
on a sector the engine had told to skip.

The checks here are deliberately narrow and deterministic:

* **Numbers with an agronomic unit** (mm, m³, %, °C, L) must appear in the data the
  turn actually read. Planning language ("nas próximas 24-48 horas") carries no
  measurement and is not checked — flagging it would only teach the model to drop
  useful timing advice.
* **Irrigation directives** require a current engine decision for the sector in
  scope and must follow its dose and action.

A valid citation is not proof that the prose follows from it, so this is a floor,
not a guarantee — the evaluation harness carries the semantic side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Units that denote a measured agronomic quantity. Time units are excluded on
# purpose: "24-48 horas" is a monitoring horizon, not a reading.
_UNIT_PATTERN = r"(mm/dia|mm|m³/ha|m3/ha|m³|m3|%|ºC|°C|L/h|L)"
_NUMBER_PATTERN = r"([+-]?\d{1,6}(?:[.,]\d{1,3})?)"
_CLAIM_RE = re.compile(rf"{_NUMBER_PATTERN}\s*{_UNIT_PATTERN}", re.IGNORECASE)

_UNIT_ALIASES = {
    "mm/dia": "mm",
    "mm": "mm",
    "m³/ha": "m3/ha",
    "m3/ha": "m3/ha",
    "m³": "m3",
    "m3": "m3",
    "%": "%",
    "ºc": "degC",
    "°c": "degC",
    "l/h": "L/h",
    "l": "L",
}

# Numeric context keys the tool results expose, grouped by the unit they carry.
_MM_KEYS = (
    "irrigation_depth_mm",
    "depletion_mm",
    "taw_mm",
    "raw_mm",
    "et0_mm",
    "etc_mm",
    "rainfall_mm",
    "rain_effective_mm",
    "recommended_depth_mm",
    "actual_applied_mm",
    "dose_error_mm",
    "last_irrigation_applied_mm",
    "forecast_rain_next_48h",
    "applied_mm",
    "depth_mm",
)
_PCT_KEYS = (
    "depletion_pct",
    "dose_error_pct",
    "humidity_pct",
    "rainfall_probability_pct",
)
_M3_HA_KEYS = ("total_m3_ha", "volume_m3_ha")
_DEGC_KEYS = ("temperature_max_c", "temperature_min_c", "temperature_c")

_KEYS_BY_UNIT: dict[str, tuple[str, ...]] = {
    "mm": _MM_KEYS,
    "%": _PCT_KEYS,
    "m3/ha": _M3_HA_KEYS,
    "degC": _DEGC_KEYS,
}
TOOL_MEASUREMENT_UNITS = {key: unit for unit, keys in _KEYS_BY_UNIT.items() for key in keys}

# Tool results whose content is user-authored text, not measured data. A note is a
# lead to validate; it may never become the evidence for a number in the answer.
_UNTRUSTED_TOOLS = {"get_field_observations"}

_NO_IRRIGATION_ACTIONS = {"skip", "defer"}

# A negation immediately before a directive inverts it: "não deves regar" contains
# "deves regar", and matching it as advice to irrigate made the validator reject the
# very answers it exists to protect. The live multi-turn evaluation found this.
_NEGATION = r"(?<!n[ãa]o )(?<!n[ãa]o se )(?<!sem )(?<!nunca )(?<!evita )(?<!evitar )"

_IRRIGATE_DIRECTIVE_RE = re.compile(
    _NEGATION + r"\b(deves?\s+regar|rega\s+(?:j[áa]|hoje|agora)|regar\s+(?:j[áa]|hoje|agora)|"
    r"rega\s+urgente|recomendo\s+regar|aplica(?:r)?|regue|regar\s+\d|"
    r"dota[çc][ãa]o\s+recomendada)\b",
    re.IGNORECASE,
)
_SKIP_DIRECTIVE_RE = re.compile(
    r"\b(n[ãa]o\s+reg(?:ues|ar|es)|salta\s+a\s+rega|adia(?:r)?\s+a\s+rega|"
    r"dispensa(?:r)?\s+a\s+rega)\b",
    re.IGNORECASE,
)

# Portuguese negation often sits several words before the verb ("não é necessário
# regar hoje"), which a fixed-width lookbehind cannot see. Scan the clause instead.
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<!\d)\.(?!\d)|[;!?\n]|\bmas\b|\bporém\b|\bcontudo\b", re.IGNORECASE
)
_NEGATED_CLAUSE_RE = re.compile(
    r"\b(n[ãa]o|nem|sem|nunca|dispensa|dispensar|evita|evitar|desnecess[áa]ri[oa]|"
    r"escusad[oa]|adia|adiar|aguarda|aguardar)\b",
    re.IGNORECASE,
)


def _advises(text: str, pattern: re.Pattern[str]) -> bool:
    """True only for a directive in a clause that does not negate it."""
    for clause in _CLAUSE_SPLIT_RE.split(text or ""):
        match = pattern.search(clause)
        if match is None:
            continue
        before = clause[: match.start()]
        if _NEGATED_CLAUSE_RE.search(before):
            continue
        return True
    return False


_ABSOLUTE_TOLERANCE = 0.05
_RELATIVE_TOLERANCE = 0.01


@dataclass(frozen=True)
class NumericClaim:
    value: float
    unit: str
    text: str


@dataclass(frozen=True)
class GroundingIssue:
    kind: str  # unsupported_number | engine_conflict
    detail: str


@dataclass(frozen=True)
class ValidationResult:
    issues: list[GroundingIssue]

    @property
    def ok(self) -> bool:
        return not self.issues

    def repair_instruction(self) -> str:
        """One bounded correction request, in the model's own working language."""
        lines = "\n".join(f"- {issue.detail}" for issue in self.issues)
        return (
            "A resposta anterior não está sustentada pelos dados lidos:\n"
            f"{lines}\n"
            "Reescreve a resposta usando apenas valores presentes nos resultados das "
            "campos numéricos medidos das ferramentas e sem contradizer a decisão do motor determinístico. Se um "
            "valor não existir, diz que não está disponível. Não repitas números "
            "introduzidos apenas pelo utilizador, nem como hipótese: refere-te a "
            "essa quantidade como 'a dotação que sugeres'. Remove também quantidades "
            "citadas em notas de campo e outros textos não verificados, mesmo que "
            "pretendas explicar que não são fiáveis. Não transcrevas a nota."
        )


@dataclass
class GroundedFacts:
    """Everything this turn is allowed to assert.

    Only this turn's scoped tool reads support measurements. Historical evidence
    and user hypotheses are retained as conversational context, never promoted to
    current facts. A farm overview keeps each sector's facts separate.
    """

    engine_action: str | None = None
    engine_depth_mm: float | None = None
    recommendation_id: str | None = None
    sector_name: str | None = None
    values: dict[str, set[float]] = field(default_factory=dict)
    quoted: dict[str, set[float]] = field(default_factory=dict)
    fields: dict[str, set[float]] = field(default_factory=dict)
    ambiguous_scope: bool = False
    by_sector: dict[str, GroundedFacts] = field(default_factory=dict)

    def add(self, unit: str, value: float) -> None:
        self.values.setdefault(unit, set()).add(round(float(value), 3))

    def add_quoted(self, unit: str, value: float) -> None:
        self.quoted.setdefault(unit, set()).add(round(float(value), 3))

    def supports(self, value: float, unit: str) -> bool:
        return self._matches(self.values.get(unit, ()), value)

    def is_measured(self, value: float, unit: str) -> bool:
        """True only for values that came from data, never from the user's question."""
        return self._matches(self.values.get(unit, ()), value)

    @staticmethod
    def _matches(known_values, value: float) -> bool:
        for known in known_values:
            if abs(known - value) <= _ABSOLUTE_TOLERANCE:
                return True
            if known and abs(known - value) / abs(known) <= _RELATIVE_TOLERANCE:
                return True
        return False

    @property
    def has_engine_decision(self) -> bool:
        return self.engine_action is not None


def normalize_unit(raw: str) -> str:
    return _UNIT_ALIASES.get(raw.strip().lower(), raw.strip())


def extract_numeric_claims(text: str) -> list[NumericClaim]:
    claims: list[NumericClaim] = []
    for match in _CLAIM_RE.finditer(text or ""):
        raw_number, raw_unit = match.group(1), match.group(2)
        try:
            value = float(raw_number.replace(",", "."))
        except ValueError:  # pragma: no cover - regex guarantees a number
            continue
        claims.append(NumericClaim(value=value, unit=normalize_unit(raw_unit), text=match.group(0)))
    return claims


def collect_facts(
    tool_calls: list[dict],
    *,
    prior_evidence: list[dict] | None = None,
    user_message: str | None = None,
    selected_sector_id: str | None = None,
) -> GroundedFacts:
    """Bind current tool results to their sector; never pool unrelated measurements."""
    grouped: dict[str, list[dict]] = {}
    unscoped: list[dict] = []
    for call in tool_calls or []:
        result = call.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        if call.get("tool") == "get_farm_overview":
            for sector in result.get("sectors", []):
                sector_id = sector.get("sector_id")
                if sector_id:
                    grouped.setdefault(str(sector_id), []).append(
                        {
                            "tool": "get_sector_status",
                            "result": sector,
                        }
                    )
            continue
        sector_id = result.get("sector_id") or call.get("sector_id") or selected_sector_id
        if sector_id:
            grouped.setdefault(str(sector_id), []).append(call)
        else:
            unscoped.append(call)
    if selected_sector_id:
        return _collect_single(grouped.get(selected_sector_id, []) + unscoped, user_message)
    if len(grouped) == 1:
        return _collect_single(next(iter(grouped.values())) + unscoped, user_message)
    if len(grouped) > 1:
        return GroundedFacts(
            ambiguous_scope=True,
            by_sector={key: _collect_single(calls, user_message) for key, calls in grouped.items()},
        )
    return _collect_single(unscoped, user_message)


def _collect_single(tool_calls: list[dict], user_message: str | None) -> GroundedFacts:
    facts = GroundedFacts()
    # Old citations and user hypotheses are not current measurements.
    for claim in extract_numeric_claims(user_message or ""):
        facts.add_quoted(claim.unit, claim.value)
    for call in tool_calls or []:
        name = str(call.get("tool") or "")
        result = call.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        if name in _UNTRUSTED_TOOLS:
            continue
        _harvest(result, facts)
        if name == "get_sector_status":
            if (
                facts.recommendation_id
                and result.get("recommendation_id")
                and result["recommendation_id"] != facts.recommendation_id
            ):
                facts.ambiguous_scope = True
                continue
            facts.engine_action = facts.engine_action or _clean_str(result.get("action"))
            facts.recommendation_id = facts.recommendation_id or _clean_str(
                result.get("recommendation_id")
            )
            facts.sector_name = facts.sector_name or _clean_str(result.get("name"))
            depth = _as_float(result.get("irrigation_depth_mm"))
            if depth is not None:
                facts.engine_depth_mm = depth
    return facts


def _harvest(node, facts: GroundedFacts) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            number = _as_float(value)
            if number is not None:
                for unit, keys in _KEYS_BY_UNIT.items():
                    if key in keys:
                        facts.add(unit, number)
                        facts.fields.setdefault(key, set()).add(number)
            else:
                _harvest(value, facts)
        return
    if isinstance(node, list):
        for item in node:
            _harvest(item, facts)


def _as_float(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _clean_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_reply(reply: str, facts: GroundedFacts) -> ValidationResult:
    issues: list[GroundingIssue] = []
    if not reply.strip():
        return ValidationResult([GroundingIssue("empty_reply", "A resposta está vazia.")])
    if facts.by_sector:
        for clause in _CLAUSE_SPLIT_RE.split(reply):
            if not extract_numeric_claims(clause) and not (
                _advises(clause, _IRRIGATE_DIRECTIVE_RE) or _advises(clause, _SKIP_DIRECTIVE_RE)
            ):
                continue
            matches = [
                item
                for item in facts.by_sector.values()
                if item.sector_name
                and re.search(
                    r"(?<!\w)" + re.escape(item.sector_name) + r"(?!\w)", clause, re.IGNORECASE
                )
            ]
            if len(matches) != 1:
                issues.append(
                    GroundingIssue(
                        "ambiguous_scope",
                        "Cada valor ou decisão deve identificar um único setor consultado.",
                    )
                )
            else:
                issues.extend(validate_reply(clause, matches[0]).issues)
        return ValidationResult(issues)

    for claim in extract_numeric_claims(reply):
        if not facts.supports(claim.value, claim.unit):
            issues.append(
                GroundingIssue(
                    kind="unsupported_number",
                    detail=(
                        f'O valor "{claim.text}" não existe nos dados consultados nesta conversa.'
                    ),
                )
            )

    advises = _advises(reply, _IRRIGATE_DIRECTIVE_RE)
    if advises and (not facts.has_engine_decision or facts.ambiguous_scope):
        issues.append(
            GroundingIssue(
                "missing_engine",
                "Selecciona um setor e consulta a sua decisão actual antes de aconselhar uma dotação.",
            )
        )
    for clause in _CLAUSE_SPLIT_RE.split(reply):
        matches = list(_CLAIM_RE.finditer(clause))
        for index, match in enumerate(matches):
            claim = extract_numeric_claims(match.group(0))[0]
            # Bind each quantity to its local label. A sentence can contain a
            # dose, depletion and rain; one label must not relabel every number.
            start = matches[index - 1].end() if index else 0
            end = matches[index + 1].start() if index + 1 < len(matches) else len(clause)
            prefix = clause[start : match.start()]
            suffix = clause[match.end() : end]
            local = prefix + match.group(0)
            trailing_label = re.match(
                r"\s+(?:de\s+)?(deple[çc][ãa]o|d[eé]fice|chuva|precipita[çc][ãa]o)\b",
                suffix,
                re.IGNORECASE,
            )
            if trailing_label:
                local += trailing_label.group(0)
            labels = list(
                re.finditer(
                    r"deple[çc][ãa]o|d[eé]fice|chuva|precipita[çc][ãa]o|"
                    r"dota[çc][ãa]o|aplica\w*|regar|\bTAW\b|\bET[₀0]\b|evapotranspira[çc][ãa]o",
                    local,
                    re.IGNORECASE,
                )
            )
            nearest_label = labels[-1].group(0) if labels else ""
            if (
                claim.unit == "mm"
                and _advises(local, _IRRIGATE_DIRECTIVE_RE)
                and (
                    facts.engine_depth_mm is None
                    or not facts._matches([facts.engine_depth_mm], claim.value)
                )
            ):
                issues.append(
                    GroundingIssue(
                        "engine_dose",
                        "A dotação aconselhada não corresponde à dotação actual do motor.",
                    )
                )
            for label, keys in (
                (
                    r"deple[çc][ãa]o|d[eé]fice",
                    ("depletion_mm",) if claim.unit == "mm" else ("depletion_pct",),
                ),
                (
                    r"chuva|precipita[çc][ãa]o",
                    ("rainfall_mm", "rain_effective_mm", "forecast_rain_next_48h"),
                ),
            ):
                if re.search(label, nearest_label, re.IGNORECASE) and not facts._matches(
                    [v for key in keys for v in facts.fields.get(key, ())], claim.value
                ):
                    issues.append(
                        GroundingIssue(
                            "field_mismatch",
                            "O valor não pertence ao indicador citado nos dados actuais.",
                        )
                    )

    if facts.has_engine_decision:
        action = facts.engine_action or ""
        if action in _NO_IRRIGATION_ACTIONS and advises:
            issues.append(
                GroundingIssue(
                    kind="engine_conflict",
                    detail=(
                        f'A resposta aconselha regar, mas a decisão do motor é "{action}" '
                        "(não regar) para este setor."
                    ),
                )
            )
        elif action == "irrigate" and _advises(reply, _SKIP_DIRECTIVE_RE):
            issues.append(
                GroundingIssue(
                    kind="engine_conflict",
                    detail=(
                        "A resposta aconselha não regar, mas a decisão do motor é regar este setor."
                    ),
                )
            )
    return ValidationResult(issues=issues)


_ACTION_SENTENCE_PT = {
    "irrigate": "A decisão do motor determinístico para este setor é regar.",
    "skip": "A decisão do motor determinístico para este setor é não regar.",
    "defer": "A decisão do motor determinístico para este setor é adiar a rega.",
    "reduce": "A decisão do motor determinístico para este setor é reduzir a rega.",
    "increase": "A decisão do motor determinístico para este setor é aumentar a rega.",
}


def deterministic_fallback_reply(facts: GroundedFacts) -> str:
    """Answer from engine outputs alone when the model cannot be trusted this turn."""
    if facts.by_sector:
        return "\n".join(
            f"{item.sector_name or 'Setor'}: {deterministic_fallback_reply(item)}"
            for item in facts.by_sector.values()
        )
    if not facts.has_engine_decision or facts.ambiguous_scope:
        return (
            "Não consigo sustentar uma resposta com os dados consultados neste momento. "
            "Consulta a recomendação determinística na página do sector."
        )
    parts = [_ACTION_SENTENCE_PT.get(facts.engine_action or "", "")]
    if facts.engine_action == "irrigate" and facts.engine_depth_mm is not None:
        parts.append(f"Dotação recomendada: {_fmt(facts.engine_depth_mm)} mm.")
    parts.append("Não apresento a explicação gerada porque não ficou sustentada pelos dados lidos.")
    return " ".join(part for part in parts if part)


def _fmt(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return (text or "0").replace(".", ",")


# ---------------------------------------------------------------------------
# Evidence selection
# ---------------------------------------------------------------------------

_ENGINE_EVIDENCE_SUFFIXES = (".action", ".irrigation_depth_mm", ".confidence_level")


def select_chat_evidence(
    reply: str, registry, limit: int = 5, *, scopes: dict[str, str] | None = None
) -> list:
    """Attach citations to the values the answer actually used.

    Card surfaces let the model pick evidence IDs; chat prose has no such field, so
    the server matches the numbers in the reply against the registry built from this
    turn's tool results. An entry is cited only when the answer uses its value —
    a citation list that does not correspond to the sentences is decoration.
    """

    def scoped_reply(entry):
        if scopes is None:
            return reply
        for prefix, name in scopes.items():
            if entry.source.startswith(prefix + "."):
                return " ".join(
                    clause
                    for clause in _CLAUSE_SPLIT_RE.split(reply)
                    if name
                    and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", clause, re.IGNORECASE)
                )
        return ""

    selected: list = []
    seen: set[str] = set()

    for entry in registry.entries:
        if len(selected) >= limit:
            break
        entry_claims = extract_numeric_claims(entry.value)
        if not entry_claims:
            continue
        for claim in extract_numeric_claims(scoped_reply(entry)):
            match = any(
                other.unit == claim.unit and abs(other.value - claim.value) <= _ABSOLUTE_TOLERANCE
                for other in entry_claims
            )
            if match and entry.evidence_id not in seen:
                selected.append(entry.to_evidence())
                seen.add(entry.evidence_id)
                break

    # The engine decision grounds the answer's direction even when no number is quoted.
    for entry in registry.entries:
        if len(selected) >= limit:
            break
        if (
            entry.source.endswith(_ENGINE_EVIDENCE_SUFFIXES)
            and entry.evidence_id not in seen
            and scoped_reply(entry)
        ):
            selected.append(entry.to_evidence())
            seen.add(entry.evidence_id)
    return selected


def collect_data_timestamps(tool_calls: list[dict]) -> dict:
    """When the cited data was observed, per source, so staleness is visible."""
    stamps: dict[str, str] = {}
    for call in tool_calls or []:
        result = call.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        for key in ("generated_at", "latest_observation_at", "observed_at", "computed_at"):
            value = result.get(key)
            if isinstance(value, str) and value:
                stamps[f"{call.get('tool')}.{key}"] = value
    return stamps
