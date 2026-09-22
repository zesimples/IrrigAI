# A0–A4 review fixes — interrupted handoff, 2026-09-10

**Superseded implementation checkpoint:** See [the September 22 review fixes](claude-a0-a4-review-fixes-2026-09-22.md) for current code, isolated test results and release limitations. The incident history below is retained for audit.

Status: **incomplete; do not commit, push, or deploy yet.** Existing Claude changes were preserved. Codex added the changes below, but verification and several review items remain unfinished.

**2026-09-21 update:** Development recovery was subsequently approved and completed. Read [development-recovery-completed-2026-09-21.md](development-recovery-completed-2026-09-21.md) before resuming this fix batch. Original farm identities are restored, replacements preserved as archived, and an active/farm-scoped ingestion lookup fix was added and tested. Development remains at `019a556f37dd`; the A0–A4 verification and additive migration work below are still pending.

## Development database incident — resolve first

**Follow-up:** The user subsequently approved restoration into a separate recovery database. That restore succeeded; see [development-recovery-assessment-2026-09-10.md](development-recovery-assessment-2026-09-10.md) for verified counts and the selective-recovery proposal. Development has not yet been restored. The paragraphs below preserve the original incident handoff.

While preparing an isolated regression database, Codex mistakenly ran `python -m app.seed` with only `DATABASE_URL` overridden. The seed script uses `DATABASE_URL_SYNC`, which still pointed to the development database `irrigai`. This was Codex's error.

The script committed recreation of these development demo farms and their dependent data:

- Herdade do Esporão — replacement ID `cfb8b717-fbca-4ed7-9368-7a162ab1718b`, created 2026-09-10 15:47:22 UTC.
- Herdade dos Conqueiros — replacement ID `e630eb42-28a5-46f8-bc03-eed99393f0a2`, created 2026-09-10 15:47:25 UTC.
- Herdade das Amendoas do Lago — replacement ID `b9857cc7-c59d-4bfb-8db4-b2b7b5cad231`, created 2026-09-10 15:47:30 UTC.

The attached command was interrupted, but container execution continued long enough to commit all three. A subsequent `docker compose top backend` confirmed no seed process remained. No production host was accessed, and no restoration has been attempted.

Recovery candidate: `backups/irrigai_20260910_092012.sql.gz` (579 MB). The adjacent `092011` file is only 20 bytes and is not a useful database backup. A backup restore has NOT been verified. Get the user's approval before altering the development database again. Prefer restoring the backup into a separate recovery database and inspecting the affected farm subtrees before deciding between selective recovery and a whole-database rollback. A full rollback would lose unrelated changes made after the backup. The existing restore runbook is destructive and must not be executed blindly. Exact historical loss has not yet been quantified.

An isolated database named `irrigai_ai_review_20260910` also exists. Migrations and the actual pytest run were correctly pointed there. **Set BOTH `DATABASE_URL` and `DATABASE_URL_SYNC` on every subsequent test/seed/migration command.** Set `LLM_PROVIDER=mock` and use isolated/unavailable Redis, not the development quota/cache database.

## Changes implemented, pending further verification

### Weather access and scope

- `backend/app/ai/tools.py`: reject a model-supplied farm outside the conversation scope; explicitly validate farm ownership and sector membership before weather access.
- `context_builder.py`: expose the resolved weather plot ID so fallback farm weather is not labelled plot-local.
- Recommendation-scoped proposals derive their target sector from the authorized recommendation and validate it against conversation scope.

### Action transaction ownership and cancellation

- `recommendation_service.generate_recommendation` accepts keyword-only `commit=False`; chat regeneration uses it so the recommendation and successful durable action can commit together.
- Action success/result-event persistence now sits inside the rollback-protected execution block.
- Cancellation uses a conditional database update of pending/failed actions; it cannot overwrite confirmed/successful actions from a stale object.
- Failed execution rolls back the mutation, sanitizes error detail, and conditionally records failure without overwriting a concurrently completed/cancelled action.
- Frontend cancellation errors retain the actual status instead of pretending cancellation succeeded.

### Manual calibration parity

- Added `ProbeCalibrationService.run_manual`, shared by the HTTP calibration button and chat action.
- Preserves deterministic computation; clears the custom crop-profile override; resolves before/effective bounds; records the same audit and change information.
- The shared operation does not commit; callers own the transaction.

### Durable chat turn identity and replay

- Added `ChatMessage.reply_to_id` (unique self-FK) and `response_metadata`.
- `_open_turn` persists a single user/assistant pair, links replies explicitly, detects client-ID reuse with different text, and can rediscover a conversation when its ID was lost with the first response.
- Transaction advisory lock serializes discovery; a NOWAIT row lock prevents two active runners for the same question.
- Interrupted attempts resume the same placeholder. History excludes the retried user message instead of appending it again.
- Replay includes saved response metadata and the current persisted proposal state.
- Migration **`a0d5b179c368_link_chat_answers_to_durable_user_turns.py`** is additive on Claude's **`019a556f37dd`**. Autogenerated against the isolated DB, with explicit constraint names added for reversible downgrade. Upgrade passed; downgrade/check still need testing.
- This new migration has NOT been applied to development `irrigai`. The source-mounted development backend may therefore have code/schema mismatch until recovery and migration are deliberately handled.

