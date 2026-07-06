"""Dose-do-dia presentation — band classification + dose-source precedence.

Pure functions; same precedence idiom as engine/soil_bounds.resolve_soil_bounds.
The band is a PRESENTATION classifier over existing engine outputs — the
RecommendationAction enum, alerts and the AI probe-guard are untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.engine.dosage import DosageResult
from app.engine.irrigation_fingerprint import is_fingerprint_stale

DOSE_BAND_REFORCADA = "reforcada"
DOSE_BAND_NORMAL = "normal"
DOSE_BAND_CURTA = "curta"
DOSE_BAND_PODE_SALTAR = "pode_saltar"

DOSE_SOURCE_CONFIGURED = "configured"
DOSE_SOURCE_PROBE_LEARNED = "probe_learned"
DOSE_SOURCE_MM_ONLY = "mm_only"

_DEFAULT_MIN_DOSE_MM = 2.0    # gross; used when the sector has no min_irrigation_mm
_NORMAL_BAND_FLOOR = 0.4      # presentation constant, not agronomy — tune with feedback
_MIN_LEARNABLE_EVENT_MM = 0.5


@dataclass(frozen=True)
class DosePresentation:
    dose_band: str
    dose_source: str
    habitual_factor: float | None = None        # needed net mm ÷ typical event net mm
    estimated_runtime_min: float | None = None  # factor × typical duration (estimate)
    fingerprint_n_events: int | None = None
    typical_event_net_mm: float | None = None


def classify_dose_band(
    depletion_mm: float,
    effective_threshold_mm: float,
    requested_gross_mm: float,
    min_irrigation_mm: float | None,
    rain_skip: bool,
) -> str:
    if rain_skip:
        return DOSE_BAND_PODE_SALTAR
    r = depletion_mm / effective_threshold_mm if effective_threshold_mm > 0 else 0.0
    if r >= 1.0:
        return DOSE_BAND_REFORCADA
    if requested_gross_mm < (min_irrigation_mm or _DEFAULT_MIN_DOSE_MM):
        return DOSE_BAND_PODE_SALTAR
    if r >= _NORMAL_BAND_FLOOR:
        return DOSE_BAND_NORMAL
    return DOSE_BAND_CURTA


def resolve_dose_presentation(
    dose: DosageResult | None,
    dose_band: str,
    fingerprint,          # IrrigationFingerprint row or None (duck-typed, keeps this pure)
    now: datetime,
) -> DosePresentation:
    if dose is None:
        return DosePresentation(dose_band=dose_band, dose_source=DOSE_SOURCE_MM_ONLY)
    if dose.runtime_min is not None:
        return DosePresentation(dose_band=dose_band, dose_source=DOSE_SOURCE_CONFIGURED)
    if (
        fingerprint is not None
        and not is_fingerprint_stale(fingerprint.computed_at, now)
        and fingerprint.typical_event_net_mm >= _MIN_LEARNABLE_EVENT_MM
    ):
        factor = round(dose.irrigation_net_mm / fingerprint.typical_event_net_mm, 2)
        estimated = (
            round(factor * fingerprint.typical_event_duration_min, 0)
            if fingerprint.typical_event_duration_min
            else None
        )
        return DosePresentation(
            dose_band=dose_band,
            dose_source=DOSE_SOURCE_PROBE_LEARNED,
            habitual_factor=factor,
            estimated_runtime_min=estimated,
            fingerprint_n_events=fingerprint.n_events,
            typical_event_net_mm=fingerprint.typical_event_net_mm,
        )
    return DosePresentation(dose_band=dose_band, dose_source=DOSE_SOURCE_MM_ONLY)
