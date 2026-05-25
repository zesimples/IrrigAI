# Flowmeter Deviation Alarm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag sectors whose per-event water consumption deviates >±5% from their crop peers, stripping system spin-up/wind-down outliers (first + last event per sector per day), and surface the results inline on the Caudalímetros dashboard next to the AI analysis.

**Architecture:** A new `FlowmeterAlertChecker` service does the outlier stripping and deviation maths (pure computation, testable without DB). `AlertEngine.run_farm_alerts()` delegates to it for DB-backed alert persistence. A new `GET /farms/{id}/flowmeter-deviations` endpoint exposes the same computation for the inline frontend component `FlowmeterDeviationWarnings`, which auto-loads when the page opens and sits side-by-side with `FlowmeterAIAnalysis` in a responsive grid.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, Pydantic v2, React/Next.js 14, Tailwind CSS. Tests run inside the Docker container via `docker compose exec backend pytest`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/core/enums.py` | Modify | Add `FLOWMETER_DEVIATION` + `FLOWMETER_INSUFFICIENT_DATA` to `AlertType` |
| `backend/app/schemas/flowmeter.py` | Modify | Add 3 new response schema classes |
| `backend/app/alerts/flowmeter_checker.py` | Create | `FlowmeterAlertChecker` — outlier stripping, deviation computation, alert generation |
| `backend/tests/test_flowmeter/test_flowmeter_checker.py` | Create | 9 unit tests for the checker (no DB) |
| `backend/app/alerts/engine.py` | Modify | Call checker inside `run_farm_alerts()` |
| `backend/app/api/v1/flowmeter.py` | Modify | `GET /farms/{farm_id}/flowmeter-deviations` endpoint |
| `backend/tests/test_flowmeter/test_flowmeter_analysis_api.py` | Modify | 404 test for new endpoint |
| `frontend/src/types/index.ts` | Modify | 3 new TypeScript interfaces |
| `frontend/src/lib/api.ts` | Modify | `deviations` method on `flowmeterApi` |
| `frontend/src/components/flowmeter/FlowmeterDeviationWarnings.tsx` | Create | Auto-loading deviation warnings component |
| `frontend/src/components/flowmeter/FlowmeterDashboard.tsx` | Modify | Wrap AI analysis + warnings in responsive grid |
| `frontend/src/components/flowmeter/FlowmeterAIAnalysis.tsx` | Modify | Remove outer `mx-4 my-3` (grid takes over spacing) |

---

## Task 1: AlertType enum values + response schemas

**Files:**
- Modify: `backend/app/core/enums.py`
- Modify: `backend/app/schemas/flowmeter.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_flowmeter/test_flowmeter_checker.py` with just the enum/schema smoke tests for now (the full test suite gets added in Task 2):

```python
# backend/tests/test_flowmeter/test_flowmeter_checker.py
"""Tests for FlowmeterAlertChecker — outlier stripping and deviation logic."""
from datetime import date, datetime, timezone

import pytest
from unittest.mock import MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_event(fm_id: str, start_dt: datetime, total_m3_ha: float) -> MagicMock:
    """Create a mock IrrigationEventDetected."""
    e = MagicMock()
    e.flowmeter_id = fm_id
    e.start_time = start_dt
    e.total_m3_ha = total_m3_ha
    e.date = start_dt.date()
    return e


def _make_pair(fm_id: str, sector_id: str, sector_name: str, crop_type: str):
    """Create a mock (Flowmeter, Sector) pair."""
    fm = MagicMock()
    fm.id = fm_id
    sector = MagicMock()
    sector.id = sector_id
    sector.name = sector_name
    sector.crop_type = crop_type
    return (fm, sector)


def _day_events(fm_id: str, day: date, values: list) -> list:
    """Create events for a single day at 06:00, 07:00, … one per value."""
    return [
        _make_event(
            fm_id,
            datetime(day.year, day.month, day.day, 6 + i, 0, tzinfo=timezone.utc),
            v,
        )
        for i, v in enumerate(values)
    ]


BASE_DATE = date(2026, 5, 18)


def _days(n: int) -> list:
    from datetime import timedelta
    return [BASE_DATE + timedelta(days=i) for i in range(n)]


# ── enum / schema smoke tests ─────────────────────────────────────────────────

def test_flowmeter_deviation_alert_type_value():
    from app.core.enums import AlertType
    assert AlertType.FLOWMETER_DEVIATION == "flowmeter_deviation"


def test_flowmeter_insufficient_data_alert_type_value():
    from app.core.enums import AlertType
    assert AlertType.FLOWMETER_INSUFFICIENT_DATA == "flowmeter_insufficient_data"


