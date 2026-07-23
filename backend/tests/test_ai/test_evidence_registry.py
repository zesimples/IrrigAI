"""Contract tests for backend-owned AI evidence IDs."""

from app.ai.evidence import build_evidence_registry
from app.schemas.ai import AgronomicCitation


def test_registry_assigns_stable_ids_to_exact_scalar_paths():
    context = {
        "water_balance": {
            "units": {"depletion_mm": "mm"},
            "depletion_mm": 12.5,
        },
        "weather": {"forecast": [{"rainfall_mm": 4.0}]},
    }

    first = build_evidence_registry(context)
    second = build_evidence_registry(context)

    depletion = first.entry_for_path("water_balance.depletion_mm")
    assert depletion is not None
    assert depletion.evidence_id.startswith("ev_")
    assert depletion.evidence_id == second.entry_for_path("water_balance.depletion_mm").evidence_id
    assert depletion.value == "12,5 mm"
    assert first.entry_for_path("weather.forecast[0].rainfall_mm") is not None


def test_whole_number_float_values_are_not_truncated():
    context = {
        "water_balance": {
            "units": {"depletion_mm": "mm", "taw_mm": "mm"},
            "depletion_mm": 40.0,
            "taw_mm": 100.0,
        },
    }

    registry = build_evidence_registry(context)

    depletion = registry.entry_for_path("water_balance.depletion_mm")
    taw = registry.entry_for_path("water_balance.taw_mm")
    assert depletion is not None and depletion.value == "40 mm"
    assert taw is not None and taw.value == "100 mm"


def test_registry_excludes_raw_vwc_values_from_citable_evidence():
    registry = build_evidence_registry(
        {
            "probe_signal": {
                "depths": [
                    {
                        "latest_vwc": 0.341,
                        "humidade_actual": "humidade adequada",
                    }
                ]
            }
        }
    )

    assert registry.entry_for_path("probe_signal.depths[0].latest_vwc") is None
    assert registry.entry_for_path("probe_signal.depths[0].humidade_actual") is not None


def test_probe_evidence_labels_identify_the_layer_and_hide_metadata():
    registry = build_evidence_registry(
        {
            "probe_signal": {
                "probe_id": "probe-001",
                "probe_external_id": "1597/3629",
                "sector_name": "Turno 4 (S15)",
                "soil_texture": "sandy_loam",
                "soil_bounds": {
                    "source": "probe_calibrated",
                },
                "root_depth_cm": 30,
                "depths": [
                    {
                        "depth_cm": 40,
                        "n_readings": 24,
                        "humidade_actual": "humidade baixa",
                        "tendencia": "a consumir gradualmente",
                    }
                ],
            }
        }
    )

    assert registry.entry_for_path("probe_signal.probe_id") is None
    assert registry.entry_for_path("probe_signal.probe_external_id") is None
    assert registry.entry_for_path("probe_signal.depths[0].depth_cm") is None

    sector = registry.entry_for_path("probe_signal.sector_name")
    soil_texture = registry.entry_for_path("probe_signal.soil_texture")
    bounds_source = registry.entry_for_path("probe_signal.soil_bounds.source")
    root_depth = registry.entry_for_path("probe_signal.root_depth_cm")
    humidity = registry.entry_for_path("probe_signal.depths[0].humidade_actual")
    trend = registry.entry_for_path("probe_signal.depths[0].tendencia")
    readings = registry.entry_for_path("probe_signal.depths[0].n_readings")

    assert sector is not None and sector.label == "Sector"
    assert soil_texture is not None
    assert (soil_texture.label, soil_texture.value) == (
        "Textura do solo",
        "Franco-arenoso",
    )
    assert bounds_source is not None
    assert (bounds_source.label, bounds_source.value) == (
        "Origem dos limites do solo",
        "Calibração da sonda",
    )
    assert root_depth is not None
    assert (root_depth.label, root_depth.value) == ("Profundidade radicular", "30 cm")
    assert humidity is not None and humidity.label == "Humidade actual a 40 cm"
    assert trend is not None and trend.label == "Tendência a 40 cm"
    assert readings is not None and readings.label == "Leituras a 40 cm"


