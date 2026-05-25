# Flowmeter Deviation Alarm — Design Spec

**Date:** 2026-05-25  
**Status:** Approved  

---

## Goal

Add a deviation alarm to the Caudalímetros (flowmeter) dashboard that flags any sector whose per-event water consumption deviates more than ±5% from the average of its crop peers. The alarm strips the first and last irrigation event of each day as outliers (system spin-up / wind-down), computes a clean average from interior events only, and surfaces inline on the flowmeter page — always visible when the user opens the tab.

---

## Context & Motivation

Each irrigation day typically starts and ends with a short, anomalous event: the system pressurises at the beginning and depressurises at the end. These events produce lower-than-normal m³/ha readings that can distort daily averages significantly. Over a 7-day window they have less impact, but on a per-day basis they introduce meaningful noise. The alarm must strip them before computing the comparison baseline.

---

## Outlier Stripping Algorithm

**Unit of stripping:** per sector per calendar day.

For each `(sector, date)` pair within the 7-day window:

| Events on that day | Action |
|--------------------|--------|
| 0 | Skip — sector did not irrigate that day |
| 1 | Exclude entirely — sole event is likely a start or close outlier |
| ≥ 2 | Sort by `start_time`; drop chronological first and last; keep interior events |

Interior events are the only events used in the deviation computation. The original events are never modified.

**Minimum data threshold:** a sector with fewer than **3 interior events total** across the 7-day window cannot be meaningfully evaluated and receives a `FLOWMETER_INSUFFICIENT_DATA` alert instead.

---

## Deviation Computation

```
interior_avg(sector)  = mean(total_m3_ha) across all interior events for that sector
crop_avg(crop_type)   = mean(interior_avg) across all sectors of the same crop_type
                        that have ≥ 3 interior events

deviation_pct(sector) = (interior_avg(sector) − crop_avg) / crop_avg × 100
```

**Trigger condition:** `|deviation_pct| > 5.0`  
**Direction:** `"above"` when positive, `"below"` when negative  
**Window:** 7 calendar days (fixed, not user-selectable for this check)

If a crop type has only one sector with sufficient data, the crop average equals that sector's own average — no deviation is possible. The sector is evaluated but will never fire a deviation alert. Sectors without an active flowmeter are skipped entirely.

---

## Alert Types

Two new values added to `AlertType` enum in `backend/app/core/enums.py`:

| `AlertType` value | Severity | Condition |
|---|---|---|
| `FLOWMETER_DEVIATION` | `WARNING` | Sector deviation > ±5% from crop interior average |
| `FLOWMETER_INSUFFICIENT_DATA` | `INFO` | Sector has < 3 interior events in the 7-day window |

Both integrate with the existing `Alert` model and reconciliation logic. The `data` JSONB field carries:

```json
// FLOWMETER_DEVIATION
{
  "deviation_pct": -12.4,
  "direction": "below",
  "sector_avg_m3ha": 14.2,
  "crop_avg_m3ha": 16.2,
  "interior_event_count": 8,
  "period_days": 7
}

// FLOWMETER_INSUFFICIENT_DATA
{
  "interior_event_count": 1,
  "period_days": 7
}
```

---

## Backend Architecture

### New file: `backend/app/alerts/flowmeter_checker.py`

`FlowmeterAlertChecker` class with two public methods:

**`check(farm_id, db) → list[Alert]`**  
Full pipeline: load events → strip outliers → compute averages → build `Alert` objects. Called by `AlertEngine`. Does **not** write to DB (AlertEngine's `reconcile_alerts` handles persistence).

**`compute_deviations(farm_id, db) → FlowmeterDeviationsResponse`**  
Same computation, returns structured response for the read-only endpoint. No DB writes, no alert objects.

Both methods share a single private `_compute(farm_id, db)` method that does the math and returns intermediate results consumed by both public methods.

### Modified: `backend/app/alerts/engine.py`

In `run_farm_alerts()`, after the per-sector loop and before `reconcile_alerts()`:

```python
from app.alerts.flowmeter_checker import FlowmeterAlertChecker
fm_alerts = await FlowmeterAlertChecker().check(farm_id, db)
new_alerts.extend(fm_alerts)
```

The existing reconciliation key `(alert_type, sector_id)` already handles deduplication correctly for the new alert types.

### Modified: `backend/app/core/enums.py`

```python
class AlertType(str, Enum):
    ...  # existing values unchanged
    FLOWMETER_DEVIATION = "flowmeter_deviation"
    FLOWMETER_INSUFFICIENT_DATA = "flowmeter_insufficient_data"
```

### New schemas in `backend/app/schemas/flowmeter.py`

```python
class FlowmeterDeviationSector(BaseModel):
    sector_id: str
    sector_name: str
    crop_type: str
    direction: str          # "above" | "below"
    deviation_pct: float
    sector_avg_m3ha: float
    crop_avg_m3ha: float
    interior_event_count: int

class FlowmeterInsufficientDataSector(BaseModel):
    sector_id: str
    sector_name: str
    crop_type: str
    interior_event_count: int

class FlowmeterDeviationsResponse(BaseModel):
    period_days: int
    deviating: list[FlowmeterDeviationSector]
    insufficient_data: list[FlowmeterInsufficientDataSector]
    crop_averages: dict[str, float]   # crop_type → interior avg m³/ha
    evaluated_at: datetime
```

### New endpoint in `backend/app/api/v1/flowmeter.py`

```
GET /farms/{farm_id}/flowmeter-deviations
```

Calls `FlowmeterAlertChecker().compute_deviations(farm_id, db)`. No authentication bypass, no caching (fast pure computation). Returns `FlowmeterDeviationsResponse`. Returns 404 if farm not found.

---

## Frontend Architecture

### New component: `frontend/src/components/flowmeter/FlowmeterDeviationWarnings.tsx`

- **Fetches** `GET /farms/{farm_id}/flowmeter-deviations` automatically on mount and when `farmId` changes
- **Never** requires a button click to show data (unlike AI analysis)
- **Collapsible** header (same pattern as `FlowmeterAIAnalysis`)
- **Loading skeleton** while fetching
- **Error state** with retry button

**Display logic:**

| State | Display |
|---|---|
| All sectors within range, no insufficient-data | ✅ "Consumo dentro do normal" (green) |
| Deviating sectors exist | List with sector name, direction badge, deviation % |
| Insufficient-data sectors exist | Gray list at bottom |
| Both | Deviating list first, insufficient-data below |

**Sector row format:**
```
Sector Alfa-3  [▲ +12.4%]  18.2 m³/ha  (média: 16.2)
Sector Beta-1  [▼ −8.1%]   14.9 m³/ha  (média: 16.2)
```

**Severity colours:**
- `direction = "above"` → `text-terra` (red) — over-irrigation risk
- `direction = "below"` → `text-amber-600` (amber) — under-irrigation risk
- Insufficient data → `text-ink-4` (gray)

**Refresh button** at bottom right (same style as "Atualizar análise" in `FlowmeterAIAnalysis`).

### New API method in `frontend/src/lib/api.ts`

Added to `flowmeterApi`:
```typescript
deviations: (farmId: string) =>
  get<FlowmeterDeviationsResponse>(`/farms/${farmId}/flowmeter-deviations`),
```

### New TypeScript types in `frontend/src/types/index.ts`

```typescript
export interface FlowmeterDeviationSector {
  sector_id: string;
  sector_name: string;
  crop_type: string;
  direction: "above" | "below";
  deviation_pct: number;
  sector_avg_m3ha: number;
  crop_avg_m3ha: number;
  interior_event_count: number;
}

export interface FlowmeterInsufficientDataSector {
  sector_id: string;
  sector_name: string;
  crop_type: string;
  interior_event_count: number;
}

export interface FlowmeterDeviationsResponse {
  period_days: number;
  deviating: FlowmeterDeviationSector[];
  insufficient_data: FlowmeterInsufficientDataSector[];
  crop_averages: Record<string, number>;
  evaluated_at: string;
}
```

### Modified: `frontend/src/components/flowmeter/FlowmeterDashboard.tsx`

The two analysis boxes sit in a responsive grid between the summary bar and the sector table:

```tsx
<div className="grid grid-cols-1 md:grid-cols-2 gap-3 mx-4 my-3">
  <FlowmeterAIAnalysis farmId={farmId} period={period} />
  <FlowmeterDeviationWarnings farmId={farmId} />
</div>
```

On mobile (single column): stacked vertically.  
On desktop (md+): side-by-side.  
`FlowmeterAIAnalysis` is moved out of its own `mx-4 my-3` wrapper since the grid now owns the spacing.

**Required change to `FlowmeterAIAnalysis.tsx`:** the outermost `<div>` currently has `className="border border-rule-soft rounded-lg mx-4 my-3 overflow-hidden bg-white"`. Remove `mx-4 my-3` from it (the grid wrapper provides the outer spacing). The `border`, `rounded-lg`, `overflow-hidden`, and `bg-white` remain.

---

## Testing

### Backend unit tests: `backend/tests/test_flowmeter/test_flowmeter_checker.py`

| Test | Scenario |
|---|---|
| `test_no_events_returns_empty` | Farm with no events in window → empty lists |
| `test_single_event_per_day_excluded` | Days with 1 event stripped → sector gets insufficient_data |
| `test_first_last_stripped_per_day` | Day with 3 events → only middle event used |
| `test_deviation_above_threshold` | Sector avg 10% above crop avg → FLOWMETER_DEVIATION alert |
| `test_deviation_below_threshold` | Sector avg 8% below → FLOWMETER_DEVIATION alert |
| `test_within_threshold_no_alert` | Sector avg 3% off → no alert |
| `test_insufficient_data_alert` | Sector with 2 interior events → FLOWMETER_INSUFFICIENT_DATA |
| `test_single_sector_per_crop_no_deviation` | Only one sector per crop → no deviation possible |
| `test_crop_isolation` | Almond and olive averages computed independently |

### Backend API test: `backend/tests/test_flowmeter/test_flowmeter_analysis_api.py`

Add `test_deviations_endpoint_unknown_farm_returns_404`.

### Frontend

No new unit tests for this component (stateless fetch-and-render, covered by the backend tests).

---

## Edge Cases

| Case | Handling |
|---|---|
| Farm has no flowmeters | `compute_deviations` returns empty `deviating` and `insufficient_data` lists |
| All events on a day are first/last (≤ 1 event) | That day contributes 0 interior events |
| Sector has no events in window | Not in deviating or insufficient_data (has no flowmeter data at all) |
| Single sector per crop | `crop_avg` equals that sector's own avg; deviation is always 0%; no alert |
| `crop_avg` is 0 (all sectors have 0 interior events) | Division guarded: skip deviation computation for that crop |

---

## What This Is NOT

- This alarm does **not** replace the existing `UNDERPERFORMANCE` alert type (which is water-balance-based)
- It does **not** touch probe data, soil moisture, or the agronomic engine
- It does **not** use the Redis cache (computation is fast, no LLM involved)
- It does **not** send push notifications (uses the existing alert infrastructure only)