def test_flowmeter_deviations_response_schema_constructs():
    from datetime import datetime
    from app.schemas.flowmeter import FlowmeterDeviationsResponse
    r = FlowmeterDeviationsResponse(
        period_days=7,
        deviating=[],
        insufficient_data=[],
        crop_averages={},
        evaluated_at=datetime.now(timezone.utc),
    )
    assert r.period_days == 7
    assert r.deviating == []
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
docker compose exec backend pytest tests/test_flowmeter/test_flowmeter_checker.py::test_flowmeter_deviation_alert_type_value -v
```

Expected: `FAILED` — `AttributeError: FLOWMETER_DEVIATION`

- [ ] **Step 3: Add the two new AlertType values**

Open `backend/app/core/enums.py`. Find the `AlertType` class and append two new entries **after the existing `STALE_WEATHER` line**:

```python
class AlertType(str, Enum):
    WATER_STRESS = "water_stress"
    OVER_IRRIGATION = "over_irrigation"
    PROBE_ANOMALY = "probe_anomaly"
    DEEP_DRAINAGE = "deep_drainage"
    RAIN_SKIP = "rain_skip"
    UNDERPERFORMANCE = "underperformance"
    LOW_CONFIDENCE = "low_confidence"
    MISSING_DATA = "missing_data"
    STALE_PROBE = "stale_probe"
    STALE_WEATHER = "stale_weather"
    FLOWMETER_DEVIATION = "flowmeter_deviation"
    FLOWMETER_INSUFFICIENT_DATA = "flowmeter_insufficient_data"
```

- [ ] **Step 4: Add the three new schema classes**

Open `backend/app/schemas/flowmeter.py`. The file already imports `from datetime import date, datetime` and `from pydantic import BaseModel, Field`.

Append at the **very end** of the file:

```python

# ── Deviation alarm schemas ───────────────────────────────────────────────────

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

- [ ] **Step 5: Run the tests — all three should pass**

```bash
docker compose exec backend pytest tests/test_flowmeter/test_flowmeter_checker.py -v
```

Expected:
```
PASSED test_flowmeter_deviation_alert_type_value
PASSED test_flowmeter_insufficient_data_alert_type_value
PASSED test_flowmeter_deviations_response_schema_constructs
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/enums.py backend/app/schemas/flowmeter.py \
        backend/tests/test_flowmeter/test_flowmeter_checker.py
git commit -m "feat: add FLOWMETER_DEVIATION/INSUFFICIENT_DATA alert types and deviation schemas"
```

---

## Task 2: FlowmeterAlertChecker — pure computation (TDD)

**Files:**
- Create: `backend/app/alerts/flowmeter_checker.py`
- Modify: `backend/tests/test_flowmeter/test_flowmeter_checker.py`

- [ ] **Step 1: Add the full test suite**

Append all 9 domain tests to `backend/tests/test_flowmeter/test_flowmeter_checker.py` (after the smoke tests from Task 1):

