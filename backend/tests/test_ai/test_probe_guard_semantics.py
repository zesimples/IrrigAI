"""A0/A1 regressions for the probe-pattern interpretation guard.

The guard exists so the LLM can never contradict the deterministic engine.  It
must do exactly that and nothing more: it may not invent a reason the engine did
not give, may not declare every non-irrigation decision low risk, and may not
raise confidence because it agrees with the engine.
"""

from __future__ import annotations

import pytest

from app.ai.assistant import IrrigationAssistant
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import MockChatClient
from app.schemas.ai import AgronomicInterpretation


def _assistant() -> IrrigationAssistant:
    return IrrigationAssistant(
        context_builder=AssistantContextBuilder(),
        client=MockChatClient(),
        language="pt",
    )


def _interpretation(**overrides) -> AgronomicInterpretation:
    payload = {
        "summary": "Humidade crítica a 50 cm.",
        "risk_level": "high",
        "irrigation_advice": "Rega urgente para evitar stress hídrico.",
        "evidence": [],
        "missing_data": [],
        "confidence_score": 0.40,
        "confidence_explanation": "Explicação do modelo.",
        "recommended_actions": ["Aplicar rega imediatamente."],
    }
    payload.update(overrides)
    return AgronomicInterpretation(**payload)


def _stats(*, action="skip", reasons=None, live=True, stale_depths=0, **extra) -> dict:
    stats = {
        "latest_recommendation": {
            "action": action,
            "depletion_mm": 4.0,
            "taw_mm": 90.0,
            "depletion_pct": 4.4,
            "confidence_level": "medium",
            "reasons": reasons if reasons is not None else [],
        },
        "probe_state": {
            "live": {"hours_since_any_reading": 3.0} if live else None,
            "data_quality": {
                "fresh_depths": 0 if stale_depths else 3,
                "stale_depths": stale_depths,
                "total_depths": 3,
            },
        },
    }
    stats.update(extra)
    return stats


class TestNoConfidenceInflation:
    def test_guard_does_not_raise_the_confidence_score(self):
        """Regression: the guard used to force ``max(score, 0.75)``."""
        result = _assistant()._apply_probe_recommendation_guard(
            _stats(), _interpretation(confidence_score=0.40)
        )
        assert result.confidence_score <= 0.75
        assert result.confidence_score != 0.75 or result.confidence.engine_confidence == "high"

    def test_guard_cannot_hide_missing_probe_data(self):
        result = _assistant()._apply_probe_recommendation_guard(
            _stats(live=False), _interpretation()
        )
        assert result.confidence.data_quality == "missing"
        assert result.confidence_score < 0.75

    def test_confidence_block_reports_the_three_axes(self):
        result = _assistant()._apply_probe_recommendation_guard(_stats(), _interpretation())
        assert result.confidence.engine_confidence == "medium"
        assert result.confidence.data_quality == "fresh"
        assert result.confidence.explanation_status == "generated"


class TestEngineReasonIsPreserved:
    def test_guard_quotes_the_engine_reason_instead_of_inventing_one(self):
        """The engine deferred for rain; the guard used to say "reserva suficiente"."""
        result = _assistant()._apply_probe_recommendation_guard(
            _stats(
                action="defer",
                reasons=[{"category": "weather", "message": "Chuva prevista nas próximas 48 h."}],
            ),
            _interpretation(),
        )
        assert "Chuva prevista nas próximas 48 h." in result.irrigation_advice
        assert "reserva suficiente" not in result.irrigation_advice.lower()

    def test_without_an_engine_reason_the_advice_stays_neutral(self):
        result = _assistant()._apply_probe_recommendation_guard(
            _stats(reasons=[]), _interpretation()
        )
        advice = result.irrigation_advice.lower()
        assert "não reg" in advice
        # No fabricated agronomic justification when the engine supplied none.
        assert "reserva suficiente" not in advice

    def test_irrigation_advice_never_contradicts_the_engine(self):
        result = _assistant()._apply_probe_recommendation_guard(_stats(), _interpretation())
        assert "urgente" not in result.irrigation_advice.lower()
        assert all("urgente" not in action.lower() for action in result.recommended_actions)


class TestRiskIsNotAutomaticallyLow:
    def test_fresh_data_and_no_deficit_is_low_risk(self):
        result = _assistant()._apply_probe_recommendation_guard(_stats(), _interpretation())
        assert result.risk_level == "low"

    def test_stale_sensor_data_is_not_low_risk(self):
        """Irrigation urgency and sensor reliability are different questions."""
        result = _assistant()._apply_probe_recommendation_guard(
            _stats(stale_depths=2), _interpretation()
        )
        assert result.risk_level == "medium"

    def test_missing_probe_data_is_not_low_risk(self):
        result = _assistant()._apply_probe_recommendation_guard(
            _stats(live=False), _interpretation()
        )
        assert result.risk_level == "medium"


class TestGuardStillOnlyFiresForNoIrrigation:
    @pytest.mark.parametrize("action", ["irrigate", "reduce", "increase"])
    def test_untouched_when_the_engine_says_irrigate(self, action):
        stats = _stats(action=action)
        stats["latest_recommendation"]["depletion_pct"] = 62.0
        stats["latest_recommendation"]["depletion_mm"] = 55.0
        original = _interpretation()
        result = _assistant()._apply_probe_recommendation_guard(stats, original)
        assert result.irrigation_advice == original.irrigation_advice
        assert result.risk_level == "high"


class TestProbeDiagnosisConfidenceIsDerivedFromTheStats:
    """Regression found by the live golden set (A4).

    ``_complete_structured`` receives the stats wrapped under ``probe_signal`` so the
    evidence registry can cite them by path. Reading confidence through that wrapper
    graded every probe diagnosis as "unknown/unknown" even with fresh readings.
    """

    @pytest.mark.asyncio
    async def test_irrigate_case_reports_the_real_axes(self, monkeypatch):
        from unittest.mock import AsyncMock

        stats = _stats(action="irrigate")
        stats["latest_recommendation"]["depletion_pct"] = 55.0
        stats["latest_recommendation"]["depletion_mm"] = 48.0
        stats["depths"] = [{"depth_cm": 30, "humidade_actual": "humidade baixa"}]

        assistant = _assistant()
        monkeypatch.setattr(
            "app.ai.assistant.compute_probe_signal_stats",
            AsyncMock(return_value=stats),
        )

        result = await assistant.interpret_probe_patterns_structured("probe-1", None)

        assert result.confidence.engine_confidence == "medium"
        assert result.confidence.data_quality == "fresh"

    @pytest.mark.asyncio
    async def test_missing_readings_are_not_graded_as_fresh(self, monkeypatch):
        from unittest.mock import AsyncMock

        stats = _stats(action="irrigate", live=False)
        stats["latest_recommendation"]["depletion_pct"] = 55.0
        stats["latest_recommendation"]["depletion_mm"] = 48.0

        assistant = _assistant()
        monkeypatch.setattr(
            "app.ai.assistant.compute_probe_signal_stats",
            AsyncMock(return_value=stats),
        )

        result = await assistant.interpret_probe_patterns_structured("probe-1", None)

        assert result.confidence.data_quality == "missing"
        assert result.confidence_score < 0.75
