"""Backend-owned evidence registry for verifiable LLM citations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.schemas.ai import AgronomicCitation, AgronomicEvidence
from app.utils.format_pt import fmt_pt

_TOP_LEVEL_LABELS = {
    "engine_decision": "Decisão",
    "water_balance": "Água no solo",
    "probe_state": "Estado da sonda",
    "probe_signal": "Estado da sonda",
    "probe_summary": "Estado da sonda",
    "weather": "Previsão do tempo",
    "weather_changes": "Meteorologia",
    "irrigation_execution": "Execução da rega",
    "water_events": "Eventos de água",
    "water_event_changes": "Eventos de água",
    "outcomes": "Eficácia da rega",
    "crop_state": "Estado da cultura",
    "calibration": "Calibração",
    "alerts_and_limitations": "Alertas e limitações",
    "alert": "Atenção",
    "recommendation_history": "Histórico",
    "recommendation_change": "Alteração da recomendação",
    "sectors": "Sectores",
}

_FIELD_LABELS = {
    "action": "Decisão",
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
}

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


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
    ) -> list[AgronomicEvidence]:
        resolved: list[AgronomicEvidence] = []
        seen: set[str] = set()
        for citation in citations:
            entry = self._by_id.get(citation.evidence_id)
            if entry is None or entry.evidence_id in seen:
                continue
            resolved.append(entry.to_evidence())
            seen.add(entry.evidence_id)
        return resolved

    def evidence_for_paths(self, paths: list[str], limit: int = 4) -> list[AgronomicEvidence]:
        evidence: list[AgronomicEvidence] = []
        for path in paths:
            entry = self.entry_for_path(path)
            if entry is not None:
                evidence.append(entry.to_evidence())
            if len(evidence) >= limit:
                break
        return evidence

    def prompt_catalog(self) -> str:
        """Compact ID→path mapping; values already exist in the supplied context."""
        return "\n".join(
            f"- {entry.evidence_id}: {entry.source}" for entry in self.entries
        )


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
    entries.append(
        EvidenceEntry(
            evidence_id=_evidence_id(path),
            source=path,
            value=_display_value(value, unit),
            label=_label_for_path(root, path),
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


def _display_value(value, unit: str | None) -> str:
    if isinstance(value, bool):
        display = "Sim" if value else "Não"
    elif isinstance(value, float):
        digits = 0 if value.is_integer() else 2
        display = fmt_pt(value, digits).rstrip("0").rstrip(",")
    elif isinstance(value, int):
        display = str(value)
    else:
        raw = str(value)
        display = _VALUE_LABELS.get(raw.lower(), raw)
    unit_label = _UNIT_LABELS.get(unit or "", unit)
    return f"{display} {unit_label}" if unit_label else display


def _label_for_path(root: dict | list, path: str) -> str:
    field = path.rsplit(".", 1)[-1].split("[", 1)[0]
    field_label = _FIELD_LABELS.get(field)
    if field_label:
        depth_cm = _sibling_depth_cm(root, path)
        if depth_cm is not None:
            return f"{field_label} a {_display_value(depth_cm, 'cm')}"
        return field_label
    top = path.split(".", 1)[0].split("[", 1)[0]
    return _TOP_LEVEL_LABELS.get(top, "Dados")


def _sibling_depth_cm(root: dict | list, path: str) -> int | float | str | None:
    """Return the depth belonging to a per-layer probe evidence path."""
    if not path.startswith(("probe_signal.", "probe_state.", "probe_summary.")):
        return None

    current: object = root
    tokens = [
        key if key else int(index)
        for key, index in _PATH_TOKEN_RE.findall(path)
    ]
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
