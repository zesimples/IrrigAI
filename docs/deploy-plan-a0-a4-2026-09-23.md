# Production deploy plan — A0–A4 (`05ea921`) + the pending `1aa77d1`

Written 2026-09-23. Companion to
[the independent review](claude-a0-a4-independent-review-2026-09-23.md).

> **Status:** the six blocking defects from the review are **fixed and committed**, and
> the live evaluation passed (28/28) against the fixed validator. The migrations and
> sequence below are unaffected by the fixes — no new migration was added. The review's
> "Important" findings remain open; none of them is a deploy blocker.

---

## What is actually pending

| | |
|---|---|
| Prod code | last deployed `c689981` (2026-08-24 outage fix) |
| Prod schema | last **verified** `1c13f632d1a6` (2026-07-29) — re-confirm before acting |
| Undeployed commits | `1aa77d1` (code-only), `05ea921` (A0–A4), `00b3e86` (docs) |
| Migrations to apply | exactly two: `019a556f37dd`, then `a0d5b179c368` |
| New env vars | **none** |
| Compose / Dockerfile changes | **none** |

The Alembic chain is strictly linear with a single head (verified by reading all
27 revision files), so `alembic upgrade head` applies exactly those two steps:

```
1c13f632d1a6  →  019a556f37dd  →  a0d5b179c368   (head)
```

`1aa77d1` (the `no_candidate` → `not_applicable`/`insufficient_data` split) has been
pending since 2026-07-29 and carries no migration. It is an ancestor of `05ea921`, so
deploying `main` ships it automatically. **If A0–A4 is held, `1aa77d1` can be shipped
on its own** by building that commit specifically — it needs no migration and no
frontend/worker coordination beyond the usual three-service rebuild.

## The runbook is stale — do not follow `docs/runbooks/deploy.md` verbatim

It uses **two** Compose files and assumes the containerised nginx. The current host
runs **systemd Caddy** on 80/443 and needs **three** files, including the
production-local, untracked `docker-compose.caddy.yml`, which is what publishes
`127.0.0.1:8000` and `127.0.0.1:3000` for Caddy to reach. Omitting it removes those
publications and produces **public 502s**. Also: never `--remove-orphans` on this host
(`irrigai_grafana` and `irrigai_prometheus` belong to the deployment), and do not start
the committed Compose nginx/certbot services.

Throughout, `DC` means:

```bash
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.caddy.yml"
```

---

## Pre-checks (before touching anything)

1. **Confirm the real schema head.**
   ```bash
   $DC exec -T backend alembic current
   ```
   Expect `1c13f632d1a6`. Anything else — stop and re-plan; the two-step assumption
   above is what makes this deploy cheap.

2. **Prove the new constraints cannot fail.** Cheap insurance given that
   `37eabad4a828` would have failed on prod for exactly this reason.
   ```sql
   SELECT count(*) FROM chat_message WHERE reply_to_id IS NOT NULL;               -- expect 0 (or column-missing)
   SELECT conversation_id, client_message_id, count(*) FROM chat_message
     WHERE client_message_id IS NOT NULL GROUP BY 1,2 HAVING count(*) > 1;        -- expect 0 rows
   SELECT count(*) FROM chat_message;                                             -- size, for lock planning
   ```

3. **Confirm backup freshness** before a schema change — `BACKUP_DIR/.last_full_verify`
   age, and that the latest archive ends with pg_dump's completion trailer. The
   `db-backup` container still runs the **old inline entrypoint** on this host
   (recorded 2026-09-21), so trust the verified archives, not its log lines.
   `docker stop irrigai-db-backup-1` before `git pull` — the script is bind-mounted and
   bash reads it incrementally.

4. **Check disk headroom.** The 2026-08-24 outage was a full `/`.

5. **Pick the window: NOT 03:50–05:30 UTC.** Monday `probe_calibration` runs 04:00 and
   `daily_recommendations` 05:00. See the lock note below.

---

## Sequence

### 1. Pull
```bash
docker stop irrigai-db-backup-1
git pull origin main
```

### 2. Build all three images first
```bash
$DC build backend worker frontend
```
Build before migrating so a build failure costs nothing.

