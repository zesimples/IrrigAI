# Flowmeter Production Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 production-readiness issues in the flowmeter feature — migration cleanliness, event detection correctness, frontend/backend alignment, and cache/API correctness.

**Architecture:** Changes span backend (migration, ingestion service, API, cache) and frontend (two components). Each task is self-contained. Item 7 (deviation alignment) is already done in commit `f911960`.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), Next.js/TypeScript (frontend), Redis (cache), Alembic (migrations), pytest (tests)

---

## Files Changed

| File | Change |
|------|--------|
| `backend/alembic/versions/78fc0a618be2_add_flowmeter_tables.py` | Task 1 — strip unrelated ops, add missing indexes |
| `backend/app/services/flowmeter_ingestion.py` | Tasks 2 & 3 — windowed detection, duration + gap splitting |
| `backend/tests/test_flowmeter/test_event_detector.py` | Task 3 — new tests for duration and gap split |
| `frontend/src/components/flowmeter/FlowmeterSectorDetail.tsx` | Task 4 — pass since/until to events API |
| `frontend/src/components/flowmeter/FlowmeterDashboard.tsx` | Task 5 — fix "sondas" → "caudalímetros" wording |
| `frontend/src/components/flowmeter/FlowmeterSectorTable.tsx` | Task 5 — fix "Diagnóstico de sondas" link text |
| `frontend/src/components/flowmeter/FlowmeterAIAnalysis.tsx` | Task 6 — fix misleading AI copy |
| `backend/app/services/flowmeter_cache.py` | Task 7 — add language to cache key |
| `backend/tests/test_flowmeter/test_flowmeter_analysis_api.py` | Task 7 — add cache key language test |
| `backend/app/api/v1/flowmeter.py` | Task 8 — add since < until validation |

---

## Task 1: Clean the Alembic migration

**Files:**
- Modify: `backend/alembic/versions/78fc0a618be2_add_flowmeter_tables.py`

The migration currently contains unrelated `drop_index`, `alter_column` statements for alert, probe, recommendation, weather, and irrigation_event tables. These were auto-generated noise. The downgrade is equally polluted.

- [ ] **Step 1: Read the migration and identify non-flowmeter operations**

The following lines in `upgrade()` are NOT flowmeter-related and must be removed:
```
op.drop_index(op.f('ix_alert_is_active'), table_name='alert')
op.alter_column('irrigation_event', 'source', ...)
op.drop_index(op.f('ix_irrigation_event_sector_start'), ...)
op.alter_column('probe', 'external_id', ...)
op.alter_column('probe_depth', 'sensor_type', ...)
op.alter_column('probe_depth', 'data_status', ...)
op.alter_column('probe_reading', 'unit', ...)
op.drop_index(op.f('probe_reading_timestamp_idx'), ...)
op.drop_index(op.f('ix_provider_ingestion_run_started_at'), ...)
op.alter_column('recommendation', 'suggested_start_time', ...)
op.drop_index(op.f('ix_recommendation_generated_at'), ...)
op.alter_column('sector', 'auto_calibration_dismissed_until', ...)
op.alter_column('sector', 'current_phenological_stage', ...)
op.alter_column('sector_crop_profile', 'source_template_id', ...)
op.alter_column('sector_override', 'value', ...)
op.alter_column('sector_override', 'valid_until', ...)
op.drop_index(op.f('ix_weather_forecast_farm_date'), ...)
op.drop_index(op.f('ix_weather_obs_farm_timestamp'), ...)
```

- [ ] **Step 2: Replace the migration with the clean version**

Replace the entire file content with:

