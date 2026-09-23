"""A0/A2 regressions: chat prose must be checked against the data it cites.

Before A2 the chat reply was returned verbatim. Nothing stopped the model from
inventing a dose, restating a farmer's unverified note as a measurement, or
recommending irrigation on a sector the engine had told to skip.
"""

from __future__ import annotations

import pytest

from app.ai.chat_grounding import (
    GroundedFacts,
    collect_facts,
    deterministic_fallback_reply,
    extract_numeric_claims,
    validate_reply,
)


class TestNumericClaimExtraction:
    def test_reads_pt_decimal_commas(self):
        claims = extract_numeric_claims("Aplica 12,5 mm hoje.")
        assert (12.5, "mm") in {(c.value, c.unit) for c in claims}

    def test_reads_percentages(self):
        claims = extract_numeric_claims("O solo perdeu 45% da água disponível.")
        assert (45.0, "%") in {(c.value, c.unit) for c in claims}

    def test_reads_cubic_metres_per_hectare(self):
        claims = extract_numeric_claims("Aplicaste 17,4 m³/ha no último evento.")
        assert any(c.unit.startswith("m3") for c in claims)

    def test_ignores_planning_horizons(self):
        """'nas próximas 24-48 horas' is planning language, not a measurement."""
        claims = extract_numeric_claims("Vigia nas próximas 24-48 horas.")
        assert claims == []

    def test_ignores_bare_numbers(self):
        assert extract_numeric_claims("Tens 3 setores por rever.") == []


class TestFactCollection:
    def test_evidence_does_not_cite_a_different_sector_with_the_same_value(self):
        from app.ai.chat_grounding import select_chat_evidence
        from app.ai.evidence import build_evidence_registry

        registry = build_evidence_registry(
            {
                "sectors": {
                    "units": {"depletion_mm": "mm"},
                    "items": [
                        {"name": "Olival", "depletion_mm": 8},
                        {"name": "Vinha", "depletion_mm": 8},
                    ],
                }
            }
        )
        evidence = select_chat_evidence(
            "Vinha: depleção de 8 mm.",
            registry,
            scopes={"sectors.items[0]": "Olival", "sectors.items[1]": "Vinha"},
        )
        assert evidence
        assert all(item.source.startswith("sectors.items[1].") for item in evidence)

    def test_farm_overview_keeps_sector_measurements_separate(self):
        facts = collect_facts(
            [
                {
                    "tool": "get_farm_overview",
                    "result": {
                        "sectors": [
                            {
                                "sector_id": "a",
                                "name": "Olival",
                                "action": "skip",
                                "depletion_mm": 8,
                            },
                            {
                                "sector_id": "b",
                                "name": "Vinha",
                                "action": "irrigate",
                                "irrigation_depth_mm": 12,
                                "depletion_mm": 40,
                            },
                        ]
                    },
                }
            ]
        )
        assert validate_reply("Olival: depleção de 8 mm. Vinha: aplica 12 mm.", facts).ok
        assert not validate_reply("Olival: depleção de 40 mm.", facts).ok
        assert not validate_reply("Olival: aplica 12 mm.", facts).ok
        assert not validate_reply("Aplica 12 mm.", facts).ok

    def test_selected_sector_does_not_borrow_overview_values(self):
        facts = collect_facts(
            [
                {
                    "tool": "get_farm_overview",
                    "result": {
                        "sectors": [
                            {
                                "sector_id": "a",
                                "name": "Olival",
                                "action": "skip",
                                "depletion_mm": 8,
                            },
                            {
                                "sector_id": "b",
                                "name": "Vinha",
                                "action": "irrigate",
                                "irrigation_depth_mm": 12,
                            },
                        ]
                    },
                }
            ],
            selected_sector_id="a",
        )
        assert validate_reply("A depleção é 8 mm.", facts).ok
        assert not validate_reply("Aplica 12 mm.", facts).ok

    def test_collects_engine_action_and_dose_from_tool_results(self):
        facts = collect_facts(
            [
                {
                    "tool": "get_sector_status",
                    "result": {
                        "action": "irrigate",
                        "irrigation_depth_mm": 12.0,
                        "recommendation_id": "rec-1",
                        "depletion_mm": 34.5,
                    },
                }
            ]
        )
        assert facts.engine_action == "irrigate"
        assert facts.engine_depth_mm == 12.0
        assert facts.recommendation_id == "rec-1"
        assert facts.supports(12.0, "mm")
        assert facts.supports(34.5, "mm")

    def test_does_not_treat_an_unverified_note_as_a_measurement(self):
        facts = collect_facts(
            [
                {
                    "tool": "get_field_observations",
                    "result": {
                        "field_observations": [
                            {"text": "apliquei 30 mm", "verified": False, "source": "user"}
                        ]
                    },
                }
            ]
        )
        assert not facts.supports(30.0, "mm")

    def test_error_results_contribute_no_facts(self):
        facts = collect_facts([{"tool": "get_sector_status", "result": {"error": "x"}}])
        assert facts.engine_action is None
        assert not facts.supports(1.0, "mm")


