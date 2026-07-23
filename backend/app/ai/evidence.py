"""Backend-owned evidence registry for verifiable LLM citations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.schemas.ai import AgronomicCitation, AgronomicEvidence
from app.utils.format_pt import fmt_pt

_FIELD_LABELS = {
    "action": "Decisão",
    "recommendation_action": "Decisão",
    "confidence_score": "Confiança",
    "confidence_level": "Nível de confiança",
    "depletion_mm": "Depleção",
    "taw_mm": "Água total disponível",
    "raw_mm": "Limiar de rega",
    "etc_mm": "Consumo da cultura",
    "et0_mm": "Evapotranspiração de referência",
    "rainfall_mm": "Chuva",
    "rain_effective_mm": "Chuva efectiva",
    "rain_skip_applies": "Efeito da chuva na decisão",
    "irrigation_depth_mm": "Dotação recomendada",
    "irrigation_runtime_min": "Tempo de rega",
    "probe_external_id": "Sonda",
    "sector_name": "Sector",
    "soil_texture": "Textura do solo",
    "root_depth_cm": "Profundidade radicular",
    "analysis_window_hours": "Período analisado",
    "n_irrigation_events_in_window": "Regas no período",
    "last_irrigation_applied_mm": "Última rega aplicada",
    "last_irrigation_event_source": "Origem da última rega",
    "n_readings": "Leituras",
    "humidade_actual": "Humidade actual",
    "tendencia": "Tendência",
    "sinal_estavel": "Estabilidade do sinal",
    "causa_sinal_estavel": "Leitura do sinal",
    "profundidade_alem_raizes": "Posição face às raízes",
    "variabilidade_sinal": "Variabilidade do sinal",
    "variacao_24h": "Variação em 24 h",
    "variacao_48h": "Variação em 48 h",
    "resposta_rega": "Resposta à rega",
    "horas_ate_pico_apos_rega": "Tempo até ao pico após rega",
    "quality": "Qualidade da leitura",
    "status": "Estado",
    "severity": "Gravidade",
    "title": "Alerta",
    "fresh_depths": "Profundidades com dados recentes",
    "stale_depths": "Profundidades com dados antigos",
    "dead_depths": "Profundidades sem dados",
    "recommended_depth_mm": "Dotação recomendada",
    "actual_applied_mm": "Dotação aplicada",
    "dose_error_mm": "Desvio da dotação",
    "dose_error_pct": "Desvio da dotação",
    "event_count": "Regas avaliadas",
    "pending_candidate_count": "Calibrações pendentes",
    "response": "Resposta da sonda",
}

_PATH_SUFFIX_LABELS = {
    "soil_bounds.source": "Origem dos limites do solo",
    "scope.sector.name": "Sector",
    "scope.sector.crop_type": "Cultura",
    "scope.sector.variety": "Variedade",
    "scope.sector.phenological_stage": "Fase fenológica",
    "scope.sector.current_phenological_stage": "Fase fenológica",
    "scope.sector.area_ha": "Área",
}

_VALUE_LABELS = {
    "irrigate": "Regar",
    "skip": "Não regar",
    "defer": "Adiar rega",
    "reduce": "Reduzir rega",
    "increase": "Aumentar rega",
    "low": "Baixa",
    "medium": "Média",
    "high": "Alta",
    "critical": "Crítica",
    "warning": "Aviso",
    "info": "Informação",
    "matched": "Execução associada",
    "pending": "Pendente",
    "active": "Activo",
    "confirmed": "Confirmado",
    # Soil textures (same Portuguese names as the configured soil presets).
    "sand": "Areia",
    "loamy_sand": "Areia-franca",
    "sandy_loam": "Franco-arenoso",
    "loam": "Franco",
    "silty_loam": "Franco-limoso",
    "silt": "Limo",
    "sandy_clay_loam": "Franco-argilo-arenoso",
    "clay_loam": "Franco-argiloso",
    "silty_clay_loam": "Franco-argilo-limoso",
    "silty_clay": "Argilo-limoso",
    "clay": "Argila",
    "sandy_clay": "Argilo-arenoso",
    "custom": "Personalizado",
    # Deterministic engine provenance codes.
    "scp_override": "Configuração específica do sector",
    "probe_calibrated": "Calibração da sonda",
    "scp": "Perfil da cultura do sector",
    "plot_preset": "Textura configurada no talhão",
    "default": "Valor predefinido",
    "probe_weighted": "Média ponderada das sondas",
    "water_balance": "Balanço hídrico",
    "water_balance_model": "Modelo de balanço hídrico",
    "default_estimate": "Estimativa predefinida",
    "manual": "Registo manual",
    "probe_detected": "Detectada pela sonda",
    "flowmeter_detected": "Detectada pelo caudalímetro",
    "configured": "Configuração do sistema",
    "probe_learned": "Aprendida pela sonda",
    "mm_only": "Apenas dotação em milímetros",
    # Crop and phenological codes stored by the deterministic domain model.
    "olive": "Olival",
    "almond": "Amendoal",
    "maize": "Milho",
    "tomato": "Tomate",
    "vineyard": "Vinha",
    "olive_dormancy": "Dormência",
    "olive_bud_break": "Abrolhamento",
    "olive_budbreak": "Abrolhamento",
    "olive_flowering": "Floração",
    "olive_fruit_set": "Vingamento",
    "olive_pit_hardening": "Endurecimento do caroço",
    "olive_oil_accumulation": "Acumulação de azeite",
    "olive_veraison": "Pintor",
    "olive_harvest": "Colheita",
    "olive_post_harvest": "Pós-colheita",
    "almond_dormancy": "Dormência",
    "almond_bloom": "Floração",
    "almond_fruit_set": "Vingamento",
    "almond_shell_expansion": "Expansão da casca",
    "almond_kernel_fill": "Enchimento do miolo",
    "almond_hull_split": "Abertura do pericarpo",
    "almond_post_harvest": "Pós-colheita",
    "vine_dormancy": "Dormência",
    "vine_bleeding": "Choro",
    "vine_budbreak": "Abrolhamento",
    "vine_shoot_growth": "Crescimento do lançamento",
    "vine_flowering": "Floração",
    "vine_fruit_set": "Vingamento",
    "vine_berry_growth": "Crescimento da baga",
    "vine_veraison": "Pintor",
    "vine_ripening": "Maturação",
    "vine_harvest": "Colheita",
    "vine_post_harvest": "Pós-colheita",
    "maize_emergence": "Emergência–V6",
    "maize_vegetative": "V6–VT (crescimento)",
    "maize_tasseling": "VT–R1 (pendoamento)",
    "maize_grain_fill": "R1–R3 (enchimento)",
    "maize_maturation": "R4–R6 (maturação)",
    # Runtime and outcome states.
    "executed": "Rega executada",
    "followed_skip": "Decisão de não regar seguida",
    "no_event": "Sem rega associada",
    "candidate": "Candidata",
    "applied": "Aplicada",
    "superseded": "Substituída",
    "fresh": "Recente",
    "stale": "Antiga",
    "dead": "Sem dados",
    "ok": "Boa",
    "error": "Erro",
    "offline": "Sem ligação",
}

_PROBE_RESPONSE_VALUE_LABELS = {
    "increase": "Humidade aumentou",
    "stable": "Sem alteração clara",
    "decrease": "Humidade diminuiu",
}

_UNIT_LABELS = {
    "degC": "°C",
    "degree-days": "GDD",
    "mm/day": "mm/dia",
    "min": "min",
    "h": "h",
    "%": "%",
}

_VWC_FIELD_PARTS = (
    "vwc",
    "swc",
    "field_capacity",
    "wilting_point",
    "observed_fc",
    "observed_refill",
    "pwp",
)
_NON_CITABLE_PARTS = ("known_limitations", "missing_config", "units")
_NON_CITABLE_FIELDS = {
    # Identifiers and standalone list coordinates describe where data came from,
    # but do not verify an agronomic statement. Depth is added to the label of
    # the reading it qualifies instead.
    "probe_id",
    "probe_external_id",
    "farm_id",
    "plot_id",
    "sector_id",
    "recommendation_id",
    "depth_cm",
    "id",
    "created_at",
    "updated_at",
    "observed_at",
    "generated_at",
    "computed_at",
    "evaluated_at",
    "pre_irrigation_vwc",
    "post_irrigation_vwc",
    "probe_response_delta",
}

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_INTERNAL_CODE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


@dataclass(frozen=True)
class EvidenceEntry:
    evidence_id: str
    source: str
    value: str
    label: str

    def to_evidence(self) -> AgronomicEvidence:
        return AgronomicEvidence(
            evidence_id=self.evidence_id,
            source=self.source,
            value=self.value,
            label=self.label,
        )


class EvidenceRegistry:
    def __init__(self, entries: list[EvidenceEntry]):
        self._by_id = {entry.evidence_id: entry for entry in entries}
        self._by_path = {entry.source: entry for entry in entries}

    @property
    def entries(self) -> tuple[EvidenceEntry, ...]:
        return tuple(self._by_path.values())

    def entry_for_path(self, path: str) -> EvidenceEntry | None:
        return self._by_path.get(path)

    def first_entry_under(self, path: str) -> EvidenceEntry | None:
        direct = self.entry_for_path(path)
        if direct is not None:
            return direct
        prefix = f"{path}."
        list_prefix = f"{path}["
        return next(
            (
                entry
                for source, entry in self._by_path.items()
                if source.startswith(prefix) or source.startswith(list_prefix)
            ),
            None,
        )

    def resolve_citations(
        self,
        citations: list[AgronomicCitation],
        *,
        limit: int = 5,
    ) -> list[AgronomicEvidence]:
        resolved: list[AgronomicEvidence] = []
        seen_ids: set[str] = set()
        seen_labels: set[str] = set()
        for citation in citations:
            entry = self._by_id.get(citation.evidence_id)
            label_key = entry.label.casefold() if entry else ""
            if entry is None or entry.evidence_id in seen_ids or label_key in seen_labels:
                continue
            resolved.append(entry.to_evidence())
            seen_ids.add(entry.evidence_id)
            seen_labels.add(label_key)
            if len(resolved) >= limit:
                break
        return resolved

    def evidence_for_paths(self, paths: list[str], limit: int = 4) -> list[AgronomicEvidence]:
        evidence: list[AgronomicEvidence] = []
        seen_labels: set[str] = set()
        for path in paths:
            entry = self.entry_for_path(path)
            label_key = entry.label.casefold() if entry else ""
            if entry is not None and label_key not in seen_labels:
                evidence.append(entry.to_evidence())
                seen_labels.add(label_key)
            if len(evidence) >= limit:
                break
        return evidence

    def prompt_catalog(self) -> str:
        """Compact ID→path mapping; values already exist in the supplied context."""
        return "\n".join(f"- {entry.evidence_id}: {entry.source}" for entry in self.entries)


def build_evidence_registry(context: dict | list | None) -> EvidenceRegistry:
    entries: list[EvidenceEntry] = []
    if isinstance(context, (dict, list)):
        _walk(context, path="", root=context, entries=entries)
    return EvidenceRegistry(entries)


def _walk(
    value,
    *,
    path: str,
    root: dict | list,
    entries: list[EvidenceEntry],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _walk(child, path=child_path, root=root, entries=entries)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _walk(child, path=f"{path}[{index}]", root=root, entries=entries)
        return
    if value is None or not path or not _is_citable(path):
        return

    unit = _unit_for_path(root, path)
    if unit == "m3/m3":
        return
    label = _label_for_path(root, path)
    display_value = _display_value(value, unit, path=path)
    if label is None or display_value is None:
        return
    entries.append(
        EvidenceEntry(
            evidence_id=_evidence_id(path),
            source=path,
            value=display_value,
            label=label,
        )
    )


def _is_citable(path: str) -> bool:
    lowered = path.lower()
    segments = lowered.replace("[", ".").replace("]", "").split(".")
    field = segments[-1]
    if lowered == "schema_version":
        return False
    if field in _NON_CITABLE_FIELDS or field.endswith("_id"):
        return False
    if len(segments) == 2 and segments[-1] in {"observed_at", "source"}:
        return False
    if any(part in segments for part in _NON_CITABLE_PARTS):
        return False
    return not any(part in segments or part in segments[-1] for part in _VWC_FIELD_PARTS)


def _evidence_id(path: str) -> str:
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
    return f"ev_{digest}"


def _unit_for_path(root: dict | list, path: str) -> str | None:
    field = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if not isinstance(root, dict):
        return _inferred_unit(path, field)
    top = path.split(".", 1)[0].split("[", 1)[0]
    block = root.get(top)
    if not isinstance(block, dict):
        return _inferred_unit(path, field)
    units = block.get("units")
    if not isinstance(units, dict):
        return _inferred_unit(path, field)
    unit = units.get(field)
    if unit:
        return str(unit)
    return _inferred_unit(path, field)


def _inferred_unit(path: str, field: str) -> str | None:
    """Supply obvious units for probe statistics, which have no unit map."""
    if not path.startswith(("probe_signal.", "probe_state.", "probe_summary.")):
        return None
    if field.endswith("_cm"):
        return "cm"
    if field.endswith("_mm"):
        return "mm"
    if field.endswith("_pct") or field.endswith("_percent"):
        return "%"
    if field.endswith("_hours") or field.startswith("hours_"):
        return "h"
    if field.endswith("_min"):
        return "min"
    return None


def _display_value(
    value,
    unit: str | None,
    *,
    path: str = "",
) -> str | None:
    if isinstance(value, bool):
        display = "Sim" if value else "Não"
    elif isinstance(value, float):
        if value.is_integer():
            display = fmt_pt(value, 0)
        else:
            display = fmt_pt(value, 2).rstrip("0").rstrip(",")
    elif isinstance(value, int):
        display = str(value)
    else:
        raw = str(value)
        lowered = raw.lower()
        if "probe_response_by_depth" in path and path.endswith(".response"):
            display = _PROBE_RESPONSE_VALUE_LABELS.get(lowered)
        else:
            display = _VALUE_LABELS.get(lowered)
        if display is None:
            if _UUID_RE.fullmatch(raw) or _INTERNAL_CODE_RE.fullmatch(raw):
                return None
            display = raw
    unit_label = _UNIT_LABELS.get(unit or "", unit)
    return f"{display} {unit_label}" if unit_label else display


def _label_for_path(root: dict | list, path: str) -> str | None:
    for suffix, label in _PATH_SUFFIX_LABELS.items():
        if path == suffix or path.endswith(f".{suffix}"):
            return label
    field = path.rsplit(".", 1)[-1].split("[", 1)[0]
    field_label = _FIELD_LABELS.get(field)
    if field_label:
        depth_cm = _sibling_depth_cm(root, path)
        if depth_cm is not None:
            depth = _display_value(depth_cm, "cm")
            return f"{field_label} a {depth}" if depth else field_label
        return field_label
    return None


def _sibling_depth_cm(root: dict | list, path: str) -> int | float | str | None:
    """Return the depth belonging to a per-layer probe evidence path."""
    if not path.startswith(("probe_signal.", "probe_state.", "probe_summary.")):
        return None

    current: object = root
    tokens = [key if key else int(index) for key, index in _PATH_TOKEN_RE.findall(path)]
    try:
        for token in tokens[:-1]:
            current = current[token]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None

    if not isinstance(current, dict):
        return None
    depth = current.get("depth_cm")
    if isinstance(depth, (int, float, str)) and not isinstance(depth, bool):
        return depth
    return None