```python
"""add flowmeter tables

Revision ID: 78fc0a618be2
Revises: l2m3n4o5p6q7
Create Date: 2026-05-22 11:38:54.744596

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '78fc0a618be2'
down_revision: Union[str, None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- flowmeter device table --
    op.create_table(
        'flowmeter',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('sector_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('external_device_id', sa.Integer(), nullable=False),
        sa.Column('serial_number', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_reading_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['sector_id'], ['sector.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_flowmeter_sector_id'), 'flowmeter', ['sector_id'], unique=False)
    op.create_index(op.f('ix_flowmeter_external_device_id'), 'flowmeter', ['external_device_id'], unique=False)

    # -- readings time-series table --
    op.create_table(
        'flowmeter_reading',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('flowmeter_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('value_m3_ha', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['flowmeter_id'], ['flowmeter.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('flowmeter_id', 'timestamp', name='uq_flowmeter_reading_device_ts'),
    )
    # Composite index for the most common query: readings for a flowmeter in a time window
    op.create_index('ix_flowmeter_reading_fm_ts', 'flowmeter_reading', ['flowmeter_id', 'timestamp'], unique=False)

    # Convert to TimescaleDB hypertable (same pattern as probe_reading migration)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                ALTER TABLE flowmeter_reading DROP CONSTRAINT flowmeter_reading_pkey;
                ALTER TABLE flowmeter_reading ADD PRIMARY KEY (id, timestamp);
                PERFORM create_hypertable(
                    'flowmeter_reading', 'timestamp',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            END IF;
        END $$;
    """)

    # -- detected irrigation events table --
    op.create_table(
        'irrigation_event_detected',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('flowmeter_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('sector_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Float(), nullable=False),
        sa.Column('total_m3_ha', sa.Float(), nullable=False),
        sa.Column('peak_m3_ha', sa.Float(), nullable=False),
        sa.Column('num_readings', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['flowmeter_id'], ['flowmeter.id']),
        sa.ForeignKeyConstraint(['sector_id'], ['sector.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('flowmeter_id', 'start_time', name='uq_irrigation_event_detected_device_start'),
    )
    op.create_index(op.f('ix_irrigation_event_detected_date'), 'irrigation_event_detected', ['date'], unique=False)
    # Query by flowmeter in a time window
    op.create_index('ix_irrigation_event_detected_fm_start', 'irrigation_event_detected', ['flowmeter_id', 'start_time'], unique=False)
    # Query by sector in a time window (used by dashboard and detail views)
    op.create_index('ix_irrigation_event_detected_sector_start', 'irrigation_event_detected', ['sector_id', 'start_time'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_irrigation_event_detected_sector_start', table_name='irrigation_event_detected')
    op.drop_index('ix_irrigation_event_detected_fm_start', table_name='irrigation_event_detected')
    op.drop_index(op.f('ix_irrigation_event_detected_date'), table_name='irrigation_event_detected')
    op.drop_table('irrigation_event_detected')

    op.drop_index('ix_flowmeter_reading_fm_ts', table_name='flowmeter_reading')
    op.drop_table('flowmeter_reading')

    op.drop_index(op.f('ix_flowmeter_external_device_id'), table_name='flowmeter')
    op.drop_index(op.f('ix_flowmeter_sector_id'), table_name='flowmeter')
    op.drop_table('flowmeter')
```

Note: The old single-column `ix_flowmeter_reading_flowmeter_id` index is replaced by the composite `ix_flowmeter_reading_fm_ts`. The old single-column flowmeter_id/sector_id indexes on `irrigation_event_detected` are replaced by composite indexes with start_time.

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/78fc0a618be2_add_flowmeter_tables.py
git commit -m "fix(migration): strip unrelated ops from flowmeter migration, add composite indexes"
```

---

## Task 2: Make event detection incremental (bounded window)

**Files:**
- Modify: `backend/app/services/flowmeter_ingestion.py`

Currently `_detect_and_store_events` loads ALL historical readings every ingestion cycle. This doesn't scale. The fix: only scan a bounded window around new data. If no new readings were inserted, skip detection entirely (the ON CONFLICT DO NOTHING idempotency already handles replays).

- [ ] **Step 1: Update `_detect_and_store_events` to accept a bounded window and skip when nothing new**

In `FlowmeterIngestionService`, replace `_detect_and_store_events` and its call site. The method now receives `inserted_count` and only runs if `inserted_count > 0`. When it does run, it queries only `[window_since, window_until]` instead of all history.

Add this constant near the top of the file (after the existing constants):
```python
# How far back from the earliest new reading to extend the detection window.
# Must cover at least one full irrigation event that may have started before
# the ingestion window.
_EVENT_DETECTION_LOOKBACK_HOURS = 24
```

Replace `_detect_and_store_events`:
```python
async def _detect_and_store_events(
    self,
    flowmeter: "Flowmeter",
    earliest_new_ts: datetime,
    latest_new_ts: datetime,
    db: AsyncSession,
) -> int:
    """Run event detection over a bounded window around new data.

    Scans [earliest_new_ts - 24h, latest_new_ts + 1h] so that:
    - Events that started before the ingestion window are captured.
    - The +1h buffer ensures the tail of the last event is included.
    ON CONFLICT DO NOTHING keeps this idempotent.
    """
    import uuid

    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models import FlowmeterReading, IrrigationEventDetected

    window_since = earliest_new_ts - timedelta(hours=_EVENT_DETECTION_LOOKBACK_HOURS)
    window_until = latest_new_ts + timedelta(hours=1)

    rows_result = await db.execute(
        select(FlowmeterReading)
        .where(
            FlowmeterReading.flowmeter_id == flowmeter.id,
            FlowmeterReading.timestamp >= window_since,
            FlowmeterReading.timestamp <= window_until,
        )
        .order_by(FlowmeterReading.timestamp)
    )
    raw_readings = [(r.timestamp, r.value_m3_ha) for r in rows_result.scalars().all()]
    if not raw_readings:
        return 0

    detector = IrrigationEventDetector()
    events = detector.detect_events(raw_readings)

    added = 0
    for ev in events:
        stmt = (
            pg_insert(IrrigationEventDetected)
            .values(
                id=str(uuid.uuid4()),
                flowmeter_id=flowmeter.id,
                sector_id=flowmeter.sector_id,
                start_time=ev.start_time,
                end_time=ev.end_time,
                duration_minutes=ev.duration_minutes,
                total_m3_ha=ev.total_m3_ha,
                peak_m3_ha=ev.peak_m3_ha,
                num_readings=ev.num_readings,
                date=ev.start_time.date(),
            )
            .on_conflict_do_nothing(
                constraint="uq_irrigation_event_detected_device_start"
            )
        )
        result = await db.execute(stmt)
        added += result.rowcount if result.rowcount >= 0 else 1

    return added