class TestValidation:
    def test_multiple_measurements_keep_their_own_labels(self):
        facts = collect_facts(
            [
                {
                    "tool": "get_sector_status",
                    "result": {
                        "action": "irrigate",
                        "irrigation_depth_mm": 14,
                        "depletion_mm": 41.2,
                        "rainfall_mm": 0,
                    },
                }
            ]
        )
        assert validate_reply("Aplica 14 mm, com depleção de 41,2 mm e chuva de 0 mm.", facts).ok
        assert not validate_reply("Aplica 41,2 mm, com depleção de 14 mm.", facts).ok
        assert not validate_reply("Há 14 mm de depleção.", facts).ok
        assert validate_reply("Sem chuva prevista, a dotação recomendada é de 14 mm.", facts).ok

    def test_empty_answer_requires_repair(self):
        assert not validate_reply("  ", self._facts()).ok

    def test_unknown_volume_is_not_silently_accepted(self):
        assert not validate_reply("Foram aplicados 500 L.", self._facts()).ok

    def test_decimal_point_does_not_split_the_dose_claim(self):
        assert not validate_reply(
            "Dotação recomendada: 8.0 mm.", self._facts(action="irrigate", depth=12)
        ).ok

    @pytest.mark.parametrize(
        "reply", ["Deves regar agora com 40 mm.", "Aplica 40 mm.", "Dotação recomendada: 40 mm."]
    )
    def test_measured_depletion_is_not_the_engine_dose(self, reply):
        facts = collect_facts(
            [
                {
                    "tool": "get_sector_status",
                    "result": {
                        "action": "irrigate",
                        "irrigation_depth_mm": 12,
                        "depletion_mm": 40,
                    },
                }
            ]
        )
        assert not validate_reply(reply, facts).ok

    def test_skip_rejects_apply_even_if_number_is_real(self):
        assert not validate_reply("Aplica 8 mm.", self._facts()).ok

    def test_measurement_label_cannot_borrow_other_field(self):
        facts = collect_facts([{"tool": "get_weather", "result": {"rainfall_mm": 40}}])
        assert not validate_reply("A depleção é 40 mm.", facts).ok

    def _facts(self, **kw) -> GroundedFacts:
        return collect_facts(
            [
                {
                    "tool": "get_sector_status",
                    "result": {
                        "action": kw.get("action", "skip"),
                        "irrigation_depth_mm": kw.get("depth"),
                        "depletion_mm": 8.0,
                        "recommendation_id": "rec-1",
                    },
                }
            ]
        )

    def test_a_grounded_reply_passes(self):
        result = validate_reply("A depleção está em 8 mm.", self._facts())
        assert result.ok
        assert result.issues == []

    def test_an_invented_dose_is_rejected(self):
        result = validate_reply("Aplica 25 mm hoje.", self._facts())
        assert not result.ok
        assert any(issue.kind == "unsupported_number" for issue in result.issues)

    def test_irrigation_advice_against_a_skip_decision_is_rejected(self):
        result = validate_reply("Deves regar já este setor.", self._facts(action="skip"))
        assert not result.ok
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    def test_not_irrigating_against_an_irrigate_decision_is_rejected(self):
        result = validate_reply(
            "Não regues este setor hoje.", self._facts(action="irrigate", depth=12.0)
        )
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    def test_matching_the_engine_dose_is_allowed(self):
        result = validate_reply(
            "A recomendação é regar 12 mm.", self._facts(action="irrigate", depth=12.0)
        )
        assert result.ok

    def test_small_rounding_differences_are_tolerated(self):
        result = validate_reply(
            "A recomendação é regar 12,04 mm.", self._facts(action="irrigate", depth=12.0)
        )
        assert result.ok

    def test_without_engine_facts_no_conflict_is_claimed(self):
        facts = collect_facts([])
        result = validate_reply("Deves regar já.", facts)
        assert all(issue.kind != "engine_conflict" for issue in result.issues)

    def test_issue_text_is_pt_pt_and_names_the_offending_value(self):
        result = validate_reply("Aplica 25 mm hoje.", self._facts())
        assert "25" in result.issues[0].detail
        assert result.issues[0].detail.strip()