### 3. Migrate — before swapping any image
```bash
$DC run --rm -e PGOPTIONS="-c lock_timeout=5s" backend alembic upgrade head
```

**Why the lock timeout.** `019a556f37dd` adds
`chat_message.recommendation_id → recommendation`, which takes `ACCESS EXCLUSIVE` on
`chat_message` **and `SHARE ROW EXCLUSIVE` on `recommendation`**. Row validation is
trivial (every value is NULL), but if it lands while the scheduler is writing
`recommendation`, the `ALTER` queues — and because Postgres lock queues are FIFO, every
subsequent write to `recommendation` queues behind it. A 50 ms DDL becomes a multi-minute
write stall. A 5 s timeout turns that into a clean retry instead.

Everything else is safe on a live large table: `chat_action` is a new empty table;
`chat_message.status` uses a PG11+ fast default (metadata-only, no rewrite); the partial
unique index and both unique constraints are over columns that are NULL in every existing
row; nothing touches a hypertable.

**Migrating ahead of the swap is safe** — the currently-running image never writes
`status`, `reply_to_id` or `client_message_id`, so the server defaults and the new CHECK
satisfy its inserts. The reverse is fatal in the now-familiar way: the new image's
`_open_turn` selects `reply_to_id` on **every** chat turn, so code-before-migration
reproduces the `irrigation_fingerprint` outage class — every chat request 500s.

### 4. Swap all three services together
```bash
$DC up -d --no-deps backend worker frontend
```

All three, in one command, for concrete reasons:
- **frontend** sends `client_message_id` and consumes the new SSE / `ProposedActionOut`
  shape. Old frontend + new backend silently loses turn resume; new frontend + old
  backend 500s on unknown fields.
- **worker** carries `active_probes_stmt`, `probe_calibration_service` and
  `recommendation_service` changes and runs the scheduler. A stale worker image has
  bitten this project repeatedly (flowmeter 406; the sweep drain job).

### 5. Verify
```bash
$DC exec -T backend alembic current                      # expect a0d5b179c368
$DC exec -T backend python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://localhost:8000/health')))"
curl -sf https://irrigai.95.111.254.42.nip.io/health
$DC logs --tail=200 worker | grep -i "jobs registered"   # expect 8
```
Then, in the UI: log in; open a sector; send one chat message and confirm the SSE
progress appears *before* the answer (this is what the `no-transform` header fixes, and
its e2e guard is currently unreachable — see the review); check the Boletim and one
recommendation render.

### 6. Watch for 15 minutes
`$DC logs -f backend worker frontend`. Specifically watch for `MultipleResultsFound` from
ingestion — prod has no archived duplicate `external_id`s (the recovery was
development-only), so the `active_probes_stmt` change should be behaviourally inert
there, but that is the assumption most worth falsifying early.

---

## Known cosmetic breakage on deploy

`irrigai_ai_response_feedback_total` changes labels from `["surface","rating"]` to
`["surface","reason","rating"]`. Existing Grafana panels and any recording rules over it
break — old series stop, new series start with no continuity. Cardinality is fine
(`reason` is a 4-value `Literal`). Worth noting in the deploy record; not a blocker.

## Rollback

Both migrations have correct, order-safe `downgrade()` bodies. Downgrading discards the
new columns and the whole `chat_action` table — i.e. any proposed/confirmed action
recorded after the deploy. For a code-only problem, redeploy the previous image and
**leave the schema forward**: the old code ignores the new columns entirely, so there is
no need to downgrade to roll back. See `docs/runbooks/rollback.md`.

## After a successful deploy

- Two one-line `CREATE INDEX CONCURRENTLY` on the new `recommendation_id` FK columns
  (`chat_message`, `chat_action`). Both are `ON DELETE SET NULL` with no index, which
  makes bulk farm-subtree deletes quadratic — and this project does those routinely.
- The five performance indexes from `g7h8i9j0k1l2` are still missing on prod
  (long-standing dev/prod drift); `CREATE INDEX CONCURRENTLY IF NOT EXISTS` any time.
- Recreate the `db-backup` container so it picks up `ops/db-backup.sh` instead of the old
  inline entrypoint.
