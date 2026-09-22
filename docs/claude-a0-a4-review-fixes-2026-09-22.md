# A0–A4 review fixes — 2026-09-22

This supersedes the September 10 implementation checkpoint. Development recovery
was completed separately on September 21; see
[the recovery record](development-recovery-completed-2026-09-21.md).

Status: **implemented, verified, committed and pushed.** Commit
`05ea921 feat(ai): complete A0-A4 grounding and recovery fixes` is on
`origin/main`. The full A4 release/pilot gate remains pending as described below.

## Scope and state

The local review fixes preserve Claude's existing implementation and the recovery
ingestion fix. No commit, push, production access, deployment, or Part B work was
performed. Recovery databases, rehearsal databases, backups and Docker volumes
were preserved. Development is now at `a0d5b179c368`; production remains untouched.
The additive migration was applied only after a table-scoped chat backup and archive
verification.

## Changes

- Chat grounding partitions farm-overview measurements by sector, rejects
  model-supplied foreign farm/sector scope, and checks dose claims against the
  selected engine decision. Prior answers and user amounts do not become current
  measurements. Colon-labelled doses and decimal quantities are checked correctly.
  Separate measurements in one sentence retain their local indicator labels.
  Unknown volume claims and empty answers require repair or fallback.
- Multi-sector evidence selection respects the sector named in the answer; repeated
  tool reads no longer overwrite the evidence registry. Explicit measurement units
  let numeric chat citations match the values actually stated. User-authored field notes
  cannot become measurement citations. Grounding remains a conservative heuristic,
  not a general semantic proof of arbitrary prose.
- Interrupted chat retries reuse a durable user/assistant pair, including when the
  conversation ID was lost or a later unrelated answer already exists. Changed
  text with a reused ID is rejected. Reopen retains validation and contract metadata;
  legacy rows without new metadata remain readable and are treated conservatively.
- Database regressions cover concurrent confirm/confirm and confirm/cancel,
  mutation rollback after result-event failure, and regeneration rollback. Manual
  calibration and chat calibration share precedence, computation history and
  transaction ownership, including clearing custom soil overrides.
- Analysis provenance uses actual canonical inputs. Integration coverage includes
  stable repeated context reads and same-row/same-timestamp input changes during
  generation. The latter cannot be stamped as current. Contract version is `a3.2`.
- Frontend regressions cover delayed history/detail and analysis responses, scope
  navigation, unchanged/changed-text retries, cancellation errors, late action
  responses, failed freshness checks and focus rechecks. SSE EOF without `done`
  remains interrupted.
- A real-browser test through a local Next.js proxy reproduced compressed SSE
  buffering. Adding `Cache-Control: no-cache, no-transform` makes progress visible
  before answer completion. The backend header is asserted by an API regression.
- The opt-in evaluator now covers all six structured surfaces: 20 existing card
  cases plus three synthetic alert/change/effectiveness cases. Five multi-turn
  scenarios check current-turn reads. Degraded responses fail live evaluation;
  missing credentials are skips, not passes. Synthetic model drafts are retained
  in failure output to diagnose validator mistakes without weakening assertions.

## Verification

- Full backend suite with isolated PostgreSQL and Redis: **928 passed, 10 skipped**
  in 181.44 seconds. Five existing asynchronous-mock/connection cleanup warnings.
  After the final metadata/header/evidence edits, the AI, grounded-chat, chat-action
  and manual-calibration suites passed again: **260 passed** in 46.73 seconds.
- Frontend suite: **139 passed** across 20 files. Frontend lint and production
  build (including TypeScript validation) passed.
- Chromium/Next proxy regression: **1 passed**. Uses only a synthetic loopback
  HTTP/SSE server; no real backend writes. The fixture delays answer content by
  1.2 seconds and checks visible progress first, then interrupted retry identity.
- Isolated Alembic `downgrade 019a556f37dd`, `upgrade head`, and `check`: **passed**;
  no model/schema differences. Both review DB URLs point to `irrigai_ai_review_20260921`.
- Targeted Ruff checks passed with the repository's existing FastAPI `B008`
  convention excluded. Whole changed-file checks also exclude pre-existing `B007`
  ingestion loop variables. `git diff --check` passed.
- Initial full backend run had 900 passes and 27 Redis-related failures/errors
  because the AI-only runner intentionally used unavailable Redis. A separate
  disposable Redis resolved those environment failures; development Redis was
  never used for these tests.