```python
# ── FlowmeterAlertChecker unit tests (no DB) ─────────────────────────────────

class TestFlowmeterAlertChecker:
    def setup_method(self):
        from app.alerts.flowmeter_checker import FlowmeterAlertChecker
        self.checker = FlowmeterAlertChecker()

    def test_no_events_yields_insufficient_data(self):
        """Farm with no events → sector has 0 interior events → insufficient_data."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        result = self.checker._compute_from_data(pairs, [])
        assert result.sector_results[0].interior_avg is None
        assert result.crop_averages == {}

    def test_single_event_per_day_excluded(self):
        """Day with 1 event per sector → stripped entirely → insufficient_data."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [15.0])   # 1 event per day
        result = self.checker._compute_from_data(pairs, events)
        assert result.sector_results[0].interior_avg is None

    def test_first_last_stripped_per_day(self):
        """Day with 3 events → only middle event is interior; outlier values ignored."""
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = []
        for d in _days(4):
            # first=5.0 (outlier), middle=15.0 (interior), last=5.0 (outlier)
            events += _day_events("fm1", d, [5.0, 15.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        # 4 interior events each 15.0 → avg = 15.0
        assert result.sector_results[0].interior_avg == pytest.approx(15.0)

    def test_deviation_above_threshold_fires_alert(self):
        """Sector A at 18 m³/ha, sector B at 14 m³/ha → crop avg 16 → A is +12.5%."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 18.0, 5.0])
            events += _day_events("fm2", d, [5.0, 14.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        sector_a = next(a for a in deviation_alerts if a.sector_id == "s1")
        assert sector_a.data["direction"] == "above"
        assert sector_a.data["deviation_pct"] == pytest.approx(12.5)

    def test_deviation_below_threshold_fires_alert(self):
        """Sector B at 14 m³/ha → −12.5% below crop avg 16 → alert direction=below."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 18.0, 5.0])
            events += _day_events("fm2", d, [5.0, 14.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        from app.core.enums import AlertType
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        sector_b = next(a for a in deviation_alerts if a.sector_id == "s2")
        assert sector_b.data["direction"] == "below"
        assert sector_b.data["deviation_pct"] == pytest.approx(-12.5)

    def test_within_threshold_no_deviation_alert(self):
        """Sector at ±3.1% → under threshold → no FLOWMETER_DEVIATION."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
        ]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 16.5, 5.0])
            events += _day_events("fm2", d, [5.0, 15.5, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        assert len(deviation_alerts) == 0

    def test_insufficient_data_alert_fired(self):
        """Sector with only 2 interior events (< MIN=3) → FLOWMETER_INSUFFICIENT_DATA."""
        from app.core.enums import AlertType
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = []
        for d in _days(2):   # 2 days × 1 interior event = 2 interior events
            events += _day_events("fm1", d, [5.0, 15.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        insuf = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_INSUFFICIENT_DATA]
        assert len(insuf) == 1
        assert insuf[0].data["interior_event_count"] == 2

    def test_single_sector_per_crop_no_deviation(self):
        """Only one almond sector → crop_avg == sector_avg → deviation is 0 → no alert."""
        from app.core.enums import AlertType
        pairs = [_make_pair("fm1", "s1", "Setor A", "almond")]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 20.0, 5.0])
        result = self.checker._compute_from_data(pairs, events)
        alerts = self.checker._build_alerts(result, "farm1")
        deviation_alerts = [a for a in alerts if a.alert_type == AlertType.FLOWMETER_DEVIATION]
        assert len(deviation_alerts) == 0

    def test_crop_isolation(self):
        """Almond and olive averages computed independently; olive (1 sector) never deviates."""
        from app.core.enums import AlertType
        pairs = [
            _make_pair("fm1", "s1", "Setor A", "almond"),
            _make_pair("fm2", "s2", "Setor B", "almond"),
            _make_pair("fm3", "s3", "Setor C", "olive"),
        ]
        events = []
        for d in _days(4):
            events += _day_events("fm1", d, [5.0, 20.0, 5.0])   # almond high
            events += _day_events("fm2", d, [5.0, 16.0, 5.0])   # almond low
            events += _day_events("fm3", d, [5.0, 10.0, 5.0])   # olive (sole sector)
        result = self.checker._compute_from_data(pairs, events)
        assert result.crop_averages["almond"] == pytest.approx(18.0)
        assert result.crop_averages["olive"] == pytest.approx(10.0)
        alerts = self.checker._build_alerts(result, "farm1")
        olive_deviations = [
            a for a in alerts
            if a.alert_type == AlertType.FLOWMETER_DEVIATION and a.sector_id == "s3"
        ]
        assert len(olive_deviations) == 0
```

- [ ] **Step 2: Run the tests — confirm all 9 domain tests fail**

```bash
docker compose exec backend pytest tests/test_flowmeter/test_flowmeter_checker.py -v
```

Expected: 3 PASS (smoke tests) + 9 FAIL — `ImportError: cannot import name 'FlowmeterAlertChecker'`

- [ ] **Step 3: Create `backend/app/alerts/flowmeter_checker.py`**

