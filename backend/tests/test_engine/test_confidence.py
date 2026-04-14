"""Unit tests for confidence scoring."""

import pytest
from unittest.mock import MagicMock


def make_ctx(
    app_rate=2.5,
    emitter_flow=None,
    phenological_stage="mid_season",
    soil_texture="clay_loam",
    field_capacity=0.28,
    irrigation_strategy="standard",
    defaults_used=None,
    missing_config=None,
):
    ctx = MagicMock()
    ctx.application_rate_mm_h = app_rate
    ctx.emitter_flow_lph = emitter_flow
    ctx.phenological_stage = phenological_stage
    ctx.soil_texture = soil_texture
    ctx.field_capacity = field_capacity
    ctx.irrigation_strategy = irrigation_strategy
    ctx.defaults_used = defaults_used or []
    ctx.missing_config = missing_config or []
    return ctx


def make_probes(has_data=True, hours_since=1.0, all_depths_ok=True, is_calibrated=True, anomalies=None):
    rz = MagicMock()
    rz.has_data = has_data
    rz.hours_since_any_reading = hours_since
    rz.all_depths_ok = all_depths_ok

    probes = MagicMock()
    probes.rootzone = rz
    probes.is_calibrated = is_calibrated
    probes.anomalies_detected = anomalies or []
    return probes


def make_weather(hours_since_obs=2.0):
    w = MagicMock()
    w.hours_since_observation = hours_since_obs
    return w


from app.engine.confidence import score


class TestPerfectData:
    def test_all_configured_gives_high_confidence(self):
        """Full configuration, fresh data, calibrated → high confidence."""
        ctx = make_ctx()
        probes = make_probes()
        weather = make_weather()
        result = score(ctx, probes, weather)
        assert result.level == "high"
        assert result.score >= 0.75

    def test_score_is_between_zero_and_one(self):
        ctx = make_ctx()
        probes = make_probes()
        weather = make_weather()
        result = score(ctx, probes, weather)
        assert 0.0 <= result.score <= 1.0


class TestPenalties:
    def test_no_probe_data_penalises(self):
        ctx = make_ctx()
        probes = make_probes(has_data=False)
        weather = make_weather()
        with_probes = score(make_ctx(), make_probes(), weather)
        without_probes = score(ctx, probes, weather)
        assert without_probes.score < with_probes.score

    def test_stale_probe_penalises(self):
        fresh = score(make_ctx(), make_probes(hours_since=1.0), make_weather())
        stale = score(make_ctx(), make_probes(hours_since=10.0), make_weather())
        assert stale.score < fresh.score

    def test_uncalibrated_probes_penalises(self):
        cal = score(make_ctx(), make_probes(is_calibrated=True), make_weather())
        uncal = score(make_ctx(), make_probes(is_calibrated=False), make_weather())
        assert uncal.score < cal.score

    def test_stale_weather_penalises(self):
        fresh = score(make_ctx(), make_probes(), make_weather(hours_since_obs=2.0))
        stale = score(make_ctx(), make_probes(), make_weather(hours_since_obs=30.0))
        assert stale.score < fresh.score

    def test_no_irrigation_system_penalises(self):
        with_sys = score(make_ctx(app_rate=2.5), make_probes(), make_weather())
        without = score(make_ctx(app_rate=None, emitter_flow=None), make_probes(), make_weather())
        assert without.score < with_sys.score

    def test_missing_phenological_stage_penalises(self):
        with_stage = score(make_ctx(phenological_stage="mid_season"), make_probes(), make_weather())
        without = score(make_ctx(phenological_stage=None), make_probes(), make_weather())
        assert without.score < with_stage.score

    def test_anomalies_penalise(self):
        clean = score(make_ctx(), make_probes(), make_weather())
        anomaly = score(make_ctx(), make_probes(), make_weather(), anomalies=["flatline detected"])
        assert anomaly.score < clean.score

    def test_defaults_used_penalises(self):
        no_defaults = score(make_ctx(defaults_used=[]), make_probes(), make_weather())
        with_defaults = score(make_ctx(defaults_used=["Kc", "MAD", "FC"]), make_probes(), make_weather())
        assert with_defaults.score < no_defaults.score

    def test_missing_config_penalises(self):
        complete = score(make_ctx(missing_config=[]), make_probes(), make_weather())
        incomplete = score(make_ctx(missing_config=["irrigation system", "soil"]), make_probes(), make_weather())
        assert incomplete.score < complete.score


class TestMinimumScore:
    def test_score_never_below_minimum(self):
        """Worst case: everything missing → floor at 0.10."""
        ctx = make_ctx(
            app_rate=None, emitter_flow=None,
            phenological_stage=None,
            soil_texture=None, field_capacity=None,
            defaults_used=["a", "b", "c"],
            missing_config=["x", "y", "z"],
        )
        probes = make_probes(has_data=False, is_calibrated=False)
        weather = make_weather(hours_since_obs=48.0)
        result = score(ctx, probes, weather, anomalies=["anomaly1"])
        assert result.score >= 0.10


class TestConfidenceLevels:
    def test_high_level_at_0_75(self):
        ctx = make_ctx()
        probes = make_probes()
        weather = make_weather()
        result = score(ctx, probes, weather)
        if result.score >= 0.75:
            assert result.level == "high"

    def test_medium_level_range(self):
        # Introduce a few penalties to land in medium range
        ctx = make_ctx(defaults_used=["Kc", "MAD"], missing_config=["irrigation system"])
        result = score(ctx, make_probes(), make_weather())
        if 0.50 <= result.score < 0.75:
            assert result.level == "medium"

    def test_low_level_below_0_50(self):
        ctx = make_ctx(
            app_rate=None, emitter_flow=None,
            phenological_stage=None,
            defaults_used=["a", "b", "c"],
            missing_config=["x", "y"],
        )
        probes = make_probes(has_data=False)
        result = score(ctx, probes, make_weather(), anomalies=["x"])
        if result.score < 0.50:
            assert result.level == "low"


class TestPenaltyBreakdown:
    def test_penalties_list_populated(self):
        ctx = make_ctx(phenological_stage=None)
        result = score(ctx, make_probes(), make_weather())
        assert len(result.penalties) > 0
        # Each penalty is (reason_str, float)
        for reason, amount in result.penalties:
            assert isinstance(reason, str)
            assert isinstance(amount, float)

    def test_warnings_list_populated(self):
        ctx = make_ctx(phenological_stage=None)
        result = score(ctx, make_probes(), make_weather())
        assert len(result.warnings) > 0