```

- [ ] **Step 2: Update the call site in `ingest_farm` to only call detection when new readings exist**

Replace this block in `ingest_farm`:
```python
                inserted = await self.ingest_device(flowmeter, since, now, adapter, db)
                total_inserted += inserted
                # Always run event detection — even if no new readings were inserted this
                # cycle, there may be stored readings that haven't been processed into events yet
                # (e.g. after a restart). ON CONFLICT DO NOTHING keeps this idempotent.
                events_added = await self._detect_and_store_events(flowmeter, since, now, db)
                total_events += events_added
```

With:
```python
                inserted, earliest_ts, latest_ts = await self.ingest_device(
                    flowmeter, since, now, adapter, db
                )
                total_inserted += inserted
                if inserted > 0 and earliest_ts is not None and latest_ts is not None:
                    events_added = await self._detect_and_store_events(
                        flowmeter, earliest_ts, latest_ts, db
                    )
                    total_events += events_added
```

- [ ] **Step 3: Update `ingest_device` to return `(inserted, earliest_ts, latest_ts)`**

Change the signature and return type of `ingest_device`:

```python
async def ingest_device(
    self,
    flowmeter: "Flowmeter",
    since: datetime,
    until: datetime,
    adapter: "MyIrrigationAdapter",
    db: AsyncSession,
) -> tuple[int, datetime | None, datetime | None]:
    """Fetch readings for one flowmeter and bulk-insert with deduplication.

    Returns (inserted_count, earliest_timestamp, latest_timestamp).
    earliest/latest are from the API response, not the DB — they bound the
    detection window in _detect_and_store_events.
    """
```

And update the `return` statements:
```python
        # Early return: API returned no data
        if not readings:
            return 0, None, None

        # ... (existing rows/stmt logic unchanged) ...

        latest_ts = max(ts for ts, _ in readings)
        earliest_ts = min(ts for ts, _ in readings)
        flowmeter.last_reading_at = latest_ts

        logger.debug(
            "FlowmeterIngestion device %s: %d/%d readings inserted",
            flowmeter.external_device_id, inserted, len(rows),
        )
        return inserted, earliest_ts, latest_ts
```

Also update the early-return on API call failure:
```python
        except Exception:
            logger.exception(
                "FlowmeterIngestion: API call failed for device %s", flowmeter.external_device_id
            )
            return 0, None, None