```python
# backend/app/alerts/flowmeter_checker.py
"""Flowmeter deviation alert checker.

Detects sectors whose per-event water consumption deviates more than ±5%
from the crop-average of interior events. Strips the first and last event
per sector per calendar day (system spin-up / wind-down outliers).
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertSeverity, AlertType
from app.models.alert import Alert

logger = logging.getLogger(__name__)

PERIOD_DAYS = 7
DEVIATION_THRESHOLD_PCT = 5.0
MIN_INTERIOR_EVENTS = 3


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class _SectorResult:
    sector_id: str
    sector_name: str
    crop_type: str
    interior_events: list
    interior_avg: float | None   # None when len(interior_events) < MIN_INTERIOR_EVENTS


@dataclass
class _ComputeResult:
    sector_results: list[_SectorResult]
    crop_averages: dict[str, float]   # crop_type → mean interior avg across sectors


# ---------------------------------------------------------------------------
# Alert factory
# ---------------------------------------------------------------------------

def _alert(
    alert_type: AlertType,
    severity: AlertSeverity,
    title_pt: str,
    title_en: str,
    description_pt: str,
    description_en: str,
    farm_id: str,
    sector_id: str,
    data: dict,
) -> Alert:
    return Alert(
        alert_type=alert_type,
        severity=severity,
        title_pt=title_pt,
        title_en=title_en,
        description_pt=description_pt,
        description_en=description_en,
        farm_id=farm_id,
        sector_id=sector_id,
        is_active=True,
        data=data,
    )


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class FlowmeterAlertChecker:
    """Check for flowmeter consumption deviations vs per-crop interior-event averages."""

    # -- Public interface ----------------------------------------------------

    async def check(self, farm_id: str, db: AsyncSession) -> list[Alert]:
        """Compute deviations and return Alert objects. Does NOT write to DB."""
        result = await self._compute(farm_id, db)
        return self._build_alerts(result, farm_id)

    async def compute_deviations(self, farm_id: str, db: AsyncSession):
        """Compute deviations and return a structured response for the frontend."""
        from app.schemas.flowmeter import (
            FlowmeterDeviationSector,
            FlowmeterDeviationsResponse,
            FlowmeterInsufficientDataSector,
        )
        result = await self._compute(farm_id, db)
        deviating = []
        insufficient_data = []

        for sr in result.sector_results:
            if sr.interior_avg is None:
                insufficient_data.append(
                    FlowmeterInsufficientDataSector(
                        sector_id=sr.sector_id,
                        sector_name=sr.sector_name,
                        crop_type=sr.crop_type,
                        interior_event_count=len(sr.interior_events),
                    )
                )
                continue

            crop_avg = result.crop_averages.get(sr.crop_type)
            if not crop_avg:
                continue

            deviation_pct = (sr.interior_avg - crop_avg) / crop_avg * 100
            if abs(deviation_pct) > DEVIATION_THRESHOLD_PCT:
                deviating.append(
                    FlowmeterDeviationSector(
                        sector_id=sr.sector_id,
                        sector_name=sr.sector_name,
                        crop_type=sr.crop_type,
                        direction="above" if deviation_pct > 0 else "below",
                        deviation_pct=round(deviation_pct, 1),
                        sector_avg_m3ha=round(sr.interior_avg, 2),
                        crop_avg_m3ha=round(crop_avg, 2),
                        interior_event_count=len(sr.interior_events),
                    )
                )

        return FlowmeterDeviationsResponse(
            period_days=PERIOD_DAYS,
            deviating=deviating,
            insufficient_data=insufficient_data,
            crop_averages={k: round(v, 2) for k, v in result.crop_averages.items()},
            evaluated_at=datetime.now(UTC),
        )

    # -- Core computation (pure — testable without DB) -----------------------

    def _compute_from_data(self, pairs: list, all_events: list) -> _ComputeResult:
        """Strip outliers, compute interior averages and crop means.

        Args:
            pairs: list of (Flowmeter, Sector) objects (may be mocks in tests).
            all_events: list of IrrigationEventDetected objects for the window.
        """
        # Group events by (flowmeter_id, date)
        events_by_fm_date: dict[tuple, list] = defaultdict(list)
        for ev in all_events:
            events_by_fm_date[(str(ev.flowmeter_id), ev.date)].append(ev)

        # Strip first+last per day → collect interior events per flowmeter
        interior_by_fm: dict[str, list] = defaultdict(list)
        for (fm_id, _day), day_events in events_by_fm_date.items():
            sorted_day = sorted(day_events, key=lambda e: e.start_time)
            if len(sorted_day) >= 2:
                interior_by_fm[fm_id].extend(sorted_day[1:-1])
            # 0 or 1 events → fully excluded (system start/stop with no interior run)

        # Build per-sector results
        sector_results: list[_SectorResult] = []
        for fm, sector in pairs:
            fm_id = str(fm.id)
            interior = interior_by_fm.get(fm_id, [])
            if len(interior) >= MIN_INTERIOR_EVENTS:
                avg: float | None = statistics.mean(ev.total_m3_ha for ev in interior)
            else:
                avg = None
            sector_results.append(
                _SectorResult(
                    sector_id=str(sector.id),
                    sector_name=sector.name,
                    crop_type=sector.crop_type or "unknown",
                    interior_events=interior,
                    interior_avg=avg,
                )
            )

        # Compute per-crop averages from sectors with sufficient data
        crop_avgs_raw: dict[str, list[float]] = defaultdict(list)
        for sr in sector_results:
            if sr.interior_avg is not None:
                crop_avgs_raw[sr.crop_type].append(sr.interior_avg)

        crop_averages = {
            crop: statistics.mean(avgs)
            for crop, avgs in crop_avgs_raw.items()
            if avgs
        }

        return _ComputeResult(sector_results=sector_results, crop_averages=crop_averages)

    # -- Alert builder -------------------------------------------------------

    def _build_alerts(self, result: _ComputeResult, farm_id: str) -> list[Alert]:
        alerts: list[Alert] = []

        for sr in result.sector_results:
            if sr.interior_avg is None:
                alerts.append(
                    _alert(
                        alert_type=AlertType.FLOWMETER_INSUFFICIENT_DATA,
                        severity=AlertSeverity.INFO,
                        title_pt=f"Dados insuficientes: {sr.sector_name}",
                        title_en=f"Insufficient data: {sr.sector_name}",
                        description_pt=(
                            f"{sr.sector_name} tem apenas {len(sr.interior_events)} evento(s) "
                            f"interior(es) nos últimos {PERIOD_DAYS} dias. "
                            f"São necessários pelo menos {MIN_INTERIOR_EVENTS} para avaliação."
                        ),
                        description_en=(
                            f"{sr.sector_name} has only {len(sr.interior_events)} interior "
                            f"event(s) in the last {PERIOD_DAYS} days. "
                            f"At least {MIN_INTERIOR_EVENTS} are required for evaluation."
                        ),
                        farm_id=farm_id,
                        sector_id=sr.sector_id,
                        data={
                            "interior_event_count": len(sr.interior_events),
                            "period_days": PERIOD_DAYS,
                        },
                    )
                )
                continue

            crop_avg = result.crop_averages.get(sr.crop_type)
            if not crop_avg:
                continue   # single sector for this crop — no peer to compare against

            deviation_pct = (sr.interior_avg - crop_avg) / crop_avg * 100
            if abs(deviation_pct) <= DEVIATION_THRESHOLD_PCT:
                continue

            direction = "above" if deviation_pct > 0 else "below"
            direction_pt = "acima" if direction == "above" else "abaixo"

            alerts.append(
                _alert(
                    alert_type=AlertType.FLOWMETER_DEVIATION,
                    severity=AlertSeverity.WARNING,
                    title_pt=f"Desvio de consumo: {sr.sector_name}",
                    title_en=f"Consumption deviation: {sr.sector_name}",
                    description_pt=(
                        f"{sr.sector_name} aplica em média {sr.interior_avg:.1f} m³/ha por evento — "
                        f"{abs(deviation_pct):.1f}% {direction_pt} da média da cultura "
                        f"({crop_avg:.1f} m³/ha)."
                    ),
                    description_en=(
                        f"{sr.sector_name} averages {sr.interior_avg:.1f} m³/ha per event — "
                        f"{abs(deviation_pct):.1f}% {direction} the crop average "
                        f"({crop_avg:.1f} m³/ha)."
                    ),
                    farm_id=farm_id,
                    sector_id=sr.sector_id,
                    data={
                        "deviation_pct": round(deviation_pct, 1),
                        "direction": direction,
                        "sector_avg_m3ha": round(sr.interior_avg, 2),
                        "crop_avg_m3ha": round(crop_avg, 2),
                        "interior_event_count": len(sr.interior_events),
                        "period_days": PERIOD_DAYS,
                    },
                )
            )

        return alerts

    # -- DB loader -----------------------------------------------------------

    async def _compute(self, farm_id: str, db: AsyncSession) -> _ComputeResult:
        from app.models import Flowmeter, IrrigationEventDetected, Plot, Sector

        now = datetime.now(UTC)
        since = now - timedelta(days=PERIOD_DAYS)

        fm_result = await db.execute(
            select(Flowmeter, Sector)
            .join(Sector, Flowmeter.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .where(Plot.farm_id == farm_id, Flowmeter.is_active.is_(True))
        )
        pairs = fm_result.all()
        if not pairs:
            return _ComputeResult(sector_results=[], crop_averages={})

        fm_ids = [str(fm.id) for fm, _ in pairs]
        ev_result = await db.execute(
            select(IrrigationEventDetected)
            .where(
                IrrigationEventDetected.flowmeter_id.in_(fm_ids),
                IrrigationEventDetected.start_time >= since,
            )
            .order_by(IrrigationEventDetected.start_time)
        )
        all_events = ev_result.scalars().all()

        return self._compute_from_data(pairs, all_events)
```

