"""Unit tests for irrigation trigger logic."""

import pytest
from unittest.mock import MagicMock

from app.engine.trigger import effective_trigger_threshold, rain_skip_applies, should_irrigate
from app.engine.water_balance import WaterBalanceResult


def make_wb(dr: float, raw: float, taw: float = 50.0) -> WaterBalanceResult:
    return WaterBalanceResult(
        swc_current=0.20,
        depletion_mm=dr,
        taw_mm=taw,
        raw_mm=raw,
        fc=0.28,
        pwp=0.14,
        root_depth_m=0.60,
    )


def make_ctx(
    strategy="standard",
    deficit_factor=1.0,
    rdi_eligible=False,
    rdi_factor=None,
    rainfall_effectiveness=0.20,
):
    ctx = MagicMock()
    ctx.irrigation_strategy = strategy
    ctx.deficit_factor = deficit_factor
    ctx.rdi_eligible = rdi_eligible
    ctx.rdi_factor = rdi_factor
    ctx.rainfall_effectiveness = rainfall_effectiveness
    return ctx


class TestRainSkip:
    def test_skips_when_rain_exceeds_15mm(self):
        wb = make_wb(dr=30.0, raw=20.0)
        do_it, reason = should_irrigate(wb, make_ctx(), forecast_rain_next_48h=20.0)
        assert do_it is False
        assert "chuva" in reason.lower()

    def test_does_not_skip_below_threshold(self):
        """14.9mm rain → does NOT trigger rain skip."""
        wb = make_wb(dr=30.0, raw=20.0)
        do_it, _ = should_irrigate(wb, make_ctx(), forecast_rain_next_48h=14.9)
        assert do_it is True

    def test_exactly_15mm_triggers_skip(self):
        wb = make_wb(dr=30.0, raw=20.0)
        do_it, _ = should_irrigate(wb, make_ctx(), forecast_rain_next_48h=15.0)
        assert do_it is False


class TestStandardTrigger:
    def test_irrigates_when_dr_gte_raw(self):
        wb = make_wb(dr=20.0, raw=18.0)
        do_it, reason = should_irrigate(wb, make_ctx())
        assert do_it is True
        assert "regar" in reason.lower()

    def test_skips_when_dr_lt_raw(self):
        wb = make_wb(dr=10.0, raw=18.0)
        do_it, reason = should_irrigate(wb, make_ctx())
        assert do_it is False
        assert "reserva" in reason.lower()

    def test_exactly_at_raw_triggers(self):
        wb = make_wb(dr=18.0, raw=18.0)
        do_it, _ = should_irrigate(wb, make_ctx())
        assert do_it is True


class TestRdiStrategy:
    def test_rdi_raises_threshold(self):
        """RDI factor >1 means stress is allowed → threshold higher, harder to trigger."""
        wb = make_wb(dr=20.0, raw=18.0)
        ctx = make_ctx(strategy="rdi", rdi_eligible=True, rdi_factor=1.5)
        # threshold = 18 × 1.5 = 27 → dr=20 < 27 → skip
        do_it, _ = should_irrigate(wb, ctx)
        assert do_it is False

    def test_rdi_triggers_when_above_adjusted_threshold(self):
        wb = make_wb(dr=30.0, raw=18.0)
        ctx = make_ctx(strategy="rdi", rdi_eligible=True, rdi_factor=1.5)
        # threshold = 18 × 1.5 = 27 → dr=30 ≥ 27 → irrigate
        do_it, _ = should_irrigate(wb, ctx)
        assert do_it is True

    def test_rdi_ignored_when_not_eligible(self):
        """RDI strategy but rdi_eligible=False → uses standard RAW threshold."""
        wb = make_wb(dr=20.0, raw=18.0)
        ctx = make_ctx(strategy="rdi", rdi_eligible=False, rdi_factor=1.5)
        do_it, _ = should_irrigate(wb, ctx)
        assert do_it is True  # dr=20 ≥ raw=18 → irrigate


class TestDeficitFactor:
    def test_deficit_factor_reduces_threshold(self):
        """deficit_factor=0.5 → threshold = 18 × 0.5 = 9 → dr=10 ≥ 9 → irrigate."""
        wb = make_wb(dr=10.0, raw=18.0)
        ctx = make_ctx(deficit_factor=0.5)
        do_it, _ = should_irrigate(wb, ctx)
        assert do_it is True

    def test_deficit_factor_1_is_standard(self):
        wb = make_wb(dr=10.0, raw=18.0)
        ctx = make_ctx(deficit_factor=1.0)
        do_it, _ = should_irrigate(wb, ctx)
        assert do_it is False


class TestEffectiveTriggerThreshold:
    def test_plain_raw(self):
        ctx = make_ctx()  # default strategy, deficit_factor=1.0
        wb = make_wb(dr=0.0, raw=30.0)
        assert effective_trigger_threshold(wb, ctx) == 30.0

    def test_deficit_factor_scales(self):
        ctx = make_ctx(deficit_factor=0.8)
        wb = make_wb(dr=0.0, raw=30.0)
        assert effective_trigger_threshold(wb, ctx) == 24.0

    def test_rdi_scales_when_eligible(self):
        ctx = make_ctx(strategy="rdi", rdi_eligible=True, rdi_factor=0.5)
        wb = make_wb(dr=0.0, raw=30.0)
        assert effective_trigger_threshold(wb, ctx) == 15.0


class TestRainSkipApplies:
    def test_true_when_effective_rain_covers_full_deficit(self):
        """Fully depleted sector (dr >= threshold) + enough rain still counts as
        covering the remaining deficit (remaining_to_trigger clamped to 0)."""
        wb = make_wb(dr=30.0, raw=20.0)
        ctx = make_ctx(rainfall_effectiveness=1.0)
        assert rain_skip_applies(wb, ctx, forecast_rain_next_48h=5.0) is True

    def test_false_when_drizzle_below_min_effective_rain(self):
        """Below the 3mm effective-rain floor even though it 'covers' a tiny deficit."""
        wb = make_wb(dr=17.5, raw=18.0)
        ctx = make_ctx(rainfall_effectiveness=0.5)
        # remaining_to_trigger = 0.5mm; effective_rain = 4 * 0.5 = 2.0mm >= remaining
        # but effective_rain (2.0) < _MIN_EFFECTIVE_RAIN_TO_SKIP (3.0) → False
        assert rain_skip_applies(wb, ctx, forecast_rain_next_48h=4.0) is False

    def test_false_when_no_rain_forecast(self):
        wb = make_wb(dr=30.0, raw=20.0)
        ctx = make_ctx()
        assert rain_skip_applies(wb, ctx, forecast_rain_next_48h=0.0) is False

    def test_false_when_rain_insufficient_for_remaining_deficit(self):
        wb = make_wb(dr=5.0, raw=20.0)
        ctx = make_ctx(rainfall_effectiveness=0.2)
        # remaining_to_trigger = 15mm; effective_rain = 10 * 0.2 = 2mm < 15mm
        assert rain_skip_applies(wb, ctx, forecast_rain_next_48h=10.0) is False

    def test_matches_should_irrigate_skip_decision(self):
        """Consistency check: when rain_skip_applies is True, should_irrigate skips
        for the rain reason."""
        wb = make_wb(dr=30.0, raw=20.0)
        ctx = make_ctx()
        assert rain_skip_applies(wb, ctx, forecast_rain_next_48h=20.0) is True
        do_it, reason = should_irrigate(wb, ctx, forecast_rain_next_48h=20.0)
        assert do_it is False
        assert "chuva" in reason.lower()