```

- [ ] **Step 4: Add a public `backfill_events` method for historical reprocessing**

After `_detect_and_store_events`, add:
```python
async def backfill_events(self, flowmeter_id: str, db: AsyncSession) -> int:
    """Reprocess ALL historical readings for a flowmeter. One-off tool, not called by ingest_farm.

    Use this after migrating data or fixing the event detector logic.
    """
    from sqlalchemy import select
    import uuid
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models import FlowmeterReading, IrrigationEventDetected, Flowmeter

    flowmeter_result = await db.execute(
        select(Flowmeter).where(Flowmeter.id == flowmeter_id)
    )
    flowmeter = flowmeter_result.scalar_one_or_none()
    if flowmeter is None:
        raise ValueError(f"Flowmeter {flowmeter_id} not found")

    rows_result = await db.execute(
        select(FlowmeterReading)
        .where(FlowmeterReading.flowmeter_id == flowmeter_id)
        .order_by(FlowmeterReading.timestamp)
    )
    raw_readings = [(r.timestamp, r.value_m3_ha) for r in rows_result.scalars().all()]
    if not raw_readings:
        return 0

    detector = IrrigationEventDetector()
    events = detector.detect_events(raw_readings)

    added = 0
    for ev in events:
        stmt = (
            pg_insert(IrrigationEventDetected)
            .values(
                id=str(uuid.uuid4()),
                flowmeter_id=flowmeter.id,
                sector_id=flowmeter.sector_id,
                start_time=ev.start_time,
                end_time=ev.end_time,
                duration_minutes=ev.duration_minutes,
                total_m3_ha=ev.total_m3_ha,
                peak_m3_ha=ev.peak_m3_ha,
                num_readings=ev.num_readings,
                date=ev.start_time.date(),
            )
            .on_conflict_do_nothing(constraint="uq_irrigation_event_detected_device_start")
        )
        result = await db.execute(stmt)
        added += result.rowcount if result.rowcount >= 0 else 1

    await db.commit()
    logger.info("backfill_events flowmeter=%s: %d events upserted", flowmeter_id, added)
    return added
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/flowmeter_ingestion.py
git commit -m "fix(ingestion): make event detection incremental — skip when no new readings, scan bounded window"
```

---

## Task 3: Fix event duration and gap-based event splitting

**Files:**
- Modify: `backend/app/services/flowmeter_ingestion.py` (IrrigationEventDetector class)
- Modify: `backend/tests/test_flowmeter/test_event_detector.py`

### Problems to fix

1. **Duration undercounts**: `end_time - start_time` for two 15-min readings gives 15 min, but actual irrigation was 30 min (each bucket covers 15 min). Fix: add one inferred interval to duration.
2. **Gap merging**: positive readings separated by a large gap (e.g. 2 hours) are merged into one event. Fix: split when gap > `inferred_interval × 2.5`.

- [ ] **Step 1: Write failing tests for duration and gap split**

Add to `backend/tests/test_flowmeter/test_event_detector.py`:

```python
def test_single_reading_duration_includes_interval():
    # A single 15-min bucket: duration should be 15 min (the bucket width), not 0.
    readings = _make_readings([0, 0, 2.5, 2.5, 0])  # 2 readings at t=30, t=45
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1
    # 15-min gap between readings + 1 interval = 15 + 15 = 30 min
    assert events[0].duration_minutes == 30.0


def test_two_readings_duration_includes_last_interval():
    # t=0, t=15, t=30 — readings at indices 0,1,2 → start=0, end=30
    # duration = (30 - 0) + 15 = 45 min
    readings = [(_ts(0), 2.0), (_ts(15), 3.0), (_ts(30), 2.5)]
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1
    assert events[0].duration_minutes == 45.0


def test_event_splits_across_large_gap():
    # readings at t=0, t=15, t=30, then gap to t=120, t=135
    # gap of 90 min > 15 * 2.5 = 37.5 min → should produce 2 events
    readings = [
        (_ts(0), 2.0), (_ts(15), 3.0), (_ts(30), 2.5),
        (_ts(120), 1.8), (_ts(135), 2.1),
    ]
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 2
    assert events[0].num_readings == 3
    assert events[1].num_readings == 2


def test_small_gap_does_not_split_event():
    # gap of 30 min = 2 × 15-min interval — at threshold, should NOT split (> 2.5 × required)
    readings = [
        (_ts(0), 2.0), (_ts(15), 3.0),
        (_ts(45), 1.8), (_ts(60), 2.1),
    ]
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1


def test_below_minimum_consumption_no_event():
    # total consumption below threshold — with threshold=0.5, values of 0.3 produce no event
    readings = _make_readings([0, 0.3, 0.3, 0.3, 0])
    events = IrrigationEventDetector().detect_events(readings, threshold_m3_ha=0.5)
    assert len(events) == 0
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
cd /path/to/repo/backend
pytest tests/test_flowmeter/test_event_detector.py::test_single_reading_duration_includes_interval tests/test_flowmeter/test_event_detector.py::test_two_readings_duration_includes_last_interval tests/test_flowmeter/test_event_detector.py::test_event_splits_across_large_gap -v
```

Expected: FAIL (duration and split logic not yet implemented)

- [ ] **Step 3: Rewrite `IrrigationEventDetector` with interval inference, correct duration, and gap splitting**

Replace the entire `IrrigationEventDetector` class:

```python
# ---------------------------------------------------------------------------
# Event detection constants
# ---------------------------------------------------------------------------

