# Deploy record — A0–A4 to production, 2026-09-25

Executed from [the deploy plan](deploy-plan-a0-a4-2026-09-23.md). This machine has no SSH
access to the host, so the user ran every command on the host and pasted the output back;
everything below is taken from that output.

**Result: deployed and verified at 11:18 UTC.** Production runs `origin/main` `1ef69de` at
schema `a0d5b179c368`. The 15-minute post-deploy watch (plan step 9) was handed to the user
and its output had not come back when this record was written.

## Timeline (UTC)

| Time | Step |
|---|---|
| 09-24 15:12 | `docker builder prune -f` reclaimed 26.8 GB (19 → 44 GB free); backup cycle forced |
| 09-24 16:09 | `irrigai_20260924_151238.sql.gz` (9.1 GB) written; **16:53 full restore verified, farm_count=4** |
| 09-25 09:19 | Step 1 read-only checks — all as expected (below) |
| 09:26 | Step 2: `db-backup` stopped; chat-table dump taken |
| 09:27 | Step 3: rollback tags; step 4: pull `910e5d2` and build |
| 09:33 | **Step 5 failed before touching the database** — `ModuleNotFoundError: No module named 'psycopg'` in `alembic upgrade head`. The guard chain stopped before the swap; nothing changed. `db-backup` restarted (09:34 cycle) |
| ~09:50 | `irrigai-*:latest` tags pointed back at the running images, so no accidental `up` could start the broken build |
| 10:00 | Fix `1ef69de` pushed (dependency pins, below) |
| 10:33 | `irrigai_20260925_093436.sql.gz` (9.2 GB) written — the pre-migration backup |
| 11:16 | Deploy script: backup gate passed, `db-backup` stopped, pull `1ef69de`, build, **pins identical** |
| 11:18 | Migration `1c13f632d1a6 → 019a556f37dd → a0d5b179c368`; swap of all three services |
| 11:19 | Verification passed; `db-backup` restarted (post-migration cycle) |

## Step 1 findings

- Checkout `c689981`, clean apart from the untracked `backups/` and `docker-compose.caddy.yml`.
- Schema `1c13f632d1a6`; 34 GB free.
- **`1aa77d1` was already deployed**: the 2026-07-29 backend and worker images both contain
  `not_applicable`. CLAUDE.md's "PENDING DEPLOY" note was stale and is corrected.
- `chat_message` had **0 rows** — chat had never been used in production — and none of the new
  columns existed.
- The backup service runs `ops/db-backup.sh` (not the old inline entrypoint).

## The dependency failure, and the fix

`pyproject.toml` declares only lower bounds and the Dockerfile had no lock, so an image's
contents depended on the Docker build cache. Pruning it (to free disk for backups) made the
build resolve today's newest packages. Old vs new backend image:

| Package | Running (2026-07-29) | Cold build (2026-09-25) |
|---|---|---|
| SQLAlchemy | 2.0.51 | **2.1.0** — default `postgresql://` driver becomes psycopg 3 |
| openai | 2.45.0 | **3.19.2** (major) |
| fastapi / starlette | 0.139.0 / 1.3.1 | 0.141.1 / 1.7.0 |
| cryptography | 49.0.0 | 50.0.1 |
| websockets | 16.1 | 17.1 |

Plus new transitive packages (`httpx2`, `httpcore2`, `truststore`). The SQLAlchemy change
broke Alembic; the others would have shipped untested.

**Fix (`1ef69de`):** `backend/constraints.txt` pins the runtime set to production's own
2026-07-29 image (58 packages) plus the dev/test tools, and both Dockerfile installs use
`-c constraints.txt`. `tests/test_dependency_pins.py` fails if a declared dependency is
unpinned, if SQLAlchemy leaves 2.0.x, or if either install is unconstrained (confirmed red on
the old and on a half-fixed Dockerfile).

Verified locally before pushing (deterministic suites only; no live eval):
- the pinned production-target image's `pip freeze` equals the production set exactly;
  default driver resolves to psycopg2;
- full backend suite on the pinned development image through `run_isolated_review`
  (isolated review DB + Redis): **997 passed, 10 skipped, 0 failed**;
- `alembic current` on the pinned production image against the review DB: `a0d5b179c368`.

On the host, the deploy script diffed both new images' `pip freeze` against the running set
before migrating: **identical**.

## Artefacts