- [ ] **Step 4: Run the tests — all 12 should pass**

```bash
docker compose exec backend pytest tests/test_flowmeter/test_flowmeter_checker.py -v
```

Expected: 12 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/app/alerts/flowmeter_checker.py \
        backend/tests/test_flowmeter/test_flowmeter_checker.py
git commit -m "feat: add FlowmeterAlertChecker with outlier stripping and deviation detection"
```

---

## Task 3: AlertEngine integration

**Files:**
- Modify: `backend/app/alerts/engine.py`

- [ ] **Step 1: Wire the checker into `run_farm_alerts`**

Open `backend/app/alerts/engine.py`. Find `run_farm_alerts`. Insert the flowmeter check block **after the per-sector loop and before `await self.reconcile_alerts(...)`**:

The current code at that point looks like:

```python
        for plot in plots:
            sectors_result = await db.execute(
                select(Sector).where(Sector.plot_id == plot.id)
            )
            for sector in sectors_result.scalars().all():
                try:
                    sector_alerts = await self._run_sector_alerts(sector, farm_id, db)
                    new_alerts.extend(sector_alerts)
                except Exception:
                    logger.exception("Alert check failed for sector %s", sector.id)

        await self.reconcile_alerts(farm_id, new_alerts, db)
```

Change it to:

```python
        for plot in plots:
            sectors_result = await db.execute(
                select(Sector).where(Sector.plot_id == plot.id)
            )
            for sector in sectors_result.scalars().all():
                try:
                    sector_alerts = await self._run_sector_alerts(sector, farm_id, db)
                    new_alerts.extend(sector_alerts)
                except Exception:
                    logger.exception("Alert check failed for sector %s", sector.id)

        # Flowmeter deviation check (per-crop interior-event average comparison)
        try:
            from app.alerts.flowmeter_checker import FlowmeterAlertChecker
            fm_alerts = await FlowmeterAlertChecker().check(farm_id, db)
            new_alerts.extend(fm_alerts)
        except Exception:
            logger.exception("Flowmeter deviation check failed for farm %s", farm_id)

        await self.reconcile_alerts(farm_id, new_alerts, db)
