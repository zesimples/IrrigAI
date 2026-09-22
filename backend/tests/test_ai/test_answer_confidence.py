"""A0/A1 regression: confidence has three independent axes and no inflation.

The AI layer used to publish one model-authored percentage and then raise it to a
floor of 75% whenever the probe guard agreed with the engine.  Agreement with the
engine is not evidence; neither is a missing probe an opinion the model may hold.
"""

from __future__ import annotations

import pytest

from app.ai.answer_confidence import (
    DEGRADED_SCORE_CAP,
    derive_answer_confidence,
    numeric_score,
    resolve_data_quality,
    resolve_engine_confidence,
)


def _context(*, confidence_level=None, fresh=0, stale=0, total=0, live=True):
    return {
        "engine_decision": {
            "observed_at": None,
            "source": "recommendation.inputs_snapshot",
            "units": {},
            "available": confidence_level is not None,
            "action": "skip",
            "confidence_level": confidence_level,
        },
        "probe_state": {
            "observed_at": None,
            "source": "engine.probe_interpreter",
            "units": {},
            "live": {"hours_since_any_reading": 2.0} if live else None,
            "data_quality": {
                "fresh_depths": fresh,
                "stale_depths": stale,
                "total_depths": total,
            },
        },
    }


class TestEngineConfidence:
    def test_reads_the_engine_level_from_the_canonical_block(self):
        assert resolve_engine_confidence(_context(confidence_level="high")) == "high"

    def test_reads_the_legacy_flat_shape(self):
        assert resolve_engine_confidence({"confidence_level": "medium"}) == "medium"

    def test_probe_signal_latest_recommendation_carries_no_level(self):
        context = {"probe_signal": {"latest_recommendation": {"action": "skip"}}}
        assert resolve_engine_confidence(context) == "unknown"

    def test_absent_recommendation_is_unknown_not_low(self):
        assert resolve_engine_confidence(_context()) == "unknown"

    def test_unrecognised_value_is_unknown(self):
        assert resolve_engine_confidence({"confidence_level": "excellent"}) == "unknown"


class TestDataQuality:
    def test_all_depths_fresh(self):
        assert resolve_data_quality(_context(fresh=3, stale=0, total=3)) == "fresh"

    def test_any_stale_depth_degrades_quality(self):
        assert resolve_data_quality(_context(fresh=2, stale=1, total=3)) == "stale"

    def test_no_live_probe_is_missing(self):
        assert resolve_data_quality(_context(live=False)) == "missing"

    def test_no_probe_block_is_unknown(self):
        assert resolve_data_quality({}) == "unknown"


class TestNumericScore:
    def test_engine_confidence_is_the_ceiling(self):
        assert numeric_score("low", "fresh") < numeric_score("high", "fresh")

    def test_stale_data_lowers_a_high_engine_confidence(self):
        assert numeric_score("high", "stale") < numeric_score("high", "fresh")

    def test_missing_data_lowers_it_further(self):
        assert numeric_score("high", "missing") < numeric_score("high", "stale")

    def test_unknown_engine_confidence_never_reaches_the_high_band(self):
        assert numeric_score("unknown", "fresh") <= 0.5

    def test_score_stays_within_bounds(self):
        for engine in ("high", "medium", "low", "unknown"):
            for quality in ("fresh", "stale", "missing", "unknown"):
                assert 0.0 <= numeric_score(engine, quality) <= 1.0


class TestDeriveAnswerConfidence:
    def test_axes_are_reported_separately(self):
        confidence = derive_answer_confidence(
            _context(confidence_level="high", fresh=1, stale=2, total=3),
            explanation_status="generated",
        )
        assert confidence.engine_confidence == "high"
        assert confidence.data_quality == "stale"
        assert confidence.explanation_status == "generated"

    def test_agreement_with_the_engine_cannot_raise_confidence(self):
        """The old probe guard raised the score to 0.75 whenever it agreed."""
        poor = derive_answer_confidence(
            _context(confidence_level="low", live=False),
            explanation_status="generated",
        )
        assert poor.score < 0.75
        assert poor.data_quality == "missing"

    def test_degraded_explanation_is_capped_and_flagged(self):
        confidence = derive_answer_confidence(
            _context(confidence_level="high", fresh=3, total=3),
            explanation_status="degraded",
        )
        assert confidence.explanation_status == "degraded"
        assert confidence.score <= DEGRADED_SCORE_CAP

    def test_basis_is_pt_pt_and_names_both_axes(self):
        confidence = derive_answer_confidence(
            _context(confidence_level="medium", fresh=2, stale=1, total=3),
            explanation_status="generated",
        )
        assert "confiança" in confidence.basis.lower()
        # A stale-data answer must say so rather than reporting a bare percentage.
        assert "antig" in confidence.basis.lower() or "desactualiz" in confidence.basis.lower()

    def test_missing_data_basis_does_not_claim_a_measurement(self):
        confidence = derive_answer_confidence(
            _context(confidence_level="high", live=False),
            explanation_status="generated",
        )
        assert "sem leitura" in confidence.basis.lower()

    @pytest.mark.parametrize("status", ["generated", "degraded", "unavailable"])
    def test_every_explanation_status_produces_a_valid_block(self, status):
        confidence = derive_answer_confidence(_context(), explanation_status=status)
        assert confidence.explanation_status == status
        assert confidence.basis.strip()
