"""Unit tests for irrigation dosage computation."""

import pytest
from unittest.mock import MagicMock

from app.engine.dosage import compute_dosage
from app.engine.water_balance import WaterBalanceResult


def make_wb(depletion_mm: float = 20.0) -> WaterBalanceResult:
    return WaterBalanceResult(
        swc_current=0.20,
        depletion_mm=depletion_mm,
        taw_mm=84.0,
        raw_mm=50.4,
        fc=0.28,
        pwp=0.14,
        root_depth_m=0.60,
    )


def make_ctx(
    app_rate=2.5,
    efficiency=0.90,
    emitter_flow=None,
    emitter_spacing=None,
    row_spacing=None,
    min_irrig=None,
    max_irrig=None,
    max_runtime=None,
):
    ctx = MagicMock()
    ctx.application_rate_mm_h = app_rate
    ctx.irrigation_efficiency = efficiency
    ctx.emitter_flow_lph = emitter_flow
    ctx.emitter_spacing_m = emitter_spacing
    ctx.row_spacing_m = row_spacing
    ctx.min_irrigation_mm = min_irrig
    ctx.max_irrigation_mm = max_irrig
    ctx.max_runtime_hours = max_runtime
    return ctx


class TestBasicDosage:
    def test_gross_is_net_over_efficiency(self):
        wb = make_wb(20.0)
        ctx = make_ctx(app_rate=2.5, efficiency=0.90)
        result = compute_dosage(wb, ctx)
        assert result.irrigation_net_mm == pytest.approx(20.0, rel=1e-2)
        assert result.irrigation_gross_mm == pytest.approx(20.0 / 0.90, rel=1e-2)

    def test_runtime_computed_from_app_rate(self):
        wb = make_wb(20.0)
        ctx = make_ctx(app_rate=2.5, efficiency=1.0)  # efficiency=1 → gross=net=20mm
        result = compute_dosage(wb, ctx)
        # 20mm / 2.5mm/h = 8h = 480min
        assert result.runtime_min == pytest.approx(480.0, rel=1e-2)

    def test_runtime_none_when_no_system(self):
        """No application rate AND no emitter config → runtime_min is None."""
        wb = make_wb(20.0)
        ctx = make_ctx(app_rate=None, emitter_flow=None)
        result = compute_dosage(wb, ctx)
        assert result.runtime_min is None


class TestEmitterFallback:
    def test_computes_rate_from_emitter_config(self):
        """When app_rate is None but emitter config provided → computes rate."""
        wb = make_wb(10.0)
        ctx = make_ctx(
            app_rate=None,
            emitter_flow=2.0,     # L/h per emitter
            emitter_spacing=0.5,  # m
            row_spacing=2.0,      # m
        )
        result = compute_dosage(wb, ctx)
        # drip_application_rate = 2.0 / (0.5 × 2.0) = 2.0 mm/h
        assert result.runtime_min is not None
        assert result.application_rate_mm_h == pytest.approx(2.0, rel=1e-2)


class TestCapping:
    def test_min_irrigation_cap(self):
        """Depletion below min → capped at min."""
        wb = make_wb(5.0)
        ctx = make_ctx(app_rate=2.5, efficiency=1.0, min_irrig=10.0)
        result = compute_dosage(wb, ctx)
        assert result.irrigation_gross_mm >= 10.0
        assert result.capped is True

    def test_max_irrigation_cap(self):
        """Depletion above max → capped at max."""
        wb = make_wb(50.0)
        ctx = make_ctx(app_rate=2.5, efficiency=1.0, max_irrig=30.0)
        result = compute_dosage(wb, ctx)
        assert result.irrigation_gross_mm <= 30.0
        assert result.capped is True

    def test_max_runtime_cap(self):
        """Runtime exceeds max_runtime_hours → capped."""
        wb = make_wb(40.0)  # 40mm / 1.0mm/h = 40h
        ctx = make_ctx(app_rate=1.0, efficiency=1.0, max_runtime=6.0)
        result = compute_dosage(wb, ctx)
        assert result.runtime_min == pytest.approx(360.0, rel=1e-2)
        assert result.capped is True

    def test_no_cap_within_range(self):
        wb = make_wb(20.0)
        ctx = make_ctx(app_rate=2.5, efficiency=0.9, min_irrig=5.0, max_irrig=40.0)
        result = compute_dosage(wb, ctx)
        assert result.capped is False