```

- [ ] **Step 2: Run the existing alert engine tests to confirm nothing broke**

```bash
docker compose exec backend pytest tests/ -k "alert" -v --tb=short
```

Expected: all existing alert tests still pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/alerts/engine.py
git commit -m "feat: wire FlowmeterAlertChecker into AlertEngine.run_farm_alerts"
```

---

## Task 4: GET /farms/{farm_id}/flowmeter-deviations endpoint

**Files:**
- Modify: `backend/app/api/v1/flowmeter.py`
- Modify: `backend/tests/test_flowmeter/test_flowmeter_analysis_api.py`

- [ ] **Step 1: Write the failing 404 test**

Open `backend/tests/test_flowmeter/test_flowmeter_analysis_api.py`. Add this test at the end:

```python
async def test_deviations_endpoint_unknown_farm_returns_404(client):
    response = await client.get(
        "/api/v1/farms/00000000-0000-0000-0000-000000000000/flowmeter-deviations"
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run the test — confirm it fails**

```bash
docker compose exec backend pytest tests/test_flowmeter/test_flowmeter_analysis_api.py::test_deviations_endpoint_unknown_farm_returns_404 -v
```

Expected: `FAILED` — 404 but route doesn't exist yet (likely 404 for wrong reason, or 405/422).

- [ ] **Step 3: Add the endpoint and schema imports**

Open `backend/app/api/v1/flowmeter.py`.

**Add to the imports block** (the existing import from `app.schemas.flowmeter` is on lines 17–34). Add the three new schema names:

```python
from app.schemas.flowmeter import (
    CropSummary,
    FlowmeterAnalysisRequest,
    FlowmeterAnalysisResponse,
    FlowmeterAnalysisStatistics,
    FlowmeterCropStats,
    FlowmeterDashboardResponse,
    FlowmeterDeviationsResponse,          # new
    FlowmeterEventsResponse,
    FlowmeterEventsSummary,
    FlowmeterOut,
    FlowmeterReadingPoint,
    FlowmeterReadingsResponse,
    FlowmeterSectorAnalysisResponse,
    FlowmeterSectorDashboard,
    FlowmeterSectorStatistics,
    IrrigationEventOut,
    SectorDailyBreakdown,
)
```

**Append at the very end of the file:**

```python