class TestDeterministicFallback:
    def test_states_the_engine_decision_without_inventing_numbers(self):
        facts = collect_facts(
            [
                {
                    "tool": "get_sector_status",
                    "result": {
                        "action": "irrigate",
                        "irrigation_depth_mm": 12.0,
                        "recommendation_id": "rec-1",
                    },
                }
            ]
        )
        reply = deterministic_fallback_reply(facts)
        assert "12" in reply
        assert validate_reply(reply, facts).ok

    def test_is_honest_when_there_is_nothing_to_report(self):
        reply = deterministic_fallback_reply(collect_facts([]))
        assert reply.strip()
        assert validate_reply(reply, collect_facts([])).ok

    @pytest.mark.parametrize("action", ["skip", "defer"])
    def test_no_irrigation_decisions_do_not_advise_irrigating(self, action):
        facts = collect_facts([{"tool": "get_sector_status", "result": {"action": action}}])
        reply = deterministic_fallback_reply(facts)
        assert validate_reply(reply, facts).ok


class TestMultiTurnFacts:
    """Regressions found by the live multi-turn evaluation (A4)."""

    def test_a_value_verified_last_turn_stays_quotable(self):
        facts = collect_facts(
            [],
            prior_evidence=[{"label": "Depleção", "value": "9,4 mm", "source": "x"}],
        )
        assert not validate_reply("A depleção continua em 9,4 mm.", facts).ok

    def test_a_number_the_user_introduced_may_be_echoed(self):
        facts = collect_facts(
            [{"tool": "get_sector_status", "result": {"action": "skip", "depletion_mm": 9.4}}],
            user_message="E se eu regar 30 mm mesmo assim?",
        )
        assert not validate_reply("Aplicar 30 mm seria mais do que o solo precisa.", facts).ok

    def test_echoing_the_user_is_still_not_a_licence_to_advise_irrigation(self):
        facts = collect_facts(
            [{"tool": "get_sector_status", "result": {"action": "skip"}}],
            user_message="E se eu regar 30 mm?",
        )
        result = validate_reply("Deves regar 30 mm hoje.", facts)
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    def test_a_user_number_is_not_promoted_to_a_measurement(self):
        facts = collect_facts([], user_message="Reguei 30 mm ontem.")
        assert not facts.supports(30.0, "mm")
        assert not facts.is_measured(30.0, "mm")

    def test_an_invented_number_is_still_rejected_with_prior_evidence_present(self):
        facts = collect_facts(
            [],
            prior_evidence=[{"label": "Depleção", "value": "9,4 mm", "source": "x"}],
        )
        assert not validate_reply("A depleção está em 41 mm.", facts).ok


