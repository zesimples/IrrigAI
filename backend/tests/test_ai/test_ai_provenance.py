"""A0/A3 regression: a stored analysis must know what it was computed from."""

from __future__ import annotations

import copy

import pytest

from app.services.ai_provenance import compute_context_version, context_input_version


@pytest.mark.parametrize(
    "block,field,value",
    [
        ("engine_decision", "is_accepted", True),
        ("engine_decision", "irrigation_depth_mm", 18),
        ("weather", "forecast", [{"rainfall_mm": 20}]),
        ("crop_state", "field_observations", []),
        ("crop_state", "field_observations", [{"id": "note", "verified": True}]),
        ("calibration", "soil_bounds", {"field_capacity": 0.31}),
    ],
)
def test_actual_context_changes_invalidate_without_timestamp_changes(block, field, value):
    before = {
        "engine_decision": {
            "recommendation_id": "same",
            "is_accepted": False,
            "irrigation_depth_mm": 12,
        },
        "weather": {"forecast": []},
        "crop_state": {"field_observations": [{"id": "note", "verified": False}]},
        "calibration": {"soil_bounds": {"field_capacity": 0.3}},
    }
    after = copy.deepcopy(before)
    after[block][field] = value
    assert context_input_version(before) != context_input_version(after)


def test_request_clock_noise_does_not_invalidate():
    assert context_input_version({"scope": {"observed_at": "now"}}) == context_input_version(
        {"scope": {"observed_at": "later"}}
    )


class TestContextVersion:
    def test_is_stable_for_identical_inputs(self):
        parts = ["rec-1", "2026-09-10T05:00:00+00:00", "2026-09-10T06:00:00+00:00", "-", "-"]
        assert compute_context_version(parts) == compute_context_version(list(parts))

    def test_changes_when_the_recommendation_changes(self):
        base = ["rec-1", "t1", "t2", "-", "-"]
        newer = ["rec-2", "t1", "t2", "-", "-"]
        assert compute_context_version(base) != compute_context_version(newer)

    def test_changes_when_a_new_reading_arrives(self):
        base = ["rec-1", "t1", "2026-09-10T06:00:00+00:00", "-", "-"]
        newer = ["rec-1", "t1", "2026-09-10T07:00:00+00:00", "-", "-"]
        assert compute_context_version(base) != compute_context_version(newer)

    def test_changes_when_a_field_note_is_saved(self):
        base = ["rec-1", "t1", "t2", "-", "-"]
        newer = ["rec-1", "t1", "t2", "-", "2026-09-10T09:00:00+00:00"]
        assert compute_context_version(base) != compute_context_version(newer)

    def test_changes_when_calibration_is_applied(self):
        base = ["rec-1", "t1", "t2", "-", "-"]
        newer = ["rec-1", "t1", "t2", "2026-09-09T04:00:00+00:00", "-"]
        assert compute_context_version(base) != compute_context_version(newer)

    def test_is_short_enough_for_a_cache_key_and_a_column(self):
        version = compute_context_version(["a", "b", "c", "d", "e"])
        assert 8 <= len(version) <= 32
