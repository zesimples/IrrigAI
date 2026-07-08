"""Unit tests for weighted_rootzone_series — the pure rootzone-SWC time-series helper.

Reuses probe_interpreter._depth_interval_weights (same weighting as the engine's
_compute_rootzone) so the probe chart's rootzone-weighted line can never diverge
from the recommendation. Kept DB-free and pure: series_by_depth is a plain dict of
{depth_cm: [(timestamp, vwc), ...]}.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.engine.probe_interpreter import weighted_rootzone_series

T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _ts(hours: int) -> datetime:
    return T0 + timedelta(hours=hours)


def test_empty_series_returns_empty():
    assert weighted_rootzone_series({}, root_depth_cm=60) == []


def test_no_in_zone_depths_falls_back_to_all_depths():
    # No sensor within the root zone → mirror _compute_rootzone's all-depths
    # fallback (weighted against root_depth_cm) rather than returning nothing, so
    # the chart line can't vanish while the engine still produces an SWC.
    from app.engine.probe_interpreter import _depth_interval_weights

    series_by_depth = {80: [(_ts(0), 0.30)], 90: [(_ts(0), 0.50)]}
    weights = _depth_interval_weights([80, 90], 60)
    expected = round((weights[0] * 0.30 + weights[1] * 0.50) / sum(weights), 4)
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=60)
    assert [v for _, v in result] == [expected]


def test_single_in_zone_depth_matches_its_own_value():
    series_by_depth = {30: [(_ts(0), 0.20), (_ts(1), 0.22)]}
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=60)
    assert [v for _, v in result] == [0.20, 0.22]


def test_two_depths_hand_weighted_average():
    # depths 40cm, 60cm, root_depth 80cm. Per _depth_interval_weights: 40cm covers
    # 0-50cm (50cm thick); 60cm extends half a step (20cm) past itself → 50-70cm
    # (20cm thick, capped by root_depth 80cm which isn't reached here).
    from app.engine.probe_interpreter import _depth_interval_weights

    weights = _depth_interval_weights([40, 60], 80)
    series_by_depth = {
        40: [(_ts(0), 0.30)],
        60: [(_ts(0), 0.10)],
    }
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=80)
    assert len(result) == 1
    ts, vwc = result[0]
    assert ts == _ts(0)
    expected = (weights[0] * 0.30 + weights[1] * 0.10) / sum(weights)
    assert vwc == pytest.approx(round(expected, 4))


def test_split_moisture_profile_matches_prod_example():
    # Real prod-shaped example (Innoliva "Turno 5 (S20)"): shallow depths dry,
    # deep sensors wet, root_depth 80cm — the rootzone average must stay dry
    # even though a naive sum/average across all depths would look comfortable.
    depths_cm = [10, 20, 30, 40, 50, 60, 70, 80, 90]
    dry = 0.07
    wet_80 = 0.324
    wet_90 = 0.549
    series_by_depth = {
        d: [(_ts(0), dry if d <= 70 else (wet_80 if d == 80 else wet_90))]
        for d in depths_cm
    }
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=80)
    assert len(result) == 1
    _, vwc = result[0]
    # 90cm sensor is out of the 80cm root zone and must not pull the average up.
    assert vwc < 0.15


def test_output_timestamps_are_subset_of_input_and_sorted():
    # Alignment guarantee: the endpoint builds this from the SAME (already-downsampled)
    # per-depth points sent to the chart, so the rootzone line's timestamps are always
    # a subset of the depth lines' — it can't drift out of phase under any interval.
    series_by_depth = {
        30: [(_ts(0), 0.20), (_ts(2), 0.22), (_ts(6), 0.19)],
        60: [(_ts(0), 0.18), (_ts(2), 0.20)],  # staggered: no reading at t=6
    }
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=80)
    input_ts = {t for pts in series_by_depth.values() for t, _ in pts}
    out_ts = [t for t, _ in result]
    assert all(t in input_ts for t in out_ts)
    assert out_ts == sorted(out_ts)


def test_skips_timestamps_with_no_in_zone_reading():
    # 40cm has a reading only at t=0; 90cm (out of zone) has one at t=1.
    series_by_depth = {
        40: [(_ts(0), 0.25)],
        90: [(_ts(1), 0.40)],
    }
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=60)
    assert len(result) == 1
    assert result[0][0] == _ts(0)


def test_renormalizes_over_present_depths_at_each_timestamp():
    # 40cm present at both timestamps; 60cm only present at t=0.
    # At t=1, only 40cm is present, so the average should equal 40cm's own value,
    # not be diluted by a "missing" 60cm.
    series_by_depth = {
        40: [(_ts(0), 0.30), (_ts(1), 0.10)],
        60: [(_ts(0), 0.10)],
    }
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=80)
    result_by_ts = dict(result)
    assert result_by_ts[_ts(1)] == pytest.approx(0.10)


def test_rounds_to_4dp():
    series_by_depth = {
        40: [(_ts(0), 0.123456)],
        60: [(_ts(0), 0.234567)],
    }
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=80)
    _, vwc = result[0]
    assert vwc == round(vwc, 4)


def test_results_sorted_by_timestamp():
    series_by_depth = {
        30: [(_ts(2), 0.20), (_ts(0), 0.25), (_ts(1), 0.22)],
    }
    result = weighted_rootzone_series(series_by_depth, root_depth_cm=60)
    assert [ts for ts, _ in result] == [_ts(0), _ts(1), _ts(2)]
