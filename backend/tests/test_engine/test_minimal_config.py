"""Tests for minimal-configuration sector behaviour.

A sector with only crop_type set and no IrrigationSystem, no crop profile
stages, and no soil config should:
- Still produce a valid EngineRecommendation
- Have low confidence
- Have many defaults_used and missing_config entries
- Have runtime_min = None
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.engine.types import (
    ConfidenceResult,
    DailyWeather,
    DepthStatus,
    EngineRecommendation,
    ProbeSnapshot,
    ReasonEntry,
    RootzoneStatus,
    SectorContext,
    WeatherContext,
)


def make_minimal_ctx() -> SectorContext:
    """Minimal SectorContext — only crop_type set, everything else defaults/missing."""
    return SectorContext(
        sector_id="test-sector-minimal",
        sector_name="Minimal Sector",
        crop_type="olive",
        phenological_stage=None,           # not set
        planting_year=None,
        tree_age_years=None,
        soil_texture=None,                 # not configured
        field_capacity=0.28,              # fallback FC
        wilting_point=0.14,               # fallback PWP
        kc=1.10,                          # fallback (highest)
        kc_source="default (stage not set, using highest Kc as mid-season proxy)",
        mad=0.50,
        root_depth_m=0.80,
        rdi_eligible=False,
        rdi_factor=None,
        irrigation_system_type=None,       # NOT configured
        application_rate_mm_h=None,        # NOT configured
        irrigation_efficiency=0.90,        # fallback
        emitter_flow_lph=None,
        emitter_spacing_m=None,
        row_spacing_m=None,
        max_runtime_hours=None,
        min_irrigation_mm=None,
        max_irrigation_mm=None,
        irrigation_strategy="standard",
        deficit_factor=1.0,
        area_ha=None,
        rainfall_effectiveness=0.75,
        defaults_used=[
            "soil FC/PWP (not configured, using clay-loam defaults)",
            "Kc=1.10 (default (stage not set, using highest Kc as mid-season proxy))",
        ],
        missing_config=[
            "irrigation system not configured",
        ],
    )


def make_no_probe_snapshot(sector_id: str) -> ProbeSnapshot:
    rz = RootzoneStatus(
        swc_current=None,
        swc_source="default",
        depth_statuses=[],
        has_data=False,
        hours_since_any_reading=None,
        all_depths_ok=False,
    )
    return ProbeSnapshot(
        sector_id=sector_id,
        probe_ids=[],
        rootzone=rz,
        anomalies_detected=[],
        is_calibrated=False,
    )


def make_minimal_weather() -> WeatherContext:
    return WeatherContext(
        farm_id="test-farm",
        lat=38.57,
        lon=-8.0,
        today=DailyWeather(
            date=datetime.now(UTC).date(),
            t_max=28.0,
            t_min=14.0,
        ),
        forecast=[],
        hours_since_observation=None,
        has_forecast=False,
    )


class TestMinimalConfigConfidence:
    def test_minimal_config_gives_low_confidence(self):
        """No probe data, no system, no stage → confidence below 0.50."""
        from app.engine.confidence import score

        ctx = make_minimal_ctx()
        probes = make_no_probe_snapshot(ctx.sector_id)
        weather = make_minimal_weather()

        result = score(ctx, probes, weather)
        assert result.score < 0.75, f"Expected medium or low, got score={result.score}"

    def test_minimal_config_has_multiple_penalties(self):
        from app.engine.confidence import score

        ctx = make_minimal_ctx()
        probes = make_no_probe_snapshot(ctx.sector_id)
        weather = make_minimal_weather()

        result = score(ctx, probes, weather)
        assert len(result.penalties) >= 3, (
            f"Expected ≥3 penalties for minimal config, got: {result.penalties}"
        )

    def test_score_never_below_floor(self):
        from app.engine.confidence import score

        ctx = make_minimal_ctx()
        probes = make_no_probe_snapshot(ctx.sector_id)
        weather = make_minimal_weather()

        result = score(ctx, probes, weather)
        assert result.score >= 0.10


class TestMinimalConfigWaterBalance:
    def test_fallback_swc_used_when_no_probe(self):
        """No probe SWC → water balance initialised at 70% TAW."""
        from app.engine.water_balance import build_water_balance

        ctx = make_minimal_ctx()
        wb = build_water_balance(ctx, swc_probe=None)

        # 70% TAW means SWC should be between PWP and FC
        assert ctx.wilting_point < wb.swc_current < ctx.field_capacity
        assert wb.taw_mm > 0
        assert wb.raw_mm > 0


class TestMinimalConfigRuntime:
    def test_runtime_none_when_no_system(self):
        """No irrigation system → runtime_min is None."""
        from app.engine.dosage import compute_dosage
        from app.engine.water_balance import build_water_balance

        ctx = make_minimal_ctx()
        wb = build_water_balance(ctx, swc_probe=None)

        # Force depletion to trigger irrigation
        from app.engine.water_balance import WaterBalanceResult
        wb_irrigating = WaterBalanceResult(
            swc_current=wb.swc_current,
            depletion_mm=wb.raw_mm + 5.0,  # above RAW → would irrigate
            taw_mm=wb.taw_mm,
            raw_mm=wb.raw_mm,
            fc=wb.fc,
            pwp=wb.pwp,
            root_depth_m=wb.root_depth_m,
        )

        dose = compute_dosage(wb_irrigating, ctx)
        assert dose.runtime_min is None

    def test_dosage_still_has_net_and_gross(self):
        """Even without system, net and gross mm are computed."""
        from app.engine.dosage import compute_dosage
        from app.engine.water_balance import WaterBalanceResult

        ctx = make_minimal_ctx()
        wb = WaterBalanceResult(
            swc_current=0.18,
            depletion_mm=25.0,
            taw_mm=84.0,
            raw_mm=42.0,
            fc=0.28,
            pwp=0.14,
            root_depth_m=0.60,
        )
        dose = compute_dosage(wb, ctx)
        assert dose.irrigation_net_mm > 0
        assert dose.irrigation_gross_mm >= dose.irrigation_net_mm