class TestNegatedDirectives:
    """Regression found by the live multi-turn evaluation (A4).

    "não deves regar" contains "deves regar"; matching that as advice to irrigate
    rejected the exact answers the validator exists to protect, and every such turn
    collapsed to the deterministic fallback.
    """

    def _skip_facts(self) -> GroundedFacts:
        return collect_facts(
            [{"tool": "get_sector_status", "result": {"action": "skip", "depletion_mm": 6.0}}]
        )

    def _irrigate_facts(self) -> GroundedFacts:
        return collect_facts(
            [
                {
                    "tool": "get_sector_status",
                    "result": {"action": "irrigate", "irrigation_depth_mm": 12.0},
                }
            ]
        )

    @pytest.mark.parametrize(
        "reply",
        [
            "Não deves regar hoje.",
            "Não recomendo regar neste momento.",
            "Não é necessário regar hoje.",
            "Sem necessidade de regar agora.",
            "Evita regar hoje — o solo tem reserva.",
            "Aguarda antes de regar hoje.",
        ],
    )
    def test_negated_advice_is_not_an_irrigation_directive(self, reply):
        assert validate_reply(reply, self._skip_facts()).ok

    @pytest.mark.parametrize(
        "reply",
        ["Deves regar hoje.", "Recomendo regar já.", "Rega agora este setor."],
    )
    def test_a_real_directive_is_still_caught(self, reply):
        result = validate_reply(reply, self._skip_facts())
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    def test_a_negation_in_a_previous_clause_does_not_excuse_a_later_directive(self):
        result = validate_reply("Não há chuva prevista; deves regar hoje.", self._skip_facts())
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    def test_skip_advice_against_an_irrigate_decision_is_still_caught(self):
        result = validate_reply("Não regues hoje.", self._irrigate_facts())
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    def test_explaining_an_irrigate_decision_is_not_a_skip_directive(self):
        assert validate_reply("A recomendação é regar 12 mm hoje.", self._irrigate_facts()).ok


