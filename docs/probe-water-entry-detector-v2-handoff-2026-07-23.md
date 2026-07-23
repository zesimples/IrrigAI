# Probe-only water-entry detector v2 handoff

Date: 2026-07-23

## Scope

This batch improves the water-entry markers shown on probe charts without using
flowmeters, weather observations, or logged irrigation events as detector
inputs. The detector reports a probable water entry; only user confirmation
classifies it as irrigation or rain.

## Backend

- Replaced adjacent-reading jump detection with cumulative
  local-baseline-to-peak detection per physical depth.
- Added a robust per-depth noise floor, cadence scoring, sustained-response
  filtering, invalid-range filtering, and isolated-spike rejection.
- A clear decline closes a rising episode, and a second rise at the same depth
  starts a second event instead of being merged into the first.
- Responses propagating to different depths within six hours are grouped into
  one profile event.
- Automatic events are always stored as `unlogged`. Source probabilities and
  source-match fields are zero because source attribution is outside the
  probe-only detector.
- Readings from duplicate channels at the same physical depth are combined by
  median. Both `soil_moisture` and legacy `moisture` depth types are supported.
- Ingestion and manual refresh recalculate at least the latest 48 hours, with a
  12-hour pre-roll to establish a baseline. This allows late readings to repair
  previously missed events.
- Active automatic rows are reconciled against the recalculated window.
  Confirmed and rejected events are preserved and suppress a replacement
  automatic marker within two hours.
- Confirm/reject actions now record `confirmed_by`.

## Frontend

- Unclassified markers display `Água +X%` instead of looking like confirmed
  irrigation.
- The section and badges use `Entradas de água detectadas` and
  `Entrada de água`.
- Detail text describes the cumulative increase rather than an adjacent or
  summed jump.
- Both probe surfaces let the user explicitly confirm irrigation, confirm rain,
  or reject a false positive.
- The inline surface now exposes `Reanalisar`; it recalculates the currently
  selected time window.

## Verification

- Backend: `673 passed, 10 skipped`.
- Targeted detector/persistence suite: `8 passed, 1 skipped`.
- Frontend: `85 passed`.
- Frontend lint: clean.
- Frontend production build: clean.
- Ruff checks and formatting for changed backend files: clean.
- `git diff --check`: clean.

## Deployment

No database migration was added. Deploy the backend, worker, and frontend
together so ingestion uses the new detector and both UI surfaces use the new
event semantics. Existing active markers are reconciled the next time each
probe ingests a reading or when a user selects `Reanalisar`.