def test_resolver_discards_unknown_ids_and_ignores_model_supplied_values():
    registry = build_evidence_registry(
        {"engine_decision": {"action": "defer", "confidence_score": 0.82}}
    )
    action = registry.entry_for_path("engine_decision.action")
    assert action is not None

    resolved = registry.resolve_citations(
        [
            AgronomicCitation(evidence_id=action.evidence_id),
            AgronomicCitation(evidence_id="ev_invented"),
        ]
    )

    assert len(resolved) == 1
    assert resolved[0].evidence_id == action.evidence_id
    assert resolved[0].source == "engine_decision.action"
    assert resolved[0].value == "Adiar rega"


def test_prompt_catalog_contains_ids_and_paths_but_not_duplicate_values():
    registry = build_evidence_registry(
        {"water_balance": {"depletion_mm": 12.5, "rain_skip_applies": False}}
    )

    catalog = registry.prompt_catalog()

    assert "water_balance.depletion_mm" in catalog
    assert "water_balance.rain_skip_applies" in catalog
    assert "12,5" not in catalog


def test_registry_hides_internal_metadata_and_localizes_scope_codes():
    registry = build_evidence_registry(
        {
            "scope": {
                "units": {"area_ha": "ha"},
                "sector": {
                    "id": "8de7fe5b-6fce-4ebc-95c4-a0ab2b055650",
                    "name": "Turno 1 (S05)",
                    "crop_type": "olive",
                    "current_phenological_stage": "olive_flowering",
                    "area_ha": 1.0,
                    "internal_flag": "raw_variable_code",
                },
            }
        }
    )

    assert registry.entry_for_path("scope.sector.id") is None
    assert registry.entry_for_path("scope.sector.internal_flag") is None
    assert all(entry.label != "Dados" for entry in registry.entries)

    crop = registry.entry_for_path("scope.sector.crop_type")
    stage = registry.entry_for_path("scope.sector.current_phenological_stage")
    sector = registry.entry_for_path("scope.sector.name")
    area = registry.entry_for_path("scope.sector.area_ha")
    assert sector is not None and (sector.label, sector.value) == (
        "Sector",
        "Turno 1 (S05)",
    )
    assert crop is not None and (crop.label, crop.value) == ("Cultura", "Olival")
    assert stage is not None and (stage.label, stage.value) == (
        "Fase fenológica",
        "Floração",
    )
    assert area is not None and (area.label, area.value) == ("Área", "1 ha")


def test_resolver_keeps_only_one_user_facing_row_per_label():
    registry = build_evidence_registry(
        {
            "engine_decision": {"action": "skip"},
            "recommendation_change": {"action": "irrigate"},
            "water_balance": {"depletion_mm": 29.04},
        }
    )
    skip = registry.entry_for_path("engine_decision.action")
    irrigate = registry.entry_for_path("recommendation_change.action")
    depletion = registry.entry_for_path("water_balance.depletion_mm")
    assert skip is not None and irrigate is not None and depletion is not None

    resolved = registry.resolve_citations(
        [
            AgronomicCitation(evidence_id=skip.evidence_id),
            AgronomicCitation(evidence_id=irrigate.evidence_id),
            AgronomicCitation(evidence_id=depletion.evidence_id),
        ]
    )

    assert [(item.label, item.value) for item in resolved] == [
        ("Decisão", "Não regar"),
        ("Depleção", "29,04"),
    ]


def test_change_analysis_keeps_both_latest_and_previous_decisions():
    registry = build_evidence_registry(
        {
            "recommendation_change": {
                "latest": {"action": "irrigate"},
                "previous": {"action": "skip"},
            }
        }
    )
    latest = registry.entry_for_path("recommendation_change.latest.action")
    previous = registry.entry_for_path("recommendation_change.previous.action")
    assert latest is not None and previous is not None

    resolved = registry.resolve_citations(
        [
            AgronomicCitation(evidence_id=latest.evidence_id),
            AgronomicCitation(evidence_id=previous.evidence_id),
        ]
    )

    assert len(resolved) == 2
    assert {item.label for item in resolved} == {
        "Decisão (recente)",
        "Decisão (anterior)",
    }
    assert {item.value for item in resolved} == {"Regar", "Não regar"}


def test_outcome_probe_response_uses_agronomic_wording_not_engine_code():
    path = "outcomes.items[0].details.probe_response_by_depth[0].response"
    registry = build_evidence_registry(
        {
            "outcomes": {
                "items": [
                    {
                        "details": {
                            "probe_response_by_depth": [{"depth_cm": 30, "response": "increase"}]
                        }
                    }
                ]
            }
        }
    )

    response = registry.entry_for_path(path)

    assert response is not None
    assert (response.label, response.value) == (
        "Resposta da sonda",
        "Humidade aumentou",
    )
