# Production deploy plan — A0–A4 + review fixes

Revised 2026-09-23 after checking every step against the repository's actual Compose
files, Dockerfiles, Alembic environment and migration code, and rehearsing the
migration on the disposable review database. Companion to
[the independent review](claude-a0-a4-independent-review-2026-09-23.md) and
[the A4 completion report](a4-completion-report-2026-09-23.md).

**Nothing in this plan has been run against production.** It requires explicit
approval for each operation listed in [Approvals required](#approvals-required).

## Corrections to the first version of this plan

The first version (same day) had two defects that would have mattered:

1. **It stopped `db-backup` and never restarted it.** The service is
   `restart: unless-stopped`, so a manual stop keeps it down until someone starts it
   again — production would have silently stopped taking backups, the failure class
   behind the 2026-08-24 outage. Step 8 now restarts and verifies it.
2. **It said production's backup container still ran the old inline entrypoint.**
   That observation came from the *development* recovery record (2026-09-21).
   Production received `ops/db-backup.sh` on 2026-08-24 (`9a29a92`, `c689981`,
   deployed and verified). Step 1 checks it instead of assuming either way.

It also lacked a working rollback: images are rebuilt under the same tag, so "redeploy
the previous image" had nothing to point at. Step 3 now tags them first.

## What is being deployed

| | |
|---|---|
| Target code | `origin/main` at the commit named in the completion report |
| Schema, last verified on prod | `1c13f632d1a6` (2026-07-29) — **re-check in step 1** |
| Migrations to apply | `019a556f37dd`, then `a0d5b179c368` (linear chain, single head) |
| New env vars / Compose / Dockerfile changes | none |
| Services rebuilt | `backend`, `worker`, `frontend` (swapped together) |

**Which application code production is running is not known.** The source checkout
includes `1aa77d1` (it is an ancestor of `c689981`, deployed 2026-08-24), but that
deploy changed only `docker-compose.yml` and `ops/`, so the backend/worker/frontend
*images* may predate it. Step 1 records what each running image actually contains.

## Verified locally before writing this (review DB `irrigai_ai_review_20260921`)

| Claim the plan relies on | Evidence |
|---|---|
| `PGOPTIONS` reaches the Alembic session | Alembic uses `DATABASE_URL_SYNC` (psycopg2/libpq). Through `docker compose run -e PGOPTIONS="-c lock_timeout=5s"`, `current_setting('lock_timeout')` = `5s` |
| A lock conflict fails fast and leaves no partial schema | Downgraded to `1c13f632d1a6`, held `ROW EXCLUSIVE` on `recommendation` (what scheduler writes take), ran the upgrade: `LockNotAvailable: canceling statement due to lock timeout` after ~5 s; revision still `1c13f632d1a6`, `chat_action` absent |
| The upgrade itself is fast | After releasing the lock: both migrations in 1.4 s including container start; `alembic check`: no new operations |
| **Migrate-before-swap is safe** | Production's current code (`c689981`) run against the migrated schema: **762 passed, 10 skipped, 0 failed** — the old image works during the window |
| The reverse is unsafe | The new code selects `chat_message.reply_to_id` on every chat turn |

## Conventions

Run from the production checkout, with `.env` loaded (`set -a; . ./.env; set +a`) so
`$POSTGRES_USER`/`$POSTGRES_DB` resolve. Every command uses all three Compose files:

```bash
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.caddy.yml"
```

Never start the committed nginx/certbot services, never use `--remove-orphans`
(`irrigai_grafana` and `irrigai_prometheus` belong to this deployment), and never
omit `docker-compose.caddy.yml` (it publishes `127.0.0.1:8000` and `:3000` for
systemd Caddy — without it the public site returns 502).

**Window:** not 03:50–05:30 UTC (Monday calibration 04:00, daily recommendations 05:00),
and not while `db-backup` is mid-dump (step 1 checks).

---

## 1. Read-only checks — stop on any unexpected answer

```bash
git status --short && git log --oneline -1          # clean checkout, known commit
$DC ps                                              # all services up; note monitoring containers
$DC exec -T backend alembic current                 # expect 1c13f632d1a6
df -h / && docker system df                         # headroom, see below
```

Record what the running images contain, so rollback and the stale "is `1aa77d1`
deployed?" question are answered from fact:

```bash
for s in backend worker frontend; do
  echo "$s $($DC images -q $s) $(docker inspect -f '{{.Created}}' $($DC images -q $s))"
done
$DC exec -T backend grep -c not_applicable app/services/probe_calibration_service.py   # 1 ⇒ 1aa77d1 running, 0 ⇒ older
$DC exec -T worker  grep -c not_applicable app/services/probe_calibration_service.py   # the worker image separately
```

Backup service and last verified backup:

```bash
$DC exec -T db-backup head -3 /usr/local/bin/db-backup.sh     # the script, not an inline entrypoint
$DC logs --tail=30 db-backup                                  # sleeping between cycles, not mid-dump
ls -lt backups/ | head -5                                     # newest archive and its age
cat backups/.last_full_verify                                  # last full restore-verification
```

**Disk:** stop if `/` has less than **10 GB** free. Basis: three image rebuilds need a
few GB, the step-2 chat dump is small, and `db-backup` is stopped for the window so its
~20 GB restore-verification cannot run concurrently. Its own floor
(`BACKUP_MIN_FREE_MB=20480`) must still hold after the deploy for the next cycle.

Code markers above were checked against Git: each one discriminates the commit it
names (the first draft grepped a file that never contains the marker).

**Constraint pre-checks** (read-only; they prove the new constraints cannot fail):

```sql
SELECT count(*) FROM chat_message;                                   -- lock-planning size
SELECT column_name FROM information_schema.columns
 WHERE table_name='chat_message' AND column_name IN ('reply_to_id','status','client_message_id');
                                                                    -- expect 0 rows
```

## 2. Backup the tables the migration touches

The migrations alter `chat_message` and `ai_response_feedback` and create
`chat_action`; a downgrade discards new columns and `chat_action`. A table-scoped dump
is small, fast, and exactly covers that:

```bash
$DC stop db-backup                     # after confirming it is sleeping (step 1)
# $POSTGRES_USER / $POSTGRES_DB come from .env (see Conventions)
$DC exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  -t chat_conversation -t chat_message -t ai_response_feedback \
  > backups/pre-a0a4-chat-$(date -u +%Y%m%dT%H%MZ).dump
sha256sum backups/pre-a0a4-chat-*.dump
$DC exec -T db pg_restore --list < backups/pre-a0a4-chat-*.dump | head   # readable
```

The newest daily full archive (step 1) is the whole-database fallback; record its name
and its `.last_full_verify` date in the deploy record.

## 3. Tag the running images for rollback

```bash
for s in backend worker frontend; do
  docker tag "$($DC images -q $s)" "irrigai-rollback/$s:pre-a0a4"
done
```

## 4. Pull and build — nothing is swapped yet

```bash
git pull origin main
$DC build backend worker frontend
```

A build failure here costs nothing: the old containers are still serving.

## 5. Migrate, before any image swap

```bash
$DC run --rm -e PGOPTIONS="-c lock_timeout=5s" backend alembic upgrade head
$DC exec -T backend alembic current      # still the OLD container: expect a0d5b179c368
```

If it fails with `LockNotAvailable`, nothing changed (rehearsed above). Wait and
re-run; do not raise the timeout — a long wait is what blocks the recommendation table.

## 6. Swap all three together

```bash
$DC up -d --no-deps backend worker frontend
```

Together, because the new frontend sends `client_message_id` and reads the new SSE and
`ProposedActionOut` shapes, and the worker carries the ingestion (`active_probes_stmt`)
and calibration changes and runs the scheduler.

## 7. Verify

```bash
$DC ps                                                        # all healthy; monitoring still up
curl -sf http://127.0.0.1:8000/health                         # db ok, redis ok
curl -sfo /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/login
curl -sf https://irrigai.95.111.254.42.nip.io/health          # through Caddy
$DC logs --tail=200 worker | grep "jobs registered"           # expect 8
$DC exec -T backend grep -c _NEGATION_BRIDGE_RE app/ai/chat_grounding.py   # 2 ⇒ new code (0 in 05ea921)
$DC exec -T worker  grep -c _NEGATION_BRIDGE_RE app/ai/chat_grounding.py
$DC logs --since=10m backend worker | grep -iE "error|MultipleResultsFound|Traceback"
```

`MultipleResultsFound` is the assumption most worth falsifying early: production has no
archived duplicate provider IDs (the recovery was development-only), so the
`active_probes_stmt` change should be inert there.

**Caddy streaming** — the check no local test can stand in for. Inspect the site block
for `encode` and `reverse_proxy` options:

```bash
sudo caddy adapt --config /etc/caddy/Caddyfile 2>/dev/null | head -60 || sudo cat /etc/caddy/Caddyfile
```

Then, in a browser on the public URL, open a sector, ask one question, and record
from DevTools → Network the `chat/stream` timing: the first `progress` event must
arrive well before `done`. Repeat with `curl -N` and a real session token, timestamping
each event line. One question costs one bounded model call and writes one
conversation owned by the testing user; no farm data changes.

## 8. Restore the backup service — do not skip

```bash
$DC start db-backup
$DC ps db-backup                      # running
$DC logs --tail=20 db-backup          # started a cycle, or sleeping until the next
```

## 9. Watch for 15 minutes, then write the deploy record

Record: commit, image IDs before and after, `alembic current`, dump name + SHA-256,
health outputs, worker job count, Caddy timings, and any errors seen.

## Rollback

- **Code only** (the usual case): the old code runs on the new schema (762/0 above), so
  **do not downgrade**. Re-point each service at its rollback tag, then recreate:
  ```bash
  for s in backend worker frontend; do
    docker tag "irrigai-rollback/$s:pre-a0a4" "$(docker inspect -f '{{index .RepoTags 0}}' "$($DC images -q $s)")"
  done
  $DC up -d --no-deps backend worker frontend
  ```
- **Schema** (only if the migration itself is at fault): `alembic downgrade 1c13f632d1a6`
  discards the new columns and the whole `chat_action` table; restore from the step-2 dump
  if chat history must be recovered. Both `downgrade()` bodies were verified to reverse
  their upgrades on the review database.
- Either way, `$DC start db-backup` if it is stopped.

## Known cosmetic breakage

`irrigai_ai_response_feedback_total` gains a `reason` label; existing Grafana panels on it
lose continuity. Low cardinality (4 values). Not a blocker.

## After a successful deploy

- `CREATE INDEX CONCURRENTLY` on the two new `recommendation_id` columns
  (`chat_message`, `chat_action`) — `ON DELETE SET NULL` with no index makes bulk
  farm-subtree deletes quadratic.
- The five `g7h8i9j0k1l2` performance indexes are still missing on prod (known drift).
- Update `docs/runbooks/deploy.md`, which still describes two Compose files and nginx.

## Approvals required

Each of these is a separate production operation, none authorised yet:

1. **Read-only inspection** — step 1 and the Caddyfile read.
2. **Backup-service stop + chat-table dump** — step 2.
3. **Image tag, pull and build** — steps 3–4 (no service change).
4. **Production migration** — step 5.
5. **Service swap** — step 6, then 7–8.
6. **Public streaming check** — one real chat question from a test account (step 7).
