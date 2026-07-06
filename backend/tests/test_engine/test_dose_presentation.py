"""Band classifier + dose-source precedence (dose-do-dia)."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.engine.dosage import DosageResult
from app.engine.dose_presentation import (
    DOSE_BAND_CURTA,
    DOSE_BAND_NORMAL,
    DOSE_BAND_PODE_SALTAR,
    DOSE_BAND_REFORCADA,
    DOSE_SOURCE_CONFIGURED,
    DOSE_SOURCE_MM_ONLY,
    DOSE_SOURCE_PROBE_LEARNED,
    classify_dose_band,
    resolve_dose_presentation,
)

NOW = datetime(2026, 7, 6, 6, 0, tzinfo=UTC)


@dataclass
class FakeFingerprint:
    typical_event_net_mm: float = 4.0
    typical_event_duration_min: float | None = 120.0
    n_events: int = 5
    computed_at: datetime = NOW - timedelta(days=3)


def _dose(net=5.0, gross=6.2, runtime=None, requested=6.2):
    return DosageResult(
        irrigation_net_mm=net, irrigation_gross_mm=gross, runtime_min=runtime,
        application_rate_mm_h=None, requested_gross_mm=requested,
    )


class TestClassifyDoseBand:
    def test_rain_skip_wins(self):
        assert classify_dose_band(40, 30, 10, None, rain_skip=True) == DOSE_BAND_PODE_SALTAR

    def test_reforcada_at_threshold(self):
        assert classify_dose_band(30, 30, 10, None, rain_skip=False) == DOSE_BAND_REFORCADA

    def test_normal_band(self):
        assert classify_dose_band(15, 30, 10, None, rain_skip=False) == DOSE_BAND_NORMAL

    def test_curta_band(self):
        assert classify_dose_band(9, 30, 10, None, rain_skip=False) == DOSE_BAND_CURTA

    def test_negligible_dose_pode_saltar_default_2mm(self):
        assert classify_dose_band(9, 30, 1.5, None, rain_skip=False) == DOSE_BAND_PODE_SALTAR

    def test_negligible_dose_respects_min_irrigation(self):
        assert classify_dose_band(9, 30, 4.0, 5.0, rain_skip=False) == DOSE_BAND_PODE_SALTAR

    def test_zero_threshold_is_curta_not_crash(self):
        assert classify_dose_band(5, 0.0, 10, None, rain_skip=False) == DOSE_BAND_CURTA


class TestResolveDosePresentation:
    def test_configured_wins(self):
        p = resolve_dose_presentation(_dose(runtime=90.0), DOSE_BAND_NORMAL, FakeFingerprint(), NOW)
        assert p.dose_source == DOSE_SOURCE_CONFIGURED
        assert p.habitual_factor is None

    def test_probe_learned_factor_and_estimate(self):
        p = resolve_dose_presentation(_dose(net=5.0), DOSE_BAND_NORMAL, FakeFingerprint(), NOW)
        assert p.dose_source == DOSE_SOURCE_PROBE_LEARNED
        assert p.habitual_factor == 1.25          # 5.0 / 4.0
        assert p.estimated_runtime_min == 150.0   # 1.25 × 120
        assert p.fingerprint_n_events == 5

    def test_probe_learned_without_duration(self):
        fp = FakeFingerprint(typical_event_duration_min=None)
        p = resolve_dose_presentation(_dose(net=5.0), DOSE_BAND_NORMAL, fp, NOW)
        assert p.dose_source == DOSE_SOURCE_PROBE_LEARNED
        assert p.estimated_runtime_min is None

    def test_stale_fingerprint_falls_to_mm_only(self):
        fp = FakeFingerprint(computed_at=NOW - timedelta(days=25))
        p = resolve_dose_presentation(_dose(), DOSE_BAND_NORMAL, fp, NOW)
        assert p.dose_source == DOSE_SOURCE_MM_ONLY

    def test_near_zero_typical_falls_to_mm_only(self):
        fp = FakeFingerprint(typical_event_net_mm=0.2)
        p = resolve_dose_presentation(_dose(), DOSE_BAND_NORMAL, fp, NOW)
        assert p.dose_source == DOSE_SOURCE_MM_ONLY

    def test_no_fingerprint_mm_only(self):
        p = resolve_dose_presentation(_dose(), DOSE_BAND_NORMAL, None, NOW)
        assert p.dose_source == DOSE_SOURCE_MM_ONLY

    def test_no_dose_mm_only(self):
        p = resolve_dose_presentation(None, DOSE_BAND_PODE_SALTAR, FakeFingerprint(), NOW)
        assert p.dose_source == DOSE_SOURCE_MM_ONLY
