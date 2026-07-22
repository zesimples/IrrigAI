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
    assert depletion.evidence_id == second.entry_for_path(
        "water_balance.depletion_mm"
    ).evidence_id
    assert depletion.value == "12,5 mm"
    assert first.entry_for_path("weather.forecast[0].rainfall_mm") is not None


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
    root_depth = registry.entry_for_path("probe_signal.root_depth_cm")
    humidity = registry.entry_for_path("probe_signal.depths[0].humidade_actual")
    trend = registry.entry_for_path("probe_signal.depths[0].tendencia")
    readings = registry.entry_for_path("probe_signal.depths[0].n_readings")

    assert sector is not None and sector.label == "Sector"
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