| | |
|---|---|
| Code | `1ef69de` |
| Schema | `a0d5b179c368` |
| Full backup, pre-migration | `backups/irrigai_20260925_093436.sql.gz` (9.2 GB, integrity-checked) |
| Last full restore verification | `backups/irrigai_20260924_151238.sql.gz`, 2026-09-24 16:53, farm_count=4 |
| Chat-table dump | `backups/pre-a0a4-chat-20260925T0926Z.dump`, 9,554 bytes, SHA-256 `a34c8b92e0bf668e0a7186a794cfd27bcfe7bf828510010ec60c740d00ec32ec` |
| Rollback tags | `irrigai-rollback/{backend,worker,frontend}:pre-a0a4` — keep a few days |

| Service | Before | After |
|---|---|---|
| backend | `4879b7f6c48c` | `c3f72cfbd6b1` |
| worker | `7525b926353e` | `ea791c1d459a` |
| frontend | `e74afe8aa18e` | `76b67cf9da24` |

## Verification (11:19)

- backend and worker `healthy`; Grafana and Prometheus still up.
- `/health`: `db ok, redis ok`; `/login` 200; public `/api/v1/farms` 401 (Caddy → frontend → backend).
- Worker: `Scheduler started: 8 jobs registered`.
- `_NEGATION_BRIDGE_RE` present in backend and worker (2 each — the reviewed fix).
- **Worker `DEBUG=false`** — the `132bcb5` fix is live; the startup security guard now covers
  the worker (it passed: `ENCRYPTION_KEY` and a non-placeholder `SECRET_KEY` are set).
- No `error`/`Traceback`/`MultipleResultsFound` in backend or worker logs for the first minutes.

**Caddy streaming — static only.** The Caddyfile is `reverse_proxy 127.0.0.1:3000` with no
`encode` directive, on Caddy 2.11.2; all traffic goes through the Next frontend, whose streaming
behaviour with the backend's `Cache-Control: no-cache, no-transform` / `X-Accel-Buffering: no`
headers is covered by the CI browser test. **The public timing proof remains open**: it needs one
real chat question (~US$0.001), excluded by the current no-API-spend constraint.

## Open after this deploy

1. **Disk.** 22 GB free after the deploy; the post-migration dump running at 11:19 takes ~9 GB,
   leaving ~13 GB, below the 20 GB the next cycle needs — so the 2026-09-26 cycle will likely
   skip its dump but prune the 2026-09-18 archive, and the one after should run. `docker builder
   prune -f` after the dump reclaims today's build cache. The real fix — TimescaleDB compression,
   a bigger disk, or off-host backups — is still open, as is Alertmanager.
2. The 15-minute watch output (plan step 9).
3. Public Caddy streaming timing (needs one real question).
4. Post-deploy indexes: `CREATE INDEX CONCURRENTLY` on `chat_message.recommendation_id` and
   `chat_action.recommendation_id`; the five missing `g7h8i9j0k1l2` performance indexes.
5. `docs/runbooks/deploy.md` still describes two Compose files and nginx.
6. A4 gate: human review (agronomist + 2 growers) and the pilot.

## Development incident during this session

While writing the pin test, Claude Code ran one pytest file inside the development `backend`
container. The autouse `isolate_committed_db_rows` fixture in `backend/tests/conftest.py` runs
its `DELETE`s against `settings.DATABASE_URL` before every test, and in that container the URL
is the development database — so at 09:46:52 UTC it emptied `recommendation`,
`recommendation_reason`, `recommendation_outcome`, `detected_water_event`, `irrigation_event`,
`alert`, `sector_override`, `irrigation_event_detected`, `flowmeter_reading`,
`provider_ingestion_run`, `provider_sync_log` and `weather_forecast` in development. This broke
a standing rule in CLAUDE.md. Production was not involved.

**Restored (user-approved):** the verified dev backup `backups/irrigai_20260924_125607.sql.gz`
was loaded into a scratch database `irrigai_restore_20260925` (same schema head and farm/sector
counts as development); a dry run computed inside the scratch DB predicted every insert; then,
with the dev worker stopped, one transaction in `irrigai` (checking `current_database()` and
asserting the exact counts) merged the rows with `ON CONFLICT DO NOTHING` — forecasts only for
days not already present. Inserted: 2,834 recommendations, 11,490 reasons, 3 irrigation events,
83,553 alerts, 98,137 flowmeter readings, 222,589 ingestion runs, 2,486 water events, 2,236
detected irrigation events, 155 forecasts, 6 sync logs — all exactly as predicted. No water event
in the backup carried a human confirmation, and no chat row had a recommendation link, so
keeping the rows re-created since the wipe lost nothing. **Unrecoverable:** anything written in
development between 2026-09-24 12:56 and 2026-09-25 09:46 (mainly the 09-25 05:00
recommendations). The scratch database is kept until the user says to drop it.

Every pytest run must now point both database URLs away from development — even for a test that
never touches the database. The suite run for the fix above used `run_isolated_review`.
