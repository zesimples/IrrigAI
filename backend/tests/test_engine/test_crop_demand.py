"""Unit tests for Kc lookup and ETc computation."""

import pytest

from app.engine.crop_demand import compute_etc, get_kc_from_profile

SAMPLE_STAGES = [
    {"key": "initial", "kc": 0.60},
    {"key": "mid_season", "kc": 1.15},
    {"key": "late_season", "kc": 0.80},
]


class TestGetKcFromProfile:
    def test_exact_stage_match(self):
        kc, source = get_kc_from_profile(SAMPLE_STAGES, "mid_season")
        assert kc == 1.15
        assert "mid_season" in source

    def test_exact_stage_match_initial(self):
        kc, source = get_kc_from_profile(SAMPLE_STAGES, "initial")
        assert kc == 0.60

    def test_stage_none_returns_max_kc(self):
        """No stage set → conservative mid-season proxy (highest Kc)."""
        kc, source = get_kc_from_profile(SAMPLE_STAGES, None)
        assert kc == 1.15
        assert "highest" in source or "mid-season" in source

    def test_unknown_stage_returns_max_kc(self):
        """Stage key not in profile → falls back to highest Kc."""
        kc, source = get_kc_from_profile(SAMPLE_STAGES, "harvest")
        assert kc == 1.15
        assert "not found" in source or "default" in source

    def test_empty_stages_returns_default(self):
        kc, source = get_kc_from_profile([], None)
        assert kc == 0.80
        assert "no stages" in source

    def test_single_stage(self):
        stages = [{"key": "growing", "kc": 0.95}]
        kc, source = get_kc_from_profile(stages, "growing")
        assert kc == 0.95

    def test_kc_is_float(self):
        kc, _ = get_kc_from_profile(SAMPLE_STAGES, "initial")
        assert isinstance(kc, float)


class TestComputeEtc:
    def test_basic_multiplication(self):
        etc = compute_etc(et0_mm=5.0, kc=1.15)
        assert etc == pytest.approx(5.75, rel=1e-3)

    def test_with_stress_factor(self):
        etc = compute_etc(et0_mm=5.0, kc=1.0, ks=0.8)
        assert etc == pytest.approx(4.0, rel=1e-3)

    def test_zero_et0(self):
        assert compute_etc(0.0, 1.15) == 0.0

    def test_default_ks_is_one(self):
        """No stress → ETc = ET0 × Kc."""
        assert compute_etc(4.0, 1.0) == pytest.approx(4.0)
