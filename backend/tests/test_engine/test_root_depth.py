"""Unit tests for resolve_effective_root_depth_m — the shared root-depth helper.

Mirrors the inline logic that used to live in build_sector_context so the probe
chart's rootzone overlay can never diverge from the engine's root depth.
"""

from app.engine.pipeline import _FALLBACK_ROOT_DEPTH, resolve_effective_root_depth_m
from app.models import SectorCropProfile


def _make_scp(**overrides) -> SectorCropProfile:
    defaults = dict(
        sector_id="sector-x",
        crop_type="olive",
        mad=0.5,
        root_depth_mature_m=0.6,
        root_depth_young_m=0.3,
        maturity_age_years=4,
        stages=[],
    )
    defaults.update(overrides)
    return SectorCropProfile(**defaults)


def test_no_scp_returns_fallback():
    assert resolve_effective_root_depth_m(None, tree_age_years=10, current_stage_key=None) == (
        _FALLBACK_ROOT_DEPTH
    )


def test_mature_when_age_over_maturity():
    scp = _make_scp(maturity_age_years=4)
    assert resolve_effective_root_depth_m(scp, tree_age_years=10, current_stage_key=None) == 0.6


def test_mature_when_no_planting_year():
    scp = _make_scp(maturity_age_years=4)
    assert resolve_effective_root_depth_m(scp, tree_age_years=None, current_stage_key=None) == 0.6


def test_mature_when_no_maturity_age_configured():
    scp = _make_scp(maturity_age_years=None)
    # Young age but no maturity_age_years set — can't judge youth, defaults to mature.
    assert resolve_effective_root_depth_m(scp, tree_age_years=1, current_stage_key=None) == 0.6


def test_young_when_age_under_maturity():
    scp = _make_scp(maturity_age_years=4)
    assert resolve_effective_root_depth_m(scp, tree_age_years=2, current_stage_key=None) == 0.3


def test_stage_override_wins():
    scp = _make_scp(
        maturity_age_years=4,
        stages=[{"key": "floracao", "root_depth_m": 0.8}],
    )
    assert (
        resolve_effective_root_depth_m(scp, tree_age_years=10, current_stage_key="floracao") == 0.8
    )


def test_stage_override_wins_over_young():
    scp = _make_scp(
        maturity_age_years=4,
        stages=[{"key": "floracao", "root_depth_m": 0.8}],
    )
    assert (
        resolve_effective_root_depth_m(scp, tree_age_years=2, current_stage_key="floracao") == 0.8
    )


def test_stage_without_root_depth_m_does_not_override():
    scp = _make_scp(
        maturity_age_years=4,
        stages=[{"key": "floracao", "rdi_eligible": True}],
    )
    assert (
        resolve_effective_root_depth_m(scp, tree_age_years=10, current_stage_key="floracao") == 0.6
    )


def test_unknown_stage_key_does_not_override():
    scp = _make_scp(
        maturity_age_years=4,
        stages=[{"key": "floracao", "root_depth_m": 0.8}],
    )
    assert (
        resolve_effective_root_depth_m(scp, tree_age_years=10, current_stage_key="other") == 0.6
    )
