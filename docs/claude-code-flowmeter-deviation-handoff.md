# Flowmeter Deviation Improvements Handoff

## Scope

This change improves the `Desvio` behaviour in the Conqueiros flowmeter dashboard. It fixes period mismatches, calendar-day artefacts, self-influenced crop baselines, ambiguous missing-data states, and the accidental connection between dose deviation and flow-rate-reference status.

No database migration is required.

## New Algorithm

`Desvio` is now named **Desvio dotação**. It measures a sector's typical irrigation dose, not the flow rate and not its total consumption for the period.

For each selected period (`7d`, `30d`, or `season`):

1. Load `IrrigationEventDetected` rows for the active farm flowmeters.
2. For each sector with at least two events, calculate the median `total_m3_ha` per irrigation event.
3. For that sector, build a same-crop peer pool that excludes the sector itself.
4. Require at least two evaluated peers.
5. Compare the sector median with the leave-one-out median of the peer pool.

Formula:

```text
deviation_pct = (sector_median_dose - peer_median_dose) / peer_median_dose * 100
absolute_delta_m3ha = sector_median_dose - peer_median_dose
```

Severity bands:

- `normal`: absolute deviation <= 5%
- `info`: > 5% and <= 15%
- `warning`: > 15%
- `insufficient_data`: fewer than two detected events
- `insufficient_peer_data`: fewer than two same-crop peers with sufficient events

This is intentionally event-based. A night irrigation that crosses UTC midnight remains one operational event, avoiding the previous calendar-day split and raw-reading edge trimming.

## Backend Changes

- [backend/app/alerts/flowmeter_checker.py](/home/ze_simples/.openclaw/workspace/IrrigAI/backend/app/alerts/flowmeter_checker.py) now uses detected irrigation events, medians, leave-one-out peer baselines, explicit states, and information/warning alerts.
- [backend/app/api/v1/flowmeter.py](/home/ze_simples/.openclaw/workspace/IrrigAI/backend/app/api/v1/flowmeter.py) accepts `period=7d|30d|season` on `GET /farms/{farm_id}/flowmeter-deviations`.
- The flowmeter dashboard now also derives period totals, daily breakdowns, and event counts from `IrrigationEventDetected`, matching the deviation source.
- [backend/app/schemas/flowmeter.py](/home/ze_simples/.openclaw/workspace/IrrigAI/backend/app/schemas/flowmeter.py) adds the complete `sectors` result and explicit status/data-quality fields.

The scheduled alert engine continues to use a 7-day period. Deviations from 5% through 15% create `INFO` alerts; deviations above 15% create `WARNING` alerts.

## API Contract

Request:

```text
GET /api/v1/farms/{farm_id}/flowmeter-deviations?period=30d
```

`period` defaults to `7d` and supports `7d`, `30d`, and `season`.

The response now includes `sectors` for every active flowmeter sector. Each entry contains:

```json
{
  "status": "normal | info | warning | insufficient_data | insufficient_peer_data",
  "deviation_pct": 10.0,
  "absolute_delta_m3ha": 1.2,
  "sector_avg_m3ha": 13.2,
  "crop_avg_m3ha": 12.0,
  "event_count": 3,
  "peer_sector_count": 22
}
```

`deviation_pct`, `absolute_delta_m3ha`, `sector_avg_m3ha`, and `crop_avg_m3ha` are `null` when the comparison cannot be made.

Compatibility note: the old `interior_day_count` field is removed. Consumers must use `event_count`. `deviating` remains present, containing only `info` and `warning` sectors; `insufficient_data` remains as a summary list and now gives an event/peer reason.

## Frontend Changes

- [frontend/src/components/flowmeter/FlowmeterDashboard.tsx](/home/ze_simples/.openclaw/workspace/IrrigAI/frontend/src/components/flowmeter/FlowmeterDashboard.tsx) sends the active dashboard period to the deviation endpoint and maps every sector state.
- [frontend/src/components/flowmeter/FlowmeterSectorTable.tsx](/home/ze_simples/.openclaw/workspace/IrrigAI/frontend/src/components/flowmeter/FlowmeterSectorTable.tsx) labels the column `Desvio dotação`, explains the calculation in its tooltip, and exposes the new severity meanings.
- [frontend/src/components/flowmeter/DeviationCell.tsx](/home/ze_simples/.openclaw/workspace/IrrigAI/frontend/src/components/flowmeter/DeviationCell.tsx) shows `sem regas` and `sem pares` rather than an unexplained dash.
- [frontend/src/components/flowmeter/FlowmeterSectorRow.tsx](/home/ze_simples/.openclaw/workspace/IrrigAI/frontend/src/components/flowmeter/FlowmeterSectorRow.tsx) no longer passes peer-dose deviation into the flow-rate-reference indicator. Those are distinct calculations.
- [frontend/src/types/index.ts](/home/ze_simples/.openclaw/workspace/IrrigAI/frontend/src/types/index.ts) and [frontend/src/lib/api.ts](/home/ze_simples/.openclaw/workspace/IrrigAI/frontend/src/lib/api.ts) reflect the endpoint contract.

## Regression Coverage

[backend/tests/test_flowmeter/test_flowmeter_checker.py](/home/ze_simples/.openclaw/workspace/IrrigAI/backend/tests/test_flowmeter/test_flowmeter_checker.py) now covers:

- two-event minimum and two-peer minimum;
- night irrigation events crossing midnight;
- median dose per sector;
- leave-one-out baselines;
- resistance to a peer outlier;
- crop isolation;
- 5%/15% severity bands;
- Conqueiros-shaped comparable night-irrigation behaviour.

## Validation Performed

```text
docker compose run --rm -v /home/ze_simples/.openclaw/workspace/IrrigAI/backend:/app backend pytest tests/test_flowmeter/ tests/test_api/test_flowmeter_api.py tests/test_services/test_flowmeter_reference.py tests/test_alerts/test_flowmeter_flow_rate_alerts.py -q
# 76 passed

cd frontend && npm run test:run
# 57 passed

cd frontend && npx tsc --noEmit
# passed
```

Targeted Ruff checks also passed for the checker, schemas, tests, and modified router code. The router was linted with the repository's existing FastAPI annotation exceptions (`B008`, `F821`, `UP037`) ignored; those diagnostics predate this change.

## Production Checks

After deployment, verify:

1. Flowmeter ingestion is producing current `IrrigationEventDetected` rows for Conqueiros.
2. `GET /api/v1/farms/<conqueiros-id>/flowmeter-deviations?period=7d` returns all active sectors in `sectors`.
3. Switch the dashboard between 7 days, 30 days, and campaign; totals and `Desvio dotação` should both change with the selected period.
4. Confirm sectors with fewer than two irrigation events show `sem regas`, and sectors with too few comparable peers show `sem pares`.
5. Confirm `Caudal ref.` does not claim a crop-dose percentage is a flow-rate-reference deviation.

The local database used during development contains no flowmeter readings or detected events, so numerical validation against live Conqueiros observations must be performed after deploy.
