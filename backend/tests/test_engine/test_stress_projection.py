"""Stress projection — the already-in-stress case must report 'now', not a
nonsensical negative hours-to-stress (the '~-425h' prod bug)."""
from datetime import date

from app.engine.stress_projection import StressProjector

_TODAY = date(2026, 7, 8)


def _project(current_depletion_mm, taw_mm=111.0, mad=0.65):
    return StressProjector().project(
        current_depletion_mm=current_depletion_mm,
        taw_mm=taw_mm,
        mad=mad,
        forecast_et0=[7.0, 7.0, 7.0],
        kc=0.5,
        forecast_rain=[(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)],
        rainfall_effectiveness=0.8,
        sector_id="s1",
        today=_TODAY,
    )


def test_already_past_threshold_reports_now_not_negative():
    # depletion 90.7 of TAW 111 → 82%, well past the 65% MAD threshold (72.15mm)
    proj = _project(90.7)
    assert proj.hours_to_stress == 0.0
    assert proj.urgency == "high"
    assert "já presente" in proj.message_pt
    assert "~-" not in proj.message_pt  # the '~-425h' bug signature must be gone


def test_hours_to_stress_never_negative():
    for dep in (72.15, 80.0, 90.7, 111.0):
        proj = _project(dep)
        assert proj.hours_to_stress is None or proj.hours_to_stress >= 0.0


def test_build_messages_rounds_sub_hour_to_present():
    from app.engine.stress_projection import _build_messages

    pt, _ = _build_messages("high", 0.4, _TODAY)
    assert "já presente" in pt
    assert "~0h" not in pt


def test_not_yet_stressed_still_projects_forward():
    # Low depletion → stress is in the future (positive hours) or None, message not "já presente"
    proj = _project(10.0)
    assert proj.hours_to_stress is None or proj.hours_to_stress > 0.0
    assert "já presente" not in proj.message_pt