#: Default reading interval when it cannot be inferred from the data.
_DEFAULT_INTERVAL_MINUTES: float = 15.0

#: Split an event when the gap between two consecutive positive readings
#: exceeds this multiple of the inferred interval.
_GAP_SPLIT_FACTOR: float = 2.5


def _infer_interval_minutes(readings: list[tuple[datetime, float]]) -> float:
    """Infer the median reading interval from a sorted list of (timestamp, value) pairs.

    Returns _DEFAULT_INTERVAL_MINUTES if fewer than 2 readings or inference fails.
    """
    if len(readings) < 2:
        return _DEFAULT_INTERVAL_MINUTES
    gaps = [
        (readings[i + 1][0] - readings[i][0]).total_seconds() / 60
        for i in range(len(readings) - 1)
        if (readings[i + 1][0] - readings[i][0]).total_seconds() > 0
    ]
    if not gaps:
        return _DEFAULT_INTERVAL_MINUTES
    gaps.sort()
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 == 1 else (gaps[mid - 1] + gaps[mid]) / 2


class IrrigationEventDetector:
    """Detect irrigation events from flowmeter time-series data.

    Duration correction: each bucket covers one interval period, so the last
    bucket's interval is added to (end_time - start_time).

    Gap splitting: if consecutive positive readings are separated by more than
    _GAP_SPLIT_FACTOR × inferred_interval, they belong to different events.
    """

    def detect_events(
        self,
        readings: list[tuple[datetime, float]],
        threshold_m3_ha: float = 0.5,
    ) -> list[DetectedEvent]:
        sorted_readings = sorted(readings, key=lambda x: x[0])
        interval_minutes = _infer_interval_minutes(sorted_readings)
        gap_threshold_minutes = interval_minutes * _GAP_SPLIT_FACTOR

        events: list[DetectedEvent] = []
        current_segment: list[tuple[datetime, float]] = []

        for ts, value in sorted_readings:
            if value > threshold_m3_ha:
                if current_segment:
                    # Check if gap from last positive reading exceeds split threshold
                    last_ts = current_segment[-1][0]
                    gap_minutes = (ts - last_ts).total_seconds() / 60
                    if gap_minutes > gap_threshold_minutes:
                        # Close current segment as an event
                        if len(current_segment) >= 2:
                            events.append(self._build_event(current_segment, interval_minutes))
                        current_segment = []
                current_segment.append((ts, value))
            else:
                if current_segment:
                    if len(current_segment) >= 2:
                        events.append(self._build_event(current_segment, interval_minutes))
                    current_segment = []

        # Close event still open at end of data
        if len(current_segment) >= 2:
            events.append(self._build_event(current_segment, interval_minutes))

        return events

    def _build_event(
        self,
        readings: list[tuple[datetime, float]],
        interval_minutes: float,
    ) -> DetectedEvent:
        start_time = readings[0][0]
        end_time = readings[-1][0]
        # Include the last bucket's time slice in the duration
        duration_minutes = (end_time - start_time).total_seconds() / 60.0 + interval_minutes
        total_m3_ha = sum(v for _, v in readings)
        peak_m3_ha = max(v for _, v in readings)
        return DetectedEvent(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            total_m3_ha=round(total_m3_ha, 4),
            peak_m3_ha=peak_m3_ha,
            num_readings=len(readings),
        )
```

- [ ] **Step 4: Check existing tests still pass with the new implementation**

The existing test `test_duration_is_correct` expects 75.0 min for 6 readings at 15-min steps (start=t+15 to t+90). After the fix:
- span = (t+90) - (t+15) = 75 min
- + interval = 75 + 15 = 90 min

That test's assertion (`== 75.0`) will now fail because the duration formula changed. **Update that test** to reflect the correct semantics:

```python
def test_duration_is_correct():
    # 6 readings at 15-min intervals: t+15 to t+90
    # span = 75 min; + 1 interval = 90 min total
    readings = _make_readings([0, 1.5, 2.0, 2.0, 2.0, 2.0, 1.5, 0])
    events = IrrigationEventDetector().detect_events(readings)
    assert len(events) == 1
    assert events[0].duration_minutes == 90.0
