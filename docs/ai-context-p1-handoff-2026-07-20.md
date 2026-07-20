# AI context P1 handoff — 2026-07-20

## Outcome

Phase P1 now has a canonical, versioned sector context at
`backend/app/ai/context_v2.py`. `SectorAIContextV2` contains ten stable blocks:

1. `scope`
2. `engine_decision`
3. `water_balance`
4. `probe_state`
5. `weather`
6. `irrigation_execution`
7. `outcomes`
8. `crop_state`
9. `calibration`
10. `alerts_and_limitations`

Every block carries `observed_at`, `source`, and `units`. The latest immutable
`Recommendation.inputs_snapshot` owns `engine_decision` and `water_balance`;
live state comes from the existing shared weather, probe, soil-bound, and GDD
resolvers. The LLM does not recompute an agronomic decision.

## Data now included

- Recommendation identity, action, confidence, reasons, dose presentation, and
  full history.
- Snapshot water balance, ETc/effective rain, SWC source/model, and FC calibration.
- Canonical calibrated-preferred probe readings and diagnostics.
- Plot-scoped weather using the engine weather-scope resolver.
- Manual, probe-detected, and flowmeter-detected irrigation execution.
- Per-sector habitual dose (`IrrigationFingerprint`).
- Ten recent deterministic `RecommendationOutcome` rows.
- Crop profile, GDD progress, and snapshot stress projection.
- Effective soil bounds, active calibration, and calibration-run candidates/history.
- Deterministic alerts, confidence inputs, and explicit limitations.

## Surface routing

- Recommendation explanation cards use the compact projection.
- Sector diagnosis, sector chat, and change analysis use the full projection.
- The agentic chat seed uses a compact digest instead of rebuilding the old
  sector assistant context.
- `build_structured_agronomic_context()` is now a compatibility projection of V2.
  It retains the old evidence aliases until P2 introduces evidence IDs and direct
  structured rendering; they are aliases only, not independent data sources.
- Farm summaries remain on `FarmAssistantContext`. Aggregate farm-context query
  optimization is deliberately still P4.

## Tests and checks

- Failing-first evidence: the new contract suite initially failed during collection
  because `build_sector_ai_context_v2` did not exist.
- `backend/tests/test_ai/test_context_v2.py` covers the ten-block contract,
  mandatory provenance, snapshot authority, compact/full projections, outcomes,
  fingerprint, stress projection, and calibration candidates.
- Assistant/chat tests assert compact/full surface routing.
- AI-focused regression run: `81 passed`.
- Full backend run: `646 passed, 10 skipped`.
- Changed-file Ruff checks: clean.

No schema migration or frontend change is required for P1.

## Deliberately deferred

P2 and later remain untouched: evidence IDs plus direct React rendering, memory and
server-side chat persistence, rate/cost/error hardening and farm-query aggregation,
new outcome/calibration UI surfaces, and model routing.