### Frontend race/retry handling

- Generation guards prevent delayed conversation detail responses and old stream callbacks from overwriting newer scope/send state.
- Retry IDs are tied to the original text; changed text gets a new ID. Same-text retries reuse the visible question rather than appending duplicates.
- Interrupted text is restored in the input.
- SSE EOF without a `done` event is now treated as interrupted, not successful.

### Grounding hardening

- Tool-loop exhaustion now emits deterministic fallback, never the last unchecked model text.
- Selected-sector chat automatically reads the current engine decision before model interaction.
- Prior-turn evidence and user hypotheses no longer count as current measured values.
- Irrigation-dose claims are compared with the engine dose, not merely any measured millimetre value. Broader Portuguese directive forms include `Aplica` and recommended-dose labels.
- Added limited indicator binding for depletion/rain claims and conservative rejection of advice without an unambiguous current engine decision.
- **Still requires review:** this remains a heuristic validator, not comprehensive semantic grounding. Multi-sector/farm-overview claim binding needs a deliberate solution and regression coverage; comments describing the old historical-quoting behavior need updating. Added mandatory status lookup also requires updating old mocks and expected call counts.

### Analysis freshness

- Replaced four maximum-timestamp checks with a canonical full-context digest, including note state, weather, effective calibration, and recommendation contents.
- Removes selected request-time metadata/age noise while retaining meaningful freshness states.
- Captures pre-generation provenance and checks it after generation; if inputs changed during generation, the answer is marked with an intentionally non-current version rather than the newer version.
- Frontend starts restored results as unverified/historical, treats failed freshness checks conservatively, and rechecks every 30 seconds and on focus.
- **Still requires review:** real-context digest stability and all concurrent mutation paths need integration tests; sector-analysis response races on navigation need checking.

### Typecheck and regressions

- Added explicit Vitest imports to `StructuredAIResult.test.tsx`.
- Added regression cases for foreign weather farm arguments, fallback scope labels, wrong-field dose substitution, `Aplica` against skip, prior/user values not being measurements, and same-timestamp context changes.
- Updated three existing assertions that had explicitly allowed unsafe historical/user-value grounding.

## Verification actually performed

- Frontend existing suite: **130 passed**, 19 files.
- Frontend `npx tsc --noEmit`: **passed** after the explicit Vitest import.
- `git diff --check`: **passed** at handoff.
- Isolated database: migration chain through `019a556f37dd`, then upgrade to `a0d5b179c368`: **passed**.
- Backend run on isolated DB: **217 passed, 4 failed, 4 errors**. Some new regression tests were added after this run and have not run yet.

Backend failures/errors from that run:

- `test_chat_agent_propose_calibration`: old mock lacks the newly mandatory status read.
- `test_chat_agent_accepts_current_recommendation_from_tool_output`: expected call sequence omits the new initial status read.
- `test_propose_override_no_mutation_and_validates_access`: recommendation mock is a bare object without the now-required `sector_id`.
- `test_preview_sees_soil_moisture_sectors`: empty isolated DB lacks soil presets.
- Four `test_context_v2` setup errors: isolated DB lacks seeded Herdade do Esporão.

No full clean backend run, new frontend regression run, frontend production build, changed-file Ruff check, live model evaluation, or browser pilot has been completed in this fix pass. Do not reuse previous review/Claude counts as proof for these new edits.

## Remaining work after recovery is approved

1. Verify/perform agreed development-data recovery, preserving unaffected data and backup files.
2. Prepare isolated fixtures with BOTH database URLs set; do not run seed on the shared DB.
3. Complete current grounding/scope implementation and update the legitimate test mocks above.
4. Add database-backed regressions for interrupted retry identity, unrelated later answers, simultaneous confirmation/cancellation, regeneration rollback after result-event failure, calibration parity, and provenance changes during model completion.
5. Add frontend regressions for stale history/detail responses, retrying changed text, cancellation failure, EOF without `done`, and freshness-check failure/recheck.
6. Extend the opt-in live card evaluator beyond recommendation/probe/farm to alert explanation, change analysis, and irrigation effectiveness; this review gap is still untouched.
7. Verify additive migration upgrade/downgrade/upgrade and `alembic check` on the isolated DB.
8. Run all relevant backend/frontend tests, Ruff, frontend lint/typecheck/build, and `git diff --check`.
9. Revise this handoff with final results; only then ask for commit/push authorization. Do not implement roadmap Part B.
