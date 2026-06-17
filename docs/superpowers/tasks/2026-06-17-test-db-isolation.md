# Task: Isolate the test database from the dev database

**Status:** Queued (not started)
**Filed:** 2026-06-17

## Problem

The backend test suite runs against the **same Postgres the dev app uses** (the one
serving `localhost:3000`), and tests that `commit()` farms/plots/sectors/users are never
cleaned up — so they accumulate permanently. A fresh dev DB drifted to **72 farms** (3
real + ~7 scenario fixtures + ~56 `Farm-<uuid>` API-test artifacts) purely from test runs
over time, cluttering the dashboard.

## Evidence

- `backend/tests/conftest.py:46` and `:92` — engines are built from
  `settings.DATABASE_URL`, i.e. the dev DB. There is no separate test database.
- `backend/tests/conftest.py:56` `isolate_committed_db_rows` autouse fixture cleans only
  a fixed list of transactional tables (`_TEST_CLEANUP_STATEMENTS`), and the comment at
  `:79` states explicitly: *"The autouse cleanup above never deletes
  farm/plot/sector/probe/probe_depth/user."*
- Net effect: any test that commits a `Farm` (e.g. API tests creating `Farm-<uuid>`, and
  the `Seed Fixture Farm` at `:112`) leaves rows behind in the dev DB.

## Fix options

1. **Dedicated test database (recommended).** Point the test config at a separate DB
   (e.g. `TEST_DATABASE_URL`, or a pytest-session-scoped throwaway schema/database created
   and dropped around the run). Cleanest: keeps the dev DB pristine, enables parallel test
   runs, and doesn't risk deleting real/seed rows.
2. **Transaction-per-test rollback.** Wrap each test in an outer transaction/savepoint that
   always rolls back, so even committed rows vanish at test end. Works but fights ORM
   `commit()` calls inside code under test (need the SQLAlchemy "join an external
   transaction" pattern).
3. **Extend cleanup to farms/plots/sectors/users.** Lowest effort but fragile — hard to
   distinguish test-created rows from seed rows; risks wiping seed data.

## Acceptance criteria

- Running the full backend suite leaves the dev DB's `farm` (and plot/sector/probe/user)
  row counts **unchanged**.
- `localhost:3000` continues to show only the seeded farms after a test run.
- CI (which already uses mock providers) still passes.

## Notes

- Until this is fixed, **running the test suite re-pollutes the dev DB.** Reset with
  `make down-v && make dev` then `make migrate && make seed` to get back to the 3 seed farms.
- Related: `make lint` currently fails on a pre-existing unused `uuid.UUID` import in
  `backend/app/engine/types.py:9` — worth folding into a test/lint hygiene pass.