```

Also update `test_detect_single_event` which asserts `e.end_time == _ts(105)` but doesn't test duration — no change needed there.

- [ ] **Step 5: Run all event detector tests**

```bash
cd backend
pytest tests/test_flowmeter/test_event_detector.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/flowmeter_ingestion.py backend/tests/test_flowmeter/test_event_detector.py
git commit -m "fix(detector): correct event duration (add last bucket interval), split on large gaps"
```

---

## Task 4: Align frontend period with backend event queries

**Files:**
- Modify: `frontend/src/components/flowmeter/FlowmeterSectorDetail.tsx`

`FlowmeterSectorDetail` passes an `interval` param to `readings` but calls `events()` with no date params, so events always default to the last 7 days regardless of the selected period.

The backend `/events` endpoint already supports `since` and `until` query params and the frontend `flowmeterApi.events()` already accepts them. This task just passes the right dates.

- [ ] **Step 1: Add a helper to compute since/until for a period**

In `FlowmeterSectorDetail.tsx`, add this helper before the component:

```typescript
function periodToSinceUntil(period: "7d" | "30d" | "season"): { since: string; until: string } {
  const until = new Date();
  const since = new Date(until);
  if (period === "7d") {
    since.setDate(since.getDate() - 7);
  } else if (period === "30d") {
    since.setDate(since.getDate() - 30);
  } else {
    // season: 90 days, matching backend default
    since.setDate(since.getDate() - 90);
  }
  return {
    since: since.toISOString(),
    until: until.toISOString(),
  };
}
```

- [ ] **Step 2: Use the helper in the useEffect and depend on `period` instead of `interval`**

Replace the `useEffect` block:

```typescript
  useEffect(() => {
    setLoading(true);
    const { since, until } = periodToSinceUntil(period);
    Promise.all([
      flowmeterApi.readings(sectorId, { interval, since, until }),
      flowmeterApi.events(sectorId, { since, until }),
    ])
      .then(([r, e]) => {
        setReadings(r.readings);
        setEvents(e.events);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [sectorId, period, interval]);
```

- [ ] **Step 3: Run frontend typecheck**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "FlowmeterSectorDetail|error TS"
```

Expected: no output (no errors)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/flowmeter/FlowmeterSectorDetail.tsx
git commit -m "fix(frontend): pass since/until to flowmeter events API based on selected period"
```

---

## Task 5: Fix "sondas" wording — replace with flowmeter-specific copy

**Files:**
- Modify: `frontend/src/components/flowmeter/FlowmeterDashboard.tsx`
- Modify: `frontend/src/components/flowmeter/FlowmeterSectorTable.tsx`

Two places still say "sondas" (probes) instead of "caudalímetros" (flowmeters).

- [ ] **Step 1: Fix FlowmeterDashboard.tsx — two occurrences**

**Occurrence 1** (inline sentence in hero paragraph, line ~117):
```typescript
{stats.semDados > 0 && `; ${stats.semDados} sonda${stats.semDados !== 1 ? 's' : ''} sem dados`}.
```
Replace with:
```typescript
{stats.semDados > 0 && `; ${stats.semDados} caudalímetro${stats.semDados !== 1 ? 's' : ''} sem dados`}.
```

**Occurrence 2** (KPI strip label, line ~188):
```typescript
{ k: 'Sondas sem dados', v: String(stats.semDados), u: `de ${data.sectors.length}`, sub: 'verificar comunicação', tint: '#c9a34a', bar: undefined },
```
Replace with:
```typescript
{ k: 'Caudalímetros sem dados', v: String(stats.semDados), u: `de ${data.sectors.length}`, sub: 'verificar comunicação', tint: '#c9a34a', bar: undefined },
```

- [ ] **Step 2: Fix FlowmeterSectorTable.tsx — below-table diagnostic link**

Find:
```typescript
              <a style={{ color: '#5a5048', textDecoration: 'none', fontStyle: 'normal', fontFamily: 'var(--font-dm-sans, system-ui)', fontSize: 13 }}>
                Diagnóstico de sondas ↗
              </a>
```
Replace with:
```typescript
              <a style={{ color: '#5a5048', textDecoration: 'none', fontStyle: 'normal', fontFamily: 'var(--font-dm-sans, system-ui)', fontSize: 13 }}>
                Diagnóstico de caudalímetros ↗
              </a>
```

- [ ] **Step 3: Verify no other occurrences remain**

```bash
grep -rn "sonda" frontend/src/components/flowmeter/ --include="*.tsx"
```

Expected: only `FlowmeterSectorTable.tsx` line ~324 with "Diagnóstico de caudalímetros" (which you just fixed) — confirm no remaining "sonda" strings.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/flowmeter/FlowmeterDashboard.tsx frontend/src/components/flowmeter/FlowmeterSectorTable.tsx
git commit -m "fix(copy): replace 'sondas' with 'caudalímetros' in flowmeter dashboard and table"
```

---

## Task 6: Fix AI copy — align UI description with what the backend actually does

**Files:**
- Modify: `frontend/src/components/flowmeter/FlowmeterAIAnalysis.tsx`

The current UI says:
> "Posso analisar este consumo cruzando com o défice hídrico e a meteo da semana."

The backend prompt (`flowmeter_prompts.py`) explicitly says the LLM must use **ONLY flowmeter data** and must NOT mention probes, soil moisture, or recommendations. The UI is misleading users about what the AI does.

The preferred fix (per the spec) is to update the UI copy to accurately describe what the AI actually analyzes.

- [ ] **Step 1: Update the pre-analysis prompt text in FlowmeterAIAnalysis.tsx**

Find:
```typescript
          <p style={{
            margin: 0,
            fontFamily: 'var(--font-fraunces)',
            fontSize: 17,
            fontWeight: 500,
            color: '#2a2520',
            letterSpacing: '-0.01em',
            lineHeight: 1.4,
          }}>
            Posso analisar este consumo cruzando com o défice hídrico e a meteo da semana.{' '}
            <em style={{ fontFamily: 'var(--font-instrument)', color: '#5a5048', fontStyle: 'italic' }}>
              Demora cerca de 30 segundos.
            </em>
          </p>
```

Replace the text content (keep all style props unchanged):
```typescript
          <p style={{
            margin: 0,
            fontFamily: 'var(--font-fraunces)',
            fontSize: 17,
            fontWeight: 500,
            color: '#2a2520',
            letterSpacing: '-0.01em',
            lineHeight: 1.4,
          }}>
            Posso analisar os padrões de consumo dos caudalímetros — eventos de rega, dotações por setor e desvios entre culturas.{' '}
            <em style={{ fontFamily: 'var(--font-instrument)', color: '#5a5048', fontStyle: 'italic' }}>
              Demora cerca de 30 segundos.
            </em>
          </p>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/flowmeter/FlowmeterAIAnalysis.tsx
git commit -m "fix(copy): correct AI analysis description — flowmeter patterns only, not weather/soil"
```

---

## Task 7: Fix AI cache key — add language parameter

**Files:**
- Modify: `backend/app/services/flowmeter_cache.py`
- Modify: `backend/tests/test_flowmeter/test_flowmeter_analysis_api.py`

Cache key is currently `flowmeter_analysis:{scope}:{id}:{period_days}`. If a user triggers an analysis in Portuguese then one in English (or vice versa), the second call returns the cached text from the first language. Fix: add `language` to the key.

- [ ] **Step 1: Write a failing test for cache key language isolation**

Open `backend/tests/test_flowmeter/test_flowmeter_analysis_api.py` and read its current contents, then append:

```python
import pytest
from app.services.flowmeter_cache import _make_cache_key


def test_cache_key_includes_language():
    key_pt = _make_cache_key("farm", "abc123", 7, "pt")
    key_en = _make_cache_key("farm", "abc123", 7, "en")
    assert key_pt != key_en


def test_cache_key_format():
    key = _make_cache_key("sector", "xyz", 30, "pt")
    assert "sector" in key
    assert "xyz" in key
    assert "30" in key
    assert "pt" in key
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/test_flowmeter/test_flowmeter_analysis_api.py::test_cache_key_includes_language -v
```

Expected: FAIL — `_make_cache_key` does not exist yet.

- [ ] **Step 3: Refactor flowmeter_cache.py to extract `_make_cache_key` and add `language`**

Replace `flowmeter_cache.py` with:

```python
# backend/app/services/flowmeter_cache.py
"""Redis-backed cache for flowmeter AI analysis text.

Caches only the AI text string (not the statistics, which are computed fresh
from DB on every request).

Cache key: flowmeter_analysis:{scope}:{id}:{period_days}:{language}
TTL: 7200 s (2 hours). Errors are logged and silently ignored — the endpoint
falls back to a live LLM call if Redis is unavailable.
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

CACHE_TTL = 7200  # 2 hours

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    return _redis


def _make_cache_key(scope: str, entity_id: str, period_days: int, language: str) -> str:
    """Build a deterministic cache key. All four dimensions must match for a cache hit."""
    return f"flowmeter_analysis:{scope}:{entity_id}:{period_days}:{language}"


async def get_analysis_cache(scope: str, entity_id: str, period_days: int, language: str = "pt") -> str | None:
    """Return cached AI text, or None if missing/expired/error."""
    try:
        r = _get_redis()
        key = _make_cache_key(scope, entity_id, period_days, language)
        return await r.get(key)
    except Exception:
        logger.warning("Redis get failed for flowmeter_analysis cache — skipping cache", exc_info=True)
        return None


async def set_analysis_cache(scope: str, entity_id: str, period_days: int, language: str = "pt", value: str = "") -> None:
    """Store AI text in Redis with TTL. Silent on error."""
    try:
        r = _get_redis()
        key = _make_cache_key(scope, entity_id, period_days, language)
        await r.set(key, value, ex=CACHE_TTL)
    except Exception:
        logger.warning("Redis set failed for flowmeter_analysis cache — continuing without cache", exc_info=True)
```

- [ ] **Step 4: Update all callers of `get_analysis_cache` / `set_analysis_cache` to pass `language`**

Find callers:
```bash
grep -rn "get_analysis_cache\|set_analysis_cache" backend/app/ --include="*.py"
```

For each caller, ensure `language=` is passed. They should already have a `language` variable from the request params — just add it. Example pattern:

```python
cached = await get_analysis_cache(scope, entity_id, period_days, language=language)
# ...
await set_analysis_cache(scope, entity_id, period_days, language=language, value=analysis_text)
```

- [ ] **Step 5: Run the cache key tests**

```bash
cd backend && pytest tests/test_flowmeter/test_flowmeter_analysis_api.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/flowmeter_cache.py backend/tests/test_flowmeter/test_flowmeter_analysis_api.py
# Also add any caller files updated in step 4
git commit -m "fix(cache): add language to flowmeter analysis cache key to prevent language collision"
```

---

## Task 8: Add API validation — since < until

**Files:**
- Modify: `backend/app/api/v1/flowmeter.py`

The readings and events endpoints accept `since` and `until` but don't validate that `since < until`. An inverted range returns an empty result with no error, which is confusing.

- [ ] **Step 1: Add a shared validation helper at the top of flowmeter.py**

After the imports section, add:

```python
def _validate_date_range(since: datetime, until: datetime) -> None:
    """Raise HTTPException 400 if since >= until."""
    if since >= until:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date range: 'since' ({since.isoformat()}) must be before 'until' ({until.isoformat()})",
        )
```

- [ ] **Step 2: Call the validator in `get_flowmeter_readings`**

In `get_flowmeter_readings`, after the tz-normalization block (after `if until.tzinfo is None`), add:

```python
    _validate_date_range(since, until)
```

- [ ] **Step 3: Call the validator in `get_flowmeter_events`**

Same pattern — after tz-normalization in `get_flowmeter_events`, add:

```python
    _validate_date_range(since, until)
```

- [ ] **Step 4: Run existing flowmeter API tests to confirm no regressions**

```bash
cd backend && pytest tests/test_api/test_flowmeter_api.py tests/test_flowmeter/ -v 2>&1 | tail -20
```

Expected: all existing tests PASS (the new validation only fires when since >= until, which existing tests don't trigger)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/flowmeter.py
git commit -m "fix(api): validate since < until for flowmeter readings and events endpoints, return 400 on invalid range"
```

---

## Final: Run all flowmeter tests

- [ ] **Run full backend flowmeter test suite**

```bash
cd backend && pytest tests/test_flowmeter/ tests/test_api/test_flowmeter_api.py -v 2>&1
```

Expected: all PASS

- [ ] **Run frontend typecheck**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "error TS"
```

Expected: no output

---

## Notes

- **Item 7 (deviation alignment)** is already done — committed as `f911960`. `FlowmeterSectorTable` now fetches server-side deviations from `flowmeterApi.deviations()` instead of computing them client-side from `total_m3_ha`.
- **Task 2 + Task 3** both modify `flowmeter_ingestion.py`. Execute Task 2 first (incremental window), then Task 3 (detector class rewrite) in the same file. Commit each separately.
- **Backfill risk**: After Task 3, existing events in the DB were computed with the old (undercounting) duration. A one-off `backfill_events()` call per flowmeter will reprocess them — but the unique constraint on `(flowmeter_id, start_time)` means existing events won't be re-inserted, only new ones (which won't exist if start_times match). To fix duration of _existing_ events, a separate DB migration updating `duration_minutes` would be needed — out of scope for this plan.
