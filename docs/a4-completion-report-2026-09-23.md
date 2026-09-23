# A4 completion report — 2026-09-23

**Gate status: NOT PASSED.** Everything that can be done locally is done and evidenced
below. Three things remain and none of them can be done from here:

1. **Production migration, deployment and Caddy streaming check** — needs your approval
   for specific production operations ([listed at the end](#approvals-requested)).
2. **Human review by an agronomist and growers** — the [review pack](a4-human-review-pack-2026-09-23.md)
   is ready; participants need arranging.
3. **Representative farm pilot** — the [protocol](a4-pilot-protocol-2026-09-23.md) is a
   proposal; farms, duration, criteria, stop conditions and budget need agreeing, and it
   needs the deployed build.

Part B has not been started.

---

## What changed in this A4 batch

| Commit | What |
|---|---|
| `80f9716` | Pilot-readiness fixes from the independent review (scope, honest outage vs fallback, quick-action status, PT failure reasons, interruption message, farm-level weather grounding) |
| `8e6cdec` | SSE browser test on the production build + CI job; live-eval measurement (repairs, fallbacks, latency, tokens, outputs); response-level farm urgency check; `live-eval case <id>` |
| `77ef9b8` | **Farm advice follows the engine** (prompt fix + deterministic guard); chat turns keep question-before-answer order |
| `81164fe` | Farm "no need" claims checked against the engine in the live harness |
| `593853c` | Every chat draft recorded, so each repair can be classified |
| (docs) | This report, review pack, pilot protocol, deploy-plan corrections |

On top of `7e54b2b`/`23ea0c7` (the six blocking review fixes) and Codex's `50476ff`
(tracking the isolated runner). **None of these is pushed** — `origin/main` is at `23ea0c7`.

### The most important finding

**The live release set was blind to a systematic engine-authority failure.** Every earlier
"28/28" — Codex's on 2026-09-22 and mine this morning — passed while the farm summary told
growers that a sector *with no engine recommendation* needed no water. The harness only
checked urgency claims, never "no need" claims. Once a check existed:

| Farm case | Before (original prompt) | After (`77ef9b8`) |
|---|---|---|
| `farm-missing-recommendation` | **10/10 failed** — "Sem necessidade: todos os sectores" | 0/10 |
| `farm-low-confidence` | **6/10 failed** — "O sector B não requer rega" | 0/10 |
| The other four farm cases | 0/40 | 0/40 |

Root cause was **the product's own prompt**: "if no sector irrigates, write 'Sem
necessidade: todos os sectores'", with no exception for unassessed sectors — the model
followed it faithfully. The fix keeps "no recommendation" distinct from "no need" in the
prompt, and writes farm irrigation advice with a deterministic guard from per-sector engine
decisions (as the probe guard already does). To confirm the checks were not loosened in the
process, all 16 original bad outputs were replayed against the final checks after the
guard: **16/16 still rejected.**

A first attempt at the prompt fix made things *worse* (`farm-no-irrigation` 0/10 → 9/10
failing) and was reverted; the measured version is the minimal one.

---

## A4 checklist

Legend: ✅ verified now · ⚠️ verified with a stated limitation · 🔒 needs production access ·
👥 needs human participants.

| A4 item | Evidence | Status |
|---|---|---|
| **A4.1** Live harness covers multi-turn chat, alert, change, effectiveness, memory retrieval, action lifecycle | 23 card cases over 6 surfaces (incl. 1 each alert / change / effectiveness) + 5 multi-turn chats (incl. field-note retrieval and an action proposal) | ⚠️ Action lifecycle live = proposal only; confirm/cancel/idempotency are covered deterministically and in the browser test. Not every Part A regression has a *live* case; all have deterministic ones |
| **A4.2** Deterministic tests in CI; bounded live evals; skips/degraded are not evidence | CI runs backend, frontend unit, lint, build, and now the SSE browser job. Live eval is opt-in through the guarded runner; fallback and degraded fail it; skips are reported separately | ✅ |
| **A4.3** Evaluate factual support, engine agreement, scope, next actions, uncertainty, PT-PT, latency, tokens | Harness checks (grounding, engine agreement incl. the new farm checks, scope, PT-PT, confidence). Latency and tokens now measured per case | ✅ automated |
| **A4.3** Agronomist and grower review of representative answers | [Review pack](a4-human-review-pack-2026-09-23.md): 12 cards + 5 conversations + the calibration-overwrite confirmation, all from the release run at `81164fe`, PT-PT, with a record form | 👥 **Not done** |
| **A4.4** Feedback reasons tied to versions | `wrong_data`, `stale_answer`, `unclear_explanation`, `unhelpful_next_step`; `context_version` + `contract_version` stored per row | ✅ |
| **A4.5** Deterministic UI stays available during AI outages | `test_an_ai_outage_is_honest_and_leaves_the_engine_recommendation_available`; invalid-key behaviour checked against the real client | ✅ locally |
| **A4.5** Pilot on representative configurations | [Protocol](a4-pilot-protocol-2026-09-23.md) | 👥🔒 **Not started** |
| **Gate:** critical scope, engine-authority, action-idempotency, freshness, confidence regressions pass | Full backend suite, incl. `TestEngineAuthorityCannotBeBypassed`, `TestNegatedDirectives`, farm guard, chat-action concurrency, provenance, confidence | ✅ |
| **Gate:** no unresolved critical failures in the live release set | Release run at `81164fe`: 28/28. Farm defect found and fixed. Residual: 1 of 35 chat turns fell back (injection case — the safe outcome) | ✅ with that residual recorded |
| **Gate:** migration check | Rehearsed on the isolated DB (lock timeout, rollback, speed, old code on new schema) | ✅ locally · 🔒 production |
| **Gate:** proxy streaming check | Synthetic browser test on the production Next build, proven to discriminate | ✅ locally · 🔒 **production Caddy not verified** |
| **Gate:** latency targets chosen from A0 + pilot | Reference figures below | 👥 to agree in the pilot protocol |

---

## Environments

All local. **Production was not accessed.**

| | |
|---|---|
| Backend tests, migrations, live eval | Guarded runner `backend/scripts/run_isolated_review.py`: **both** DB URLs pinned to `irrigai_ai_review_20260921` and `current_database()` verified on every run; disposable Redis `irrigai-review-redis-20260921` |
| Development DB `irrigai` | Read-only queries only (revision, row counts, pilot-candidate counts) |
| Frontend | Node 20 locally; Playwright Chromium; synthetic SSE fixture on 127.0.0.1:8101 |
| Model | `gpt-4o-mini` for all three routes (only `OPENAI_MODEL` set). **Production's routing must be checked there** |

## Commands and results (final code)

| Check | Result |
|---|---|
| Full backend suite (`run_isolated_review pytest`) | **993 passed, 10 skipped, 0 failed** |
| Affected suites after the last change | 319 passed; outage test 2/2 |
| Frontend Vitest | **147 passed** (20 files) |
| ESLint | clean |
| `tsc --noEmit` | **0 errors** (the documented "20 pre-existing" no longer exist) |
| `npm run build` (production) | compiled |
| `npm run e2e:chat-review` | **3 passed** — progress 146–154 ms, answer 2020–2029 ms (fixture holds the answer 1200 ms) |
| Ruff lint + format, all changed Python | clean (repo's standing `B008` excluded) |
| `git diff --check` | clean |

### Streaming evidence — and what it is not

The browser test serves the **production standalone build** (`node server.js`, as the image
runs), not `next dev`, behind a synthetic backend. With `Cache-Control: no-transform`
removed from the fixture, the Next server buffers progress until completion and the test
fails. With it present, the test passes. So the header is load-bearing and the Next layer
streams. **This says nothing about Caddy**, whose configuration exists only on the host;
that check is in the deploy plan (step 7) and is still outstanding.

### Migration evidence (isolated DB)

| Claim | Result |
|---|---|
| `PGOPTIONS` reaches Alembic's psycopg2 session | `current_setting('lock_timeout')` = `5s` |
| Upgrade while a scheduler-like lock is held on `recommendation` | `LockNotAvailable` after ~5 s; revision unchanged at `1c13f632d1a6`; `chat_action` absent — **no partial schema** |
| Upgrade after release | both migrations in 1.4 s; `alembic check` clean |
| Migrate-before-swap | production's current code (`c689981`) on the new schema: **762 passed, 10 skipped, 0 failed** |
| Chat-table dump + `pg_restore --list` from stdin | works as written in the plan |

---

## Live evaluation

### Release set — `81164fe` (product code), 2026-09-23

| | |
|---|---|
| Cases | **28 passed**, 0 failed, 0 skipped, 0 degraded |
| Chat turns (7) | 4 validated · 3 repaired · 0 fallback |
| Tokens | 54,517 in · 5,043 out |
| Case duration | cards p50 3.69 s / max 6.8 s · chat cases p50 6.36 s / max 9.59 s |

### Repeated runs

| Set | Runs | Result |
|---|---|---|
| All 6 farm cases, final code | 10 × 6 = 60 | **0 failed** |
| `farm-two-irrigate`, final checks | 10 | 0 failed |
| Chat subset (5 cases), final code | 5 × 5 = 25 cases, 35 turns | 24/25 passed · turns: **26 validated, 8 repaired, 1 fallback** |

### Every repair, classified from its rejected draft

| Pattern | Frequency | Verdict |
|---|---|---|
| "E se eu regar 30 mm?" → first draft repeats the user's 30 mm | 5 of 5 runs | True positive **by policy** (A2: user amounts are not data). Costs a second call every time — a question for the human review |
| Injected field note → draft quotes the note's "50 mm" (and its directive) | 5 of 5 runs: 4 repaired, **1 fell back** | True positive by policy. The fallback is the safe outcome (engine decision shown, nothing unsafe) |
| One turn-1 `field_mismatch` repair in the release run | 1 | **Unclassified** — drafts were not yet recorded |

No false-positive repair was found in the classifiable sample. This is **one model on
synthetic fixtures**, with non-deterministic output; it is evidence about behaviour, not a
rate you can quote for production.

### Every live run today, including the failed and wasted ones

| Runs | Outcome |
|---|---|
| Full 28-case | 28/28 (pre-instrumentation) · 28/28 · **27/28** (`farm-two-irrigate`: over-literal urgency check — fixed in the harness) · 28/28 · **27/28** at `8e6cdec` (`farm-low-confidence`: English list items + unassessed-sector claim — **the real defect**) · 28/28 release |
| Two full runs | **Wasted by my command error** (output discarded / mis-filtered); results unknown |
| Farm and single-case repeats | 30 × `farm-two-irrigate`, 5 rounds × 60 farm cases while fixing |

**Measured spend:** 468 case-runs across 57 reports, 737,147 input and 75,768 output tokens,
≈ **US$ 0.16** at the list prices below, plus ≈ US$ 0.03 unmeasured. About **US$ 0.20**.

## Latency, tokens and cost — reference figures

Prices assumed: `gpt-4o-mini` US$ 0.15 / 1M input, US$ 0.60 / 1M output — **verify against
current OpenAI pricing.**

| Unit | Tokens | Cost | Note |
|---|---|---|---|
| Chat turn (incl. repairs) | ~2,900 in · ~130 out | ≈ US$ 0.0005 | synthetic contexts are small; expect 3–5× in production |
| Structured card | ~1,490 in · ~180 out | ≈ US$ 0.0003 | |
| Full 28-case eval | ~54.5k in · ~5k out | ≈ US$ 0.011 | |

Latency figures above are **model-call time on fixtures**, without database context
building or the Caddy hop. Production latency comes from `irrigai_ai_chat_stage_seconds`
(server-side `first_progress` / `first_answer` / `complete`) during the pilot, and from
the browser check for the proxy.

---

## Independent-review findings: triage

Triaged against the A4 gate. **Fixed** where the finding would mislead a pilot user or
invalidate evidence; otherwise backlogged with a reason.

### Fixed in this batch

Six blocking defects (`7e54b2b`), then: Histórico cross-scope transcripts and the English
409 · grounding fallback shown as outage · quick-action status lost on reopen · failed
confirm showing "Unprocessable Entity" · malformed interruption message · farm weather
ungroundable in multi-sector turns · SSE browser test unreachable by CI. **New in A4:** farm
advice contradicting the engine for unassessed sectors · chat transcripts ordered
answer-first (also the intermittent `test_chat_resumes_server_side_history`) · several
eval-harness blind spots and false positives.

### Backlog — deliberately not fixed in A4

| Item | Why not now |
|---|---|
| `confirm` has no timeout and holds the row lock | Single-sector operations take ~20–35 s, far below the ~5 min proxy cutoff; pilot stop condition covers a slow confirm |
| A 409 can pin a card at "A executar…" with no polling | Needs two tabs racing |
| No dedicated AI kill switch; an **empty** key makes AI endpoints return 500 | Documented working lever (invalid non-empty key) in the pilot protocol |
| "Confiança por determinar" constant on alert and farm-summary cards | Under-claims (safe direction); put to reviewers |
| Model prose uses dot decimals ("9.4 mm") and mixes *tu*/*você*; one English list item observed | PT-PT quality; put to reviewers, not a safety issue |
| Product `_SENTENCE_END_RE` / `_CLAUSE_SPLIT_RE` don't end a sentence at "Sector 2." | Affects clause attribution only; the negation bridge already rejects punctuation |
| `ingest_probe_readings_sync` defaults `farm_id=None` | No callers |
| `add_conqueiros_depths.py`, `onboard_innoliva.py` look probes up globally by `external_id`; `sync_probe_depths.py` and flowmeter ingestion ignore archived hierarchy | Not on the pilot path; **do not run these scripts** against recovered data until fixed |
| `_open_turn` releases its advisory lock before taking the row lock | Small double-runner window; the unique proposal key prevents duplicate actions |
| `client_message_id` lookup: wrong index, can raise `MultipleResultsFound` across conversations | Not reachable from the UI |
| `cancel` unrated; quota consumed before authorization; chat writes audited with `user_id=NULL`; `_get_sector_context_block` `KeyError` | Low impact |
| Cancelling a stream discards the text read so far; ✕ inert for quick actions/confirm; `SectorAnalysis` field-note double-persist; SSE reader not cancelled on throw | UI polish |
| Two `recommendation_id` FK columns without indexes | In the deploy plan's post-deploy steps |
| Chat grounding eval re-uses the product's `_advises` | Known circularity; the new farm checks are independent of product code |
| `irrigai_ai_response_feedback_total` label change breaks existing Grafana panels | Deploy note |
| `docs/runbooks/deploy.md` still describes two Compose files and nginx | The deploy plan supersedes it for this deploy |

---

## Stale handoffs reconciled

- **"Browser SSE proxy test passed"** (Codex, 09-22) was `next dev` behind a synthetic
  fixture. It now runs the production build and is proven to discriminate. Neither is
  production Caddy verification.
- **"Live evaluation 28/28"** (Codex 09-22; mine earlier today) was true and blind to the
  farm defect above. Superseded by the release run at `81164fe` with the new checks.
- **`1aa77d1` "pending deploy"** — the prod checkout includes it, but its images may not.
  Unknown until checked on the host (deploy plan, step 1).
- **`tsc` "20 pre-existing errors"** — now 0.
- **Deploy plan, first version** — had no `db-backup` restart, a development fact presented
  as production, no rollback tags, a marker grep that could never match, and a broken line
  continuation. All corrected; see the plan's own corrections section.

## Remaining limitations

- No evidence yet about **real** farm data, **real** users, or the **production** proxy.
- Live results are one model on synthetic fixtures; production contexts are larger.
- Eval latency excludes context building and network.
- The soil-bound configurations (probe-calibrated, manual override) have no candidates in
  the development copy; covering them in the pilot may require creating them.

---

## Approvals requested

Each is a separate operation; none is assumed.

1. **Push** the local commits to `origin/main`.
2. **Production read-only inspection** — revision, running image contents, disk, backups,
   Caddyfile (deploy plan step 1).
3. **Stop `db-backup` and dump the chat tables** (step 2).
4. **Tag, pull and build** images — no service change (steps 3–4).
5. **Run the two migrations** with `lock_timeout=5s`, outside 03:50–05:30 UTC (step 5).
6. **Swap backend, worker and frontend; verify; restart `db-backup`** (steps 6–8).
7. **Public streaming check** — one chat question from a test account through Caddy (step 7).
8. **Human review** — arrange 1 agronomist and 2+ growers for the review pack.
9. **Pilot** — agree the protocol's farms, duration, criteria, stop conditions and budget;
   decide on the two soil-bound configurations.
