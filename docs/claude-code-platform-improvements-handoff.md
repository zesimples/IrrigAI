# Claude Code Handoff: Platform Improvements

## Scope

This change set implements roadmap items 1, 2, 3, 5, and 6 from the July 2026
application review:

1. Production exposure and operational runbook hardening.
2. Canonical phenology stages and consistent archived-record handling.
3. Alert ownership, reconciliation, and shared engine-state improvements.
5. Complete provider/device onboarding and irrigation geometry capture.
6. Immutable probe-calibration history and recommendation outcome tracking.

## Production hardening

- `docker-compose.prod.yml` explicitly resets the development `ports` inherited
  by PostgreSQL, Redis, backend, and frontend. Only nginx publishes host ports in
  the merged production configuration.
- `docs/runbooks/deploy.md` now consistently uses both Compose files, builds the
  backend, worker, and frontend, runs Alembic before replacing services, and
  includes internal and public health checks.
- `docs/runbooks/restore-backup.md` now follows the actual `db-backup` service,
  bind-mounted backup directory, and production Compose commands.

Verify the effective configuration with:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
```

## Phenology and archived records

- Frontend crop-stage contracts now use a stable `key`; translated names are
  display labels rather than API identifiers.
- The onboarding phenology timeline submits the stage key and has a regression
  test covering selection.
- `backend/app/active_records.py` centralizes active farm/plot/sector queries.
- Live scheduler, recommendation pipeline, dashboard, GDD, ingestion,
  calibration, alert, anomaly, AI-context, and flowmeter jobs ignore archived
  hierarchy records.
- Flowmeter rate and deviation queries also filter archived plots and sectors.

Claude Code should preserve this rule: archived records remain available for
historical/reporting views but must not participate in current recommendations,
alerts, ingestion, or scheduled calculations.

## Alert architecture

- Alerts now contain `source` and `rule_key` fields with a reconciliation index.
- Migration `m3n4o5p6q7r8_alert_sources.py` backfills stable ownership metadata.
- Core, anomaly, flowmeter-deviation, and flowmeter-flow-rate producers use
  separate sources and deterministic rule keys.
- Reconciliation only resolves alerts owned by the producer currently running;
  core reconciliation cannot close anomaly or flowmeter alerts.
- Sector core-alert evaluation uses `RecommendationPipeline.run()`, so alerts and
  recommendations share probe selection, calibrated soil bounds, flowmeter water
  accounting, rain applicability, and confidence state.
- `rain_skip_applies` is explicit in the engine result and recommendation input
  snapshot.
- Persistent over-saturation remains an anomaly concern; the old core
  over-irrigation inference is no longer created from a clamped soil state.
- Anomaly detection is scheduled after ingestion.

When adding a new alert producer, give it its own `source` and stable `rule_key`.
Do not reconcile another producer's alerts.

## Onboarding and integrations

The onboarding flow now has five steps and captures:

- Farm latitude/longitude with range and pair validation, plus optional elevation.
- Sector area and optional row spacing.
- Irrigation application rate, emitter flow, and emitter spacing. Drip sectors
  require either a known application rate or enough emitter/row geometry to
  calculate it.
- Encrypted MyIrrigation credentials.
- Provider connection testing/resource discovery without returning secrets.
- Provider project/weather device mappings.
- Probe external ID.
- Flowmeter numeric ID and optional name.
- An explicit configure-later path.

New or expanded API surfaces include:

- `GET/PUT /farms/{farm_id}/credentials`
- `GET /farms/{farm_id}/provider-resources`
- Existing probe creation exposed through the frontend API client.
- `POST /sectors/{sector_id}/flowmeter`

Farm credential responses expose only configuration/status metadata. Do not
return stored passwords, tokens, or client secrets.

## Calibration history

- `ProbeCalibrationRun` is the immutable record of every deterministic
  calibration computation.
- Scheduled calibration creates `candidate` runs only; it does not silently
  change live soil bounds.
- A manual run is computed, recorded, and applied. Applying a candidate marks
  the prior applied history row `superseded` and updates the existing
  `ProbeCalibration` projection used by `resolve_sector_soil_bounds()`.
- Applying a run clears conflicting manual soil customization and is audited.
- History and application endpoints:
  - `GET /sectors/{sector_id}/calibration-runs`
  - `POST /calibration-runs/{run_id}/apply`

Numerical calibration remains deterministic in
`backend/app/engine/auto_calibration.py`; an LLM must not choose FC/refill values.

## Recommendation outcomes

- `RecommendationOutcome` records one deterministic evaluation per accepted
  recommendation.
- The evaluator matches a manual irrigation event, preferring a linked
  recommendation, or a detected flowmeter event within 36 hours.
- It records executed/followed-skip/no-event status, recommended and actual dose,
  absolute/percentage dose error, and optional before/after VWC response.
- Flowmeter volume is converted from m3/ha to millimetres by dividing by 10.
- Evaluation runs after both provider ingestion and flowmeter ingestion.
- Creating a manual irrigation event now verifies that a linked recommendation
  belongs to the same sector and audits the action.
- Outcome endpoint:
  - `GET /sectors/{sector_id}/recommendation-outcomes`

## Database migration

The migration chain added by this work is:

```text
m3n4o5p6q7r8_alert_sources.py
  -> n4o5p6q7r8s9_calibration_outcomes.py
```

Production must run `alembic upgrade head` before restarting the new backend and
worker images. Alembic autogeneration reports no model/schema drift at head.

## Verification completed

- Backend: `618 passed, 10 skipped`.
- Frontend Vitest: `67 passed`.
- Frontend ESLint: no warnings or errors.
- Next.js optimized production build: passed.
- Alembic model/schema check: no new upgrade operations.
- Python compilation: passed.
- Changed-backend unresolved import/name Ruff check: passed.
- `git diff --check`: passed.

The backend suite reports six non-failing runtime warnings involving async mocks
and an asyncpg cancellation path. They do not fail the suite but remain suitable
test-harness cleanup work.

## Production verification after deployment

1. Confirm only nginx publishes host ports.
2. Run `alembic current` and confirm head is `n4o5p6q7r8s9`.
3. Verify `/health`, login, dashboard, and recommendation generation.
4. Complete onboarding once with provider configuration and once with
   configure-later.
5. Trigger a calibration, confirm the run appears in history, and confirm apply
   changes the active projection.
6. Confirm core reconciliation does not resolve anomaly/flowmeter alerts.
7. After ingestion cycles, inspect recommendation outcomes and worker logs.
