"""The decision-reason list must carry at most ONE "config" entry.

defaults_used (engine-inferred parameters) and missing_config (unconfigured
resources) used to produce two separate CONFIGURAÇÃO topics with verbose,
nested-parenthetical text. They are now merged into a single compact reason.
"""
from types import SimpleNamespace

from app.engine.pipeline import _build_reasons


def _reasons(defaults: list[str], missing: list[str]):
    ctx = SimpleNamespace(defaults_used=defaults, missing_config=missing)
    wb = SimpleNamespace(depletion_mm=10.0, taw_mm=100.0)
    conf = SimpleNamespace(level="medium", score=0.7)
    return _build_reasons(
        ctx, wb, None, None, "trigger", {"rain_next_48h_mm": 0}, conf, None
    )


_SCREENSHOT_DEFAULTS = [
    "FC/refill calibrated from probe envelope (envelope, FC=0.30)",
    "Kc=0.60 (default (stage not set, using highest Kc as mid-season proxy))",
    "GDD-estimated stage (olive_bud_break, 180 GDD)",
]
_SCREENSHOT_MISSING = ["irrigation system not configured"]


def test_single_config_entry_when_both_defaults_and_missing():
    reasons = _reasons(_SCREENSHOT_DEFAULTS, _SCREENSHOT_MISSING)
    config = [r for r in reasons if r.category == "config"]
    assert len(config) == 1


def test_config_message_is_compact():
    reasons = _reasons(_SCREENSHOT_DEFAULTS, _SCREENSHOT_MISSING)
    msg = [r for r in reasons if r.category == "config"][0].message_pt
    # missing item present, in PT
    assert "sistema de rega" in msg
    # estimated parameters present, compact
    assert "CC calibrada pela sonda" in msg
    assert "Kc=0.60" in msg
    assert "GDD" in msg
    # the old nested-parenthetical noise is gone
    assert "aproximação de meia estação" not in msg
    assert "olive_bud_break" not in msg
    assert "método" not in msg
    # no double-nested parentheses anywhere
    assert "((" not in msg


def test_config_entry_defaults_only():
    reasons = _reasons(["soil FC/PWP (not configured, using clay-loam defaults)"], [])
    config = [r for r in reasons if r.category == "config"]
    assert len(config) == 1
    assert "CC/PMP" in config[0].message_pt


def test_config_entry_missing_only():
    reasons = _reasons([], ["crop profile not created"])
    config = [r for r in reasons if r.category == "config"]
    assert len(config) == 1
    assert "perfil de cultura" in config[0].message_pt


def test_no_config_entry_when_fully_configured():
    reasons = _reasons([], [])
    assert [r for r in reasons if r.category == "config"] == []