class TestEngineAuthorityCannotBeBypassed:
    """Independent review 2026-09-23 (B1-B3).

    The negation scan added for the regression above suppressed a directive whenever
    *any* negation appeared earlier in a comma-joined sentence, so ordinary Portuguese
    ("não choveu, por isso deves regar") switched off every engine-authority check. A
    negation only inverts a directive it is attached to; and a negated irrigation
    directive is itself advice not to irrigate.
    """

    def _skip_facts(self, **extra) -> GroundedFacts:
        return collect_facts(
            [
                {
                    "tool": "get_sector_status",
                    "result": {
                        "action": "skip",
                        "irrigation_depth_mm": 0.0,
                        "depletion_mm": 12.0,
                        **extra,
                    },
                }
            ]
        )

    def _irrigate_facts(self, **extra) -> GroundedFacts:
        return collect_facts(
            [
                {
                    "tool": "get_sector_status",
                    "result": {"action": "irrigate", "irrigation_depth_mm": 12.0, **extra},
                }
            ]
        )

    @pytest.mark.parametrize(
        "reply",
        [
            "Hoje não choveu, por isso deves regar 12 mm.",
            "Não há previsão de chuva, por isso aplica 12 mm hoje.",
            "Sem rega nas últimas 48 horas, recomendo regar hoje.",
            "Como não choveu deves regar hoje.",
        ],
    )
    def test_an_unrelated_negation_does_not_excuse_irrigation_advice(self, reply):
        result = validate_reply(reply, self._skip_facts())
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    def test_an_unrelated_negation_does_not_excuse_advice_without_an_engine_decision(self):
        result = validate_reply("Hoje não choveu, por isso deves regar.", collect_facts([]))
        assert any(issue.kind == "missing_engine" for issue in result.issues)

    def test_a_dose_cannot_ground_on_total_available_water(self):
        result = validate_reply(
            "Recomendo uma dotação de 120 mm para hoje.", self._skip_facts(taw_mm=120.0)
        )
        assert not result.ok
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    @pytest.mark.parametrize(
        "reply",
        ["A dotação de hoje é de 120 mm.", "Recomendo uma dose de 120 mm.", "Lâmina de 120 mm."],
    )
    def test_a_dose_label_binds_to_the_engine_dose_not_any_mm_field(self, reply):
        assert not validate_reply(reply, self._irrigate_facts(taw_mm=120.0)).ok

    def test_a_measurement_next_to_advice_is_not_read_as_the_dose(self):
        facts = self._irrigate_facts(depletion_mm=40.0)
        assert validate_reply("Deves regar 12 mm hoje: a depleção já atingiu 40 mm.", facts).ok

    def test_past_applied_irrigation_is_still_quotable(self):
        facts = self._skip_facts(last_irrigation_applied_mm=18.0)
        assert validate_reply("A última rega aplicou 18 mm.", facts).ok

    @pytest.mark.parametrize(
        "reply",
        [
            "No Olival Norte podes saltar a rega.",
            "Não é preciso regar hoje.",
            "Não deves regar hoje.",
            "Deixa a rega para amanhã.",
            "Aguarda antes de regar hoje.",
        ],
    )
    def test_advice_not_to_irrigate_contradicts_an_irrigate_decision(self, reply):
        result = validate_reply(reply, self._irrigate_facts())
        assert any(issue.kind == "engine_conflict" for issue in result.issues)

    @pytest.mark.parametrize(
        "reply",
        ["Não deixes de regar hoje.", "Não há chuva prevista, por isso rega hoje 12 mm."],
    )
    def test_irrigation_advice_agreeing_with_the_engine_passes(self, reply):
        assert validate_reply(reply, self._irrigate_facts()).ok


class TestFarmLevelFactsInMultiSectorTurns:
    """Review 2026-09-23: weather read in a farm conversation carries no sector, and it
    was discarded whenever the overview named more than one sector — so a correct
    "Prevê-se 8 mm de chuva" fell back, inflating the fallback rate for good answers.
    """

    def _facts(self) -> GroundedFacts:
        return collect_facts(
            [
                {
                    "tool": "get_farm_overview",
                    "result": {
                        "sectors": [
                            {
                                "sector_id": "a",
                                "name": "Olival",
                                "action": "skip",
                                "depletion_mm": 8,
                            },
                            {
                                "sector_id": "b",
                                "name": "Vinha",
                                "action": "irrigate",
                                "irrigation_depth_mm": 12,
                                "depletion_mm": 40,
                            },
                        ]
                    },
                },
                {"tool": "get_weather", "result": {"rainfall_mm": 8.0, "et0_mm": 4.2}},
            ]
        )

    def test_farm_level_weather_grounds_without_naming_a_sector(self):
        assert validate_reply("Prevê-se 8 mm de chuva nas próximas 48 horas.", self._facts()).ok

    def test_a_sector_value_still_needs_its_sector_named(self):
        assert not validate_reply("A depleção é de 40 mm.", self._facts()).ok

    def test_advice_still_needs_its_sector_named(self):
        result = validate_reply("Deves regar hoje.", self._facts())
        assert any(issue.kind == "ambiguous_scope" for issue in result.issues)

    def test_sector_clauses_are_still_checked_against_their_own_sector(self):
        facts = self._facts()
        assert validate_reply("Prevê-se 8 mm de chuva. Vinha: aplica 12 mm.", facts).ok
        assert not validate_reply("Prevê-se 8 mm de chuva. Olival: aplica 12 mm.", facts).ok