- First live run: **26 passed, 2 failed**. The second: **27 passed, 1 failed**.
  All 23 card cases passed in both runs. Multi-turn failures exposed unverified
  user-amount repetition and indicator-matching false positives. These failures
  are preserved as findings, not described as successful model evaluations.
- A subsequent five-case chat diagnostic run passed four cases and rejected a
  quoted unverified field-note quantity. The repair prompt was tightened to remove
  unverified note amounts even when the model is explaining why the note is unreliable.
- Final bounded live chat run after those fixes: **5 passed** in 20.14 seconds,
  with no skipped or degraded cases. Combined coverage is 23 passing card cases
  from the preceding full evaluation and five passing final multi-turn scenarios;
  this was not a single final 28-case run. The earlier failures remain documented
  above, and live-model output remains non-deterministic.

## Reproduce safely

Use `backend/scripts/run_isolated_review.py` inside a Compose one-off with the
current backend source mounted. It overrides and verifies **both** database URLs
before importing the application, forces mock ingestion providers, and pins Redis
to `irrigai-review-redis-20260921`. Ordinary `pytest` mode also forces a mock LLM.
`live-eval` explicitly opts into the 28 fixture cases; `live-eval chat` runs only
the five multi-turn cases. See [evaluation commands](../backend/tests/ai_eval/README.md).

Do not run the normal pytest cleanup, seed, or migration commands with inherited
development URLs. Do not rerun recovery. The review DB remains disposable and
contains synthetic seeded fixtures, not restored farm telemetry.
The disposable review Redis was stopped and auto-removed after verification;
recreate it with the documented command before running the guarded test suites.

Browser command, from `frontend`:

```bash
npx playwright test --config playwright.chat-review.config.ts
```

This profile starts its own fixture on loopback port 8101 and Next.js on 3101,
refuses existing servers, and uses no production credentials or data.
The ordinary Playwright configuration excludes this fixture-specific test and
still discovers its eight existing application tests. The required Chromium browser
was installed; no package or lockfile dependency changes were made.

## Release checks still outside this local verification

A4's full foundation release gate is not established by deterministic tests alone.
It still needs representative grower/agronomist review and a farm pilot, plus SSE
verification through the actual production Caddy topology after an authorized
deployment. The local proxy test does not establish production proxy behaviour.
Review and commit the batch before deployment; production must run the additive
migration before serving the updated backend. Existing three-file Caddy deployment
rules still apply.

## Development schema alignment completed — 2026-09-22

Before applying the migration, local development was verified at `019a556f37dd`.
The chat tables contained 4 conversations, 9 messages and 3 actions. A valid custom
format archive was written to
`backups/recovery-preserved-20260922/chat-before-a0d5b179c368.dump`, mode 0600,
SHA-256 `14224551dc1038d53c526a77b202e154c84ce7bb5d23a49602b1de196d22c11e`, and
read successfully with `pg_restore --file=/dev/null`. The migration then completed
transactionally. Development now reports `a0d5b179c368`, both `reply_to_id` and
`response_metadata` exist, and the three chat row counts remain unchanged. Existing
rows have null values for the new columns, as expected for backward compatibility.
The backend's in-container health check reports database and Redis `ok`; no service
restart was needed. Keep this backup with the recovery-preserved archives.

## Next-session handoff

The user asked to preserve this state for the next session. Start by reading this
document and `AGENTS.md`. The focused A0–A4 commit is already pushed; do not create
a duplicate commit. Local development is at `a0d5b179c368`, while production was
not accessed or deployed. Recovery databases, rehearsal databases, protected
backups and the untracked recovery scripts remain preserved. Intentional untracked
files include `AGENTS.md`, recovery tooling, design handoff material and older
planning documents; they were excluded from the A0–A4 commit.

Verified results to carry forward: full backend `928 passed, 10 skipped`; final
targeted backend `260 passed`; frontend `139 passed`; frontend lint/build passed;
browser SSE proxy test passed; isolated Alembic downgrade/upgrade/check passed;
23 card evaluations passed and the final five-case multi-turn evaluation passed.

The next authorized work is review of the pushed batch and preparation for a
separate production deployment/pilot. Production migration and deployment still
require the documented three-file Caddy procedure and must not be inferred from
the local development migration. Do not rerun recovery, seed against development,
or start Part B.
