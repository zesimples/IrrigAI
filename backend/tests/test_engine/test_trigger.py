"""Unit tests for irrigation trigger logic."""

import pytest
from unittest.mock import MagicMock

from app.engine.trigger import should_irrigate
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


def make_ctx(strategy="standard", deficit_factor=1.0, rdi_eligible=False, rdi_factor=None):
    ctx = MagicMock()
    ctx.irrigation_strategy = strategy
    ctx.deficit_factor = deficit_factor
    ctx.rdi_eligible = rdi_eligible
    ctx.rdi_factor = rdi_factor
    return ctx


class TestRainSkip:
    def test_skips_when_rain_exceeds_15mm(self):
        wb = make_wb(dr=30.0, raw=20.0)
        do_it, reason = should_irrigate(wb, make_ctx(), forecast_rain_next_48h=20.0)
        assert do_it is False
        assert "rain skip" in reason.lower() or "rain" in reason.lower()

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
        assert "depletion" in reason.lower() or "threshold" in reason.lower()

    def test_skips_when_dr_lt_raw(self):
        wb = make_wb(dr=10.0, raw=18.0)
        do_it, reason = should_irrigate(wb, make_ctx())
        assert do_it is False
        assert "no irrigation" in reason.lower() or "margin" in reason.lower()

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