@router.get("/farms/{farm_id}/flowmeter-deviations", response_model=FlowmeterDeviationsResponse)
async def get_flowmeter_deviations(
    farm_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return per-sector deviation summary vs crop interior-event averages (7-day window).

    Pure computation — no LLM, no cache, no DB writes. Used by the inline
    FlowmeterDeviationWarnings frontend component.
    """
    farm = await db.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(404, detail="Farm not found")

    from app.alerts.flowmeter_checker import FlowmeterAlertChecker
    return await FlowmeterAlertChecker().compute_deviations(farm_id, db)
```

- [ ] **Step 4: Run the test — confirm it passes**

```bash
docker compose exec backend pytest tests/test_flowmeter/test_flowmeter_analysis_api.py -v
```

Expected: all tests in the file pass, including the new 404 test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/flowmeter.py \
        backend/tests/test_flowmeter/test_flowmeter_analysis_api.py
git commit -m "feat: add GET /farms/{farm_id}/flowmeter-deviations endpoint"
```

---

## Task 5: TypeScript types + API client method

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the three new interfaces to `frontend/src/types/index.ts`**

The flowmeter types currently end around line 808 (`FlowmeterSectorAnalysisResponse`). Append after the last flowmeter interface:

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

- [ ] **Step 2: Add the import to `api.ts` and the `deviations` method**

Open `frontend/src/lib/api.ts`.

**In the import block at the top**, add the three new types (the import list already imports other Flowmeter types):

```typescript
import type {
  ...
  FlowmeterDeviationsResponse,      // add this line
  FlowmeterDeviationSector,         // add this line
  FlowmeterInsufficientDataSector,  // add this line
  ...
} from "@/types";
```

**In `flowmeterApi`**, add `deviations` before the closing `};` (after `sectorAnalysis`):

```typescript
  deviations: (farmId: string) =>
    get<FlowmeterDeviationsResponse>(`/farms/${farmId}/flowmeter-deviations`),
```

The final `flowmeterApi` object ends like:

```typescript
  sectorAnalysis: (
    sectorId: string,
    params: { period_days: number; language?: string; force_refresh?: boolean },
  ) => post<FlowmeterSectorAnalysisResponse>(
    `/sectors/${sectorId}/flowmeter-analysis`,
    params,
  ),

  deviations: (farmId: string) =>
    get<FlowmeterDeviationsResponse>(`/farms/${farmId}/flowmeter-deviations`),
};
```

- [ ] **Step 3: Verify TypeScript compiles cleanly**

```bash
docker compose exec frontend npx tsc --noEmit 2>&1 | head -20
```

Expected: no output (zero errors).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/lib/api.ts
git commit -m "feat: add FlowmeterDeviationsResponse types and flowmeterApi.deviations method"
```

---

## Task 6: FlowmeterDeviationWarnings component

**Files:**
- Create: `frontend/src/components/flowmeter/FlowmeterDeviationWarnings.tsx`

- [ ] **Step 1: Create the component**

```typescript
// frontend/src/components/flowmeter/FlowmeterDeviationWarnings.tsx
"use client";

import { useEffect, useState } from "react";
import { flowmeterApi } from "@/lib/api";
import type { FlowmeterDeviationsResponse } from "@/types";

interface Props {
  farmId: string;
}

export function FlowmeterDeviationWarnings({ farmId }: Props) {
  const [data, setData] = useState<FlowmeterDeviationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  const fetchDeviations = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await flowmeterApi.deviations(farmId);
      setData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao carregar desvios");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDeviations();
  }, [farmId]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalIssues = data
    ? data.deviating.length + data.insufficient_data.length
    : 0;

  return (
    <div className="border border-rule-soft rounded-lg overflow-hidden bg-white">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-surface-subtle cursor-pointer select-none"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-2">
          <span className="text-base">⚠️</span>
          <span className="text-sm font-semibold text-ink-1">
            Desvios de Consumo — 7 dias
          </span>
          {!loading && data && totalIssues > 0 && (
            <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium">
              {totalIssues}
            </span>
          )}
        </div>
        <span className="text-ink-3 text-xs">{collapsed ? "▶" : "▼"}</span>
      </div>

      {!collapsed && (
        <div className="px-4 py-3 space-y-2">
          {/* Loading skeleton */}
          {loading && (
            <div className="space-y-2 animate-pulse">
              <div className="h-3 bg-surface-subtle rounded w-4/5" />
              <div className="h-3 bg-surface-subtle rounded w-3/5" />
            </div>
          )}

          {/* Error */}
          {error && !loading && (
            <div className="flex items-center gap-2">
              <p className="text-sm text-terra">{error}</p>
              <button
                onClick={fetchDeviations}
                className="text-xs text-ink-3 hover:text-ink-1 underline"
              >
                Tentar novamente
              </button>
            </div>
          )}

          {/* All OK */}
          {data && !loading && totalIssues === 0 && (
            <p className="text-sm text-green-600 flex items-center gap-1.5">
              <span>✓</span>
              <span>Consumo dentro do normal</span>
            </p>
          )}

          {/* Deviating sectors */}
          {data && !loading && data.deviating.length > 0 && (
            <div className="space-y-1.5">
              {data.deviating.map((s) => (
                <div
                  key={s.sector_id}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="text-ink-2 truncate mr-2">{s.sector_name}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span
                      className={
                        s.direction === "above"
                          ? "text-terra font-medium"
                          : "text-amber-600 font-medium"
                      }
                    >
                      {s.direction === "above" ? "▲ +" : "▼ −"}
                      {Math.abs(s.deviation_pct).toFixed(1)}%
                    </span>
                    <span className="text-ink-4">
                      {s.sector_avg_m3ha.toFixed(1)} m³/ha
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Insufficient data sectors */}
          {data && !loading && data.insufficient_data.length > 0 && (
            <div className="border-t border-rule-soft pt-2 space-y-1">
              <p className="text-xs text-ink-4">Dados insuficientes:</p>
              {data.insufficient_data.map((s) => (
                <div
                  key={s.sector_id}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="text-ink-3 truncate mr-2">{s.sector_name}</span>
                  <span className="text-ink-4 shrink-0">
                    {s.interior_event_count} evento{s.interior_event_count !== 1 ? "s" : ""}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Crop averages footnote + refresh */}
          {data && !loading && (
            <div className="flex items-center justify-between pt-1 border-t border-rule-soft">
              <span className="text-xs text-ink-4">
                {Object.entries(data.crop_averages)
                  .map(
                    ([crop, avg]) =>
                      `${crop === "almond" ? "Amendoal" : crop === "olive" ? "Olival" : crop} ${avg.toFixed(1)} m³/ha`,
                  )
                  .join(" · ")}
              </span>
              <button
                onClick={fetchDeviations}
                className="text-xs text-ink-3 hover:text-ink-1 underline shrink-0 ml-2"
              >
                Atualizar
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles cleanly**

```bash
docker compose exec frontend npx tsc --noEmit 2>&1 | head -20
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/flowmeter/FlowmeterDeviationWarnings.tsx
git commit -m "feat: add FlowmeterDeviationWarnings auto-loading component"
```

---

## Task 7: Wire into FlowmeterDashboard + fix AI analysis margin

**Files:**
- Modify: `frontend/src/components/flowmeter/FlowmeterDashboard.tsx`
- Modify: `frontend/src/components/flowmeter/FlowmeterAIAnalysis.tsx`

- [ ] **Step 1: Remove the outer margin from `FlowmeterAIAnalysis`**

Open `frontend/src/components/flowmeter/FlowmeterAIAnalysis.tsx`. The outermost `<div>` on line 63 currently reads:

```tsx
    <div className="border border-rule-soft rounded-lg mx-4 my-3 overflow-hidden bg-white">
```

Change it to (remove `mx-4 my-3`):

```tsx
    <div className="border border-rule-soft rounded-lg overflow-hidden bg-white">
```

- [ ] **Step 2: Update `FlowmeterDashboard.tsx`**

Open `frontend/src/components/flowmeter/FlowmeterDashboard.tsx`.

**Add the import** after the existing `FlowmeterAIAnalysis` import:

```tsx
import { FlowmeterDeviationWarnings } from "./FlowmeterDeviationWarnings";
```

**Replace the existing AI analysis line** (currently `{/* AI Analysis section — above sector table */}` + `<FlowmeterAIAnalysis farmId={farmId} period={period} />`):

```tsx
      {/* Analysis grid — AI analysis + deviation warnings */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mx-4 my-3">
        <FlowmeterAIAnalysis farmId={farmId} period={period} />
        <FlowmeterDeviationWarnings farmId={farmId} />
      </div>
```

- [ ] **Step 3: Verify TypeScript compiles cleanly**

```bash
docker compose exec frontend npx tsc --noEmit 2>&1 | head -20
```

Expected: no output.

- [ ] **Step 4: Rebuild the frontend container**

```bash
docker compose up -d --build frontend
```

Wait for the build to finish (~60 seconds), then verify:

```bash
docker compose exec frontend sh -c "ls -la .next/server/app/farms/\[farmId\]/caudalimetros/page.js"
```

The file modification time should be today's date.

- [ ] **Step 5: Smoke test in the browser**

Open `http://localhost:3000/farms/<your-farm-id>/caudalimetros`.

Verify:
- "Análise de Consumo" (AI) and "Desvios de Consumo — 7 dias" boxes appear **side-by-side** on a wide screen
- "Desvios de Consumo" shows a loading skeleton then either "Consumo dentro do normal" ✓ or a list of deviating sectors
- The sector table is still below both boxes
- On a narrow screen (DevTools → mobile), both boxes stack vertically

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/flowmeter/FlowmeterDashboard.tsx \
        frontend/src/components/flowmeter/FlowmeterAIAnalysis.tsx
git commit -m "feat: wire FlowmeterDeviationWarnings into dashboard grid layout"
```

---

## Self-Review

**Spec coverage:**
- ✅ Outlier stripping per sector per day (Task 2)
- ✅ Min 3 interior events → FLOWMETER_INSUFFICIENT_DATA (Task 2)
- ✅ ±5% deviation → FLOWMETER_DEVIATION WARNING (Task 2)
- ✅ New AlertType enum values (Task 1)
- ✅ AlertEngine integration (Task 3)
- ✅ GET /flowmeter-deviations endpoint (Task 4)
- ✅ TypeScript types + API client (Task 5)
- ✅ FlowmeterDeviationWarnings component with all states (Task 6)
- ✅ Side-by-side grid layout (Task 7)
- ✅ FlowmeterAIAnalysis outer margin removed (Task 7)
- ✅ 404 test for new endpoint (Task 4)
- ✅ 9 unit tests for checker logic (Task 2)

**No placeholders found.**

**Type consistency:** `FlowmeterDeviationsResponse`, `FlowmeterDeviationSector`, `FlowmeterInsufficientDataSector` — all defined in Task 1 (Python) and Task 5 (TypeScript). Used in Tasks 2, 4, 6 with matching field names. `direction: "above" | "below"` consistent throughout.
