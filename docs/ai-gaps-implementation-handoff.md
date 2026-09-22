# Part A implementation handoff — AI gaps (2026-09-10)

Implements **Part A only** (A0–A4) of `docs/ai-action-plan-2026-09-10.md`.
**B1–B6 were not implemented and no Part B feature was started.**

Nothing here has been committed, pushed, or deployed, and no external message was
sent. Migration head after this batch is **`019a556f37dd`**.

---

## 1. Completion status

| Phase | Status | Notes |
| --- | --- | --- |
| A0 — regression coverage and baseline | **Complete** | Every gap has a failing-first regression case; latency measured per stage through the real proxy; the one pre-existing backend failure is recorded separately. |
| A1 — confidence and context | **Complete** | Confidence split into three server-derived axes; engine reason preserved; chat weather resolved through the shared plot resolver; field observations exposed through an access-checked read tool; canonical context reused per turn. |
| A2 — grounded chat and durable actions | **Complete** | Chat carries server-resolved evidence, provenance, and a validation status; numeric and engine-agreement checks with one bounded repair and a deterministic fallback; durable `chat_action` lifecycle with idempotency and confirmation-time revalidation; quick actions persisted in the conversation. |
| A3 — freshness and responsiveness | **Complete** | Analyses bound to recommendation + input digest + contract version, marked historical with a refresh path; local caches scoped by user and cleared on logout; post-completion chunking replaced by real progress events; cancellation/timeout/disconnect/retry handled; conversation picker added. |
| A4 — evaluation and release readiness | **Implementation complete; gate NOT passed** | Harness extended and both live suites pass, but agronomist/grower review and the pilot could not be performed. See §6. |

---

## 2. What changed, per phase, with acceptance evidence

### A0 — regression coverage and baseline

Baseline recorded **before** any implementation:

- backend `1 failed, 761 passed, 10 skipped` — the single failure is
  `tests/test_engine/test_pipeline_soil_water.py::test_probeless_flowmeter_sector_uses_water_balance_model`,
  a **pre-existing** data-dependent failure against the shared dev DB. It fails
  identically before and after this work.
- frontend `109 passed (17 files)`.

Each gap got a reproduction that failed against the then-current code before the
fix landed:

| Gap | Reproduction |
| --- | --- |
| Inflated confidence | `tests/test_ai/test_probe_guard_semantics.py::TestNoConfidenceInflation` (3 tests, all red at first) |
| Engine reason erased | `…::TestEngineReasonIsPreserved` |
| "Low risk" asserted on stale/absent sensors | `…::TestRiskIsNotAutomaticallyLow` |
| Chat weather ignoring sector/plot scope | `tests/test_ai/test_tools_scope_and_memory.py::TestWeatherScope` |
| Field notes unreachable from chat | `…::TestFieldObservationTool` |
| Context rebuilt per block read | `…::TestContextReuse` |
| Unsupported chat claims | `tests/test_ai/test_chat_grounding.py`, `tests/test_api/test_chat_grounded_stream.py` |
| Stale stored analyses | `tests/test_ai/test_ai_provenance.py`, `frontend .../SectorAnalysis.freshness.test.tsx` |
| Delayed first output | `tests/test_api/test_chat_grounded_stream.py::test_progress_events_precede_any_answer_content` |
| Repeated action confirmation | `tests/test_api/test_chat_actions.py` |

**Latency, measured per stage** (`app/metrics.py` → `irrigai_ai_chat_stage_seconds`,
labels `surface` + `stage`, no tenant identifiers). Measured on a real farm chat turn
**through the Next.js proxy on :3000**, not an in-process client:

| Stage | Seconds |
| --- | --- |
| first progress event | **0.015** |
| first validated answer block | **3.54** |
| complete | **3.55** |

Before A3 the client saw nothing until the whole turn finished, so first-output and
complete were the same number by construction.

Also added: `irrigai_ai_chat_turns_total{surface,outcome}` (validated / repaired /
fallback / interrupted / failed) and `irrigai_ai_chat_actions_total{action_type,outcome}`.
`irrigai_ai_response_feedback_total` gained a bounded `reason` label.

### A1 — confidence and context

- **`backend/app/ai/answer_confidence.py`** (new, pure, 22 unit tests). Three axes:
  `engine_confidence` (the engine's own level — the AI layer may never raise it;
  `unknown` when no recommendation exists, never `low`), `data_quality` (from the
  canonical probe-state block, which already applies `engine/staleness.py`), and
  `explanation_status`. `confidence_score` survives for API compatibility but is now
  a pure function of the two agronomic axes, capped when the explanation degraded.
  **The probe guard's `max(score, 0.75)` floor is gone.**
- **Engine reason preserved.** `probe_signal.compute_probe_signal_stats` now carries
  `latest_recommendation.reasons` and `.confidence_level`, and the guard quotes them
  (`_engine_no_irrigation_advice`). With no engine reason it states the decision and
  fabricates no justification — the old fixed "reserva suficiente" sentence is gone.
- **Risk is no longer automatically low.** The guard sets `low` only when data quality
  is `fresh`; stale or absent readings stay `medium`. Irrigation urgency and sensor
  reliability are separate questions.
- **Chat weather respects scope.** `tools._get_weather` resolves the sector's plot and
  calls the shared `get_weather_summary(..., plot_id=...)`; the result always carries
  `scope` (`plot` with the plot id, or `farm` with a "representativa" note) plus
  `latest_observation_at`. Two sectors on different plots receive different weather.
- **Field observations reachable.** New `get_field_observations` tool over the new
  shared `services/field_observation_service.py` (also now used by the REST endpoint,
  so the expiry rule cannot diverge). Returns source, observed time, expiry, and
  verification; expired notes are never returned.
- **Canonical context reused.** New `ToolSession` memoises the ten-block sector context
  per turn: five block-reading tools used to trigger five full context builds.
- **Rendering.** `render_structured` and `StructuredAIResult.tsx` report the axes
  qualitatively; the percentage is only a fallback for pre-A1 payloads.

### A2 — grounded chat and durable actions

- **`backend/app/ai/chat_grounding.py`** (new, pure, 37 unit tests). Extracts numbers
  carrying an agronomic unit (mm, m³/ha, %, °C, L — time units are deliberately
  excluded: "nas próximas 24-48 horas" is a horizon, not a reading), and rejects any
  that the turn's data does not support. Also rejects irrigation directives that
  contradict the engine — and only when the turn actually read that decision.
- **Repair, then fall back.** One bounded repair naming the exact violations; if that
  fails, the answer is replaced by `deterministic_fallback_reply()` built from engine
  outputs. `validation_status` (`validated` / `repaired` / `fallback`) travels on the
  response and is rendered to the user.
- **Evidence attached to what the answer used.** `select_chat_evidence()` matches the
  numbers in the reply against the registry built from this turn's tool results, plus
  the engine decision. A citation the prose does not use is not returned.
- **Notes are data, never instructions.** The user's message is fenced
  (`prompt_templates.wrap_user_message`), the system prompt states the rule explicitly,
  and `get_field_observations` output is excluded from the grounded value set entirely —
  an unverified note can never become the evidence for a number.
- **Durable action lifecycle.** New `chat_action` table +
  `backend/app/services/chat_actions.py`. Statuses `pending → confirmed →
  succeeded|failed`, or `cancelled` / `invalidated`. Confirmation is claimed with an
  atomic `UPDATE … WHERE status IN ('pending','failed') RETURNING`, so two concurrent
  confirmations cannot both write; a replay of a succeeded action returns the stored
  result. `uq_chat_action_idempotency` on `(user_id, idempotency_key)` gives the
  proposal a stable server identity (`msg:<assistant_message_id>`).
- **Revalidation at confirmation time.** Farm/sector ownership and — for
  recommendation-scoped actions — recommendation freshness. A superseded recommendation
  marks the action `invalidated` and returns **409**; a fresh proposal is required.
- **Failures stay failures.** A failed action is stored with its `error_detail`, is
  retryable, and renders as failed. Reopening a conversation shows the real status.
- **Legacy proposals.** A stored `proposed_action` with no action row reports
  `status: "legacy"` and is never offered for confirmation — its outcome was never
  recorded, so it is never assumed executed.
- **Results are conversation events.** A successful action appends an assistant turn
  (`surface="action_result"`), so the next question can see it.
- **Quick actions unified.** New `POST /farms/{id}/chat/quick-action` runs the card
  surface server-side and persists the user + assistant turns with their evidence and
  degraded status; the frontend no longer holds the result only in browser state.

### A3 — freshness and responsiveness

- **`backend/app/services/ai_provenance.py`** (new). `context_version` is a digest over
  the *observation times of the inputs* — latest recommendation id and time, freshest
  probe reading, active calibration, newest field note — never request-time noise.
  `CONTRACT_VERSION` (`app/services/ai_runtime.py`) is part of the Redis cache key and
  travels on every response.
- **`GET /sectors/{id}/ai-analysis-version`** lets a client decide staleness without
  paying for a model call. Sector card responses carry a matching `provenance` block.
- **Historical, not silently current.** `SectorAnalysis.tsx` stores the provenance with
  the analysis, compares it on mount, and renders an explicit "Análise histórica" banner
  with an *Actualizar análise* action. A pre-A3 entry with no provenance is historical
  by definition.
- **Caches scoped by user.** Keys are `irrigai_ai_analysis:<user>:<sector>`; `setToken`
  drops all of them when the subject changes (or when the token cannot be read), and
  `clearToken` clears them on logout.
- **Real streaming.** `ChatAgent.run_events()` is an async generator emitting
  `progress` while the work happens and `answer` blocks **only after validation**.
  Tool arguments are never emitted — only fixed Portuguese stage labels. No raw tokens
  bypass A2. The non-streaming endpoint drains the same generator.
- **Interruptions are honest.** The assistant turn is persisted as `interrupted`
  up-front and becomes `complete` only when a validated answer exists; `chat_message`
  gained a `status` column with a CHECK constraint. `conversation_history` skips
  non-complete turns. `asyncio.timeout(CHAT_TURN_TIMEOUT_SECONDS=120)` bounds a turn;
  cancellation and disconnect leave the interrupted record and count
  `ai_chat_turns_total{outcome="interrupted"}`.
- **Retries do not duplicate.** `client_message_id` + partial unique index
  `uq_chat_message_client_id`; a retried send replays the stored answer.
  `ChatPanel` sends a turn id and aborts the stream on navigation/close.
- **Conversation picker** over the existing list/detail endpoints; historical turns show
  their original date, and follow-ups fetch current data.

### A4 — evaluation

- `tests/ai_eval/harness.py` gained six Part-A assertions:
  `assert_confidence_is_server_derived`, `assert_engine_reason_is_preserved`,
  `assert_weather_scope_is_explicit`, `assert_chat_reply_is_grounded`,
  `assert_notes_are_data_not_instructions`, `assert_action_lifecycle_is_terminal`.
  All are unit-tested deterministically in `tests/test_ai/test_eval_harness_contracts.py`
  (30 tests) and therefore run in normal CI.
- New live runner **`tests/ai_eval/eval_chat_multiturn.py`** (+ `cases/chat_multiturn.json`,
  5 cases) covering multi-turn chat, weather scope, note injection, and the proposal
  lifecycle. It prints a ledger separating **model failures**, **provider failures**, and
  **skips** — a skipped run or a degraded fallback is never counted as model quality.
- `eval_golden_set.py` now also asserts the confidence derivation and engine-reason
  preservation; the six probe cases were updated to include the `probe_state` block that
  production now sends.
- Feedback gained the four required reasons (`wrong_data`, `stale_answer`,
  `unclear_explanation`, `unhelpful_next_step`) plus `context_version` /
  `contract_version`, both persisted and surfaced in the chat UI.

**Three real defects were found by running the live evaluations** (recorded because
they are the argument for keeping these runners):

1. **Negated advice matched the irrigation-directive patterns.** "não deves regar"
   contains "deves regar", so the validator rejected the exact answers it exists to
   protect and collapsed them to the deterministic fallback. Fixed with a clause-level
   negation scan (`_advises`), covered by `TestNegatedDirectives`.
2. **Facts did not carry across turns.** A number verified in turn 1 was treated as
   invented in turn 2. `collect_facts` now accepts `prior_evidence` (server-resolved
   evidence of earlier assistant turns) and `user_message` (a number the user themself
   introduced may be echoed, while the engine-conflict check still stops it becoming
   advice). Covered by `TestMultiTurnFacts`.
3. **Probe diagnosis graded confidence through the evidence wrapper.** The stats are
   passed to `_complete_structured` wrapped under `probe_signal` so the registry can
   cite paths; reading confidence through that wrapper graded every probe diagnosis
   `unknown/unknown` even with fresh readings. Fixed in
   `interpret_probe_patterns_structured`, covered by
   `TestProbeDiagnosisConfidenceIsDerivedFromTheStats`.

**A test-infra defect this batch also had to fix.** `consume_daily_ai_quota` is a real
per-user Redis counter (200/day). The deterministic suite authenticates as the single
seeded owner, so the new chat tests burned that budget and, once past ~200 requests in a
day, every later run failed with 429s that read exactly like product bugs — order- and
time-of-day-dependent. `tests/conftest.py` now no-ops the router's imported reference
alongside the existing `limiter.enabled = False`, with the reason written down.
`tests/test_ai/test_ai_runtime.py` still exercises the real quota logic against a fake
Redis, so that coverage is untouched. Verified: repeated subset runs are stable and
create no `ai:quota:*` keys.

A fourth defect was found by Ruff, not by tests: the new engine-reason query used
`RecommendationReason` without importing it, so the probe-signal path would have
raised at runtime. Every guard test mocked the stats, which is why it hid. Fixed, and
`tests/test_api/test_probe_signal_engine_reasons.py` now exercises that query against
Postgres.

---

## 3. Test commands and actual results

```bash
# Backend, full suite (in the dev container, source-mounted)
docker compose exec -T backend python -m pytest -q
#   BEFORE: 1 failed, 761 passed, 10 skipped
#   AFTER:  1 failed, 892 passed,  9 skipped
#   The single failure is identical before and after:
#   tests/test_engine/test_pipeline_soil_water.py::test_probeless_flowmeter_sector_uses_water_balance_model
#   (pre-existing, data-dependent against the shared dev DB — see the repo's
#    "Test-suite caveat": judge by zero NEW failures and the total, not the split)

# Frontend
cd frontend && npm run test:run     # BEFORE: 109 passed (17 files)
                                    # AFTER:  130 passed (19 files)
npx eslint src --ext .ts,.tsx       # clean
npx tsc --noEmit                    # exactly the 20 pre-existing
                                    # StructuredAIResult.test.tsx errors, no new ones
npm run build                       # clean production build

# Migrations
docker compose exec -T backend alembic check     # "No new upgrade operations detected."
docker compose exec -T backend alembic current   # 019a556f37dd (head)
# Round trip verified: alembic downgrade -1 && alembic upgrade head

# Live evaluations (LLM_PROVIDER=openai, real key present in the dev container)
docker compose exec -T backend python -m pytest tests/ai_eval/eval_golden_set.py -q
#   20 passed
docker compose exec -T backend python -m pytest tests/ai_eval/eval_chat_multiturn.py -q -s
#   5 passed — ledger: passed=5 model_failures=0 provider_failures=0

# Ruff, changed files only
docker compose exec -T backend ruff check <changed .py files>
#   36 errors, ALL B008 (the project-wide FastAPI `Depends()` convention that CI
#   does not gate, per CLAUDE.md). Zero other findings.
docker compose exec -T backend ruff format <new .py files>   # applied
```

**One live-model flake worth recording, not caused by this work:** the pre-existing
golden case `farm-two-irrigate` failed once with
`urgent irrigation does not identify an engine-irrigate sector: 'Rega urgente em dois
sectores, sem necessidade em um sector'` and passed on two immediate re-runs. The
assertion is correct — an urgent claim naming no sector is unactionable — so this is a
model-quality flake on the farm-summary surface, untouched by Part A.

---

## 4. Migration and compatibility

**One migration: `019a556f37dd` (`1c13f632d1a6` → `019a556f37dd`).** Additive only; no
data is rewritten or destroyed.

- New table `chat_action` (+ 2 indexes, a status CHECK, and
  `uq_chat_action_idempotency`).
- `chat_message`: `status` (NOT NULL DEFAULT `'complete'`, CHECK), `evidence`,
  `context_version`, `recommendation_id` (FK ON DELETE SET NULL), `surface`,
  `client_message_id`, and the partial unique index `uq_chat_message_client_id`.
- `ai_response_feedback`: `reason`, `context_version`, `contract_version` (all nullable).

Alembic autogenerate does not emit CHECK constraints — `ck_chat_message_status` is
written by hand in the migration, and the FK is explicitly named
`chat_message_recommendation_id_fkey` so the downgrade is not a no-name `drop_constraint`.

**Compatibility:**

- Existing conversations load unchanged: pre-migration rows get `status='complete'`
  from the server default and null provenance.
- **Legacy pending actions are handled explicitly**: a stored `proposed_action` with no
  `chat_action` row reports `status: "legacy"`, is rendered as historical, and is never
  confirmable. It is never assumed to have executed.
- `AgronomicInterpretation.confidence_score` is retained (deprecated in the docstring)
  so existing API consumers do not break; `confidence` is additive with defaults, so
  cached pre-A1 JSON still parses.
- `ChatResponse` and `ChatMessageOut` gained fields only. `proposed_action` is now
  `ProposedActionOut`, a superset of `ProposedAction`.
- The old direct-write client path (`recommendationsApi.accept` etc. from the chat
  panel) is replaced by the server-side confirm endpoint; those REST endpoints are
  unchanged and still used elsewhere.
- **Rollback** does not require deleting observations or action history: the migration's
  `downgrade()` drops only what it added, and no prior column changed meaning.

**Deploy** (three Compose files, per the project runbook): build `backend worker
frontend`, run `alembic upgrade head` **before** swapping images, then
`up -d --no-deps backend worker frontend`. `worker` needs no rebuild for behaviour here
but should stay in step with the image set. Swap backend and frontend **together**: an
old frontend cannot read the new streaming contract, and a new frontend expects
`action_id` on proposals.

---

## 5. Constraints — confirmed held

- Numerical agronomy and calibration remain deterministic; nothing in this batch lets a
  model choose FC/refill, a dose, or a decision. The engine-conflict check makes the
  engine's authority *enforceable* rather than merely instructed.
- Calibration application policy untouched (`Farm.calibration_auto_apply`, the gate in
  `engine/calibration_policy.py`, and the sweep are unchanged).
- Water-entry detection remains probe-only; automatic events remain unlogged until user
  classification. No detector input changed.
- Tenant ownership goes through `access.py` everywhere, including the new tools and
  action endpoints; missing and cross-tenant both return 404. Active-record selection
  untouched.
- AI writes remain proposals requiring explicit confirmation, and confirmation now
  revalidates permission, scope, and recommendation freshness.
- Copy is PT-PT; `fmt_pt` / `formatDecimal` untouched, and no new percentage headline
  was introduced.
- No model migration, vector database, controller integration, or notification channel.
- **B1–B6 not implemented**: no briefing service, no automatic follow-up, no scenario
  engine, no memory manager or voice entry, no investigation records, no farm-wide
  planning.

---

## 6. Outstanding checks and remaining risks

**The A4 release gate has NOT passed.** These could not be performed here:

1. **Agronomist and grower review of representative answers** (A4.3) — requires human
   participants. Only automated factual-support, engine-agreement, scope, and PT-PT
   checks were run.
2. **Pilot on representative farm configurations** (A4.5) — not started. In particular
   nothing has been exercised on Innoliva's per-plot-weather shape with real data; the
   plot-scope resolution is covered by unit tests and the shared resolver, not by a
   production farm.
3. **Playwright E2E** — not run. The repo records this job as red/never-green on main
   and not treated as a gate; it remains outside this batch.
4. **Token/cost measurement under load** — `irrigai_ai_tokens_*` already exist and the
   new stage histogram is live, but no sustained-load figures were gathered.

**Risks worth watching after deploy:**

- `ai_chat_turns_total{outcome="fallback"}` is the number to watch. A rising rate means
  the model is producing claims the data does not support — or that the validator is
  over-rejecting. Both live evaluations exist to tell those apart; check a sample of
  `validation_issues` before changing thresholds.
- The numeric-claim check is unit-based and deliberately narrow. It will not catch a
  wrong *qualitative* statement, and a valid citation still does not prove the prose
  follows from it. The semantic side stays with the evaluation set, as the plan says.
- `CHAT_TURN_TIMEOUT_SECONDS = 120` was chosen from the measured 3.5 s complete time
  with wide headroom; it has not been tuned against a slow model or a large farm.
- The quick-action endpoint is rate-limited at 10/min and shares the daily AI quota; a
  farm summary is the most expensive surface and is now reachable from the chat panel.
- `ProbeCalibrationService.compute_and_save` is invoked from the action executor; a
  sector with no usable VWC envelope raises and is recorded as `failed`, which is the
  intended outcome but produces a red card in the UI. Confirmed by test.

**Deliberately not done** (out of Part A scope): SSE remains one connection per turn
with no resume-mid-stream; the conversation picker lists 50 conversations without
paging; `_answer_blocks` splits on sentence boundaries, so a very long single sentence
still arrives as one block.

---

## 7. State of the working tree (for review)

**Nothing is committed.** All of Part A sits uncommitted on `main` as of 2026-09-10.
Baseline commit is `15e6ad7` ("docs: record the 2026-08-24 disk-full outage…"), so the
complete review surface is `git diff` plus the untracked files listed below —
56 paths under `backend/` and `frontend/`, 35 tracked files changed
(+3451 / −529) plus 21 new files.

Reviewer note: this repo is often worked by two agents at once, so if a file below
looks unrelated to Part A, check `git log`/timestamps before assuming it belongs to
this batch.

```
modified: backend/app/ai/assistant.py
modified: backend/app/ai/chat_agent.py
modified: backend/app/ai/context_builder.py
modified: backend/app/ai/probe_signal.py
modified: backend/app/ai/prompt_templates.py
modified: backend/app/ai/tools.py
modified: backend/app/api/v1/auto_calibration.py
modified: backend/app/api/v1/chat.py
modified: backend/app/api/v1/field_observations.py
modified: backend/app/metrics.py
modified: backend/app/models/ai_response_feedback.py
modified: backend/app/models/chat_message.py
modified: backend/app/models/__init__.py
modified: backend/app/schemas/ai.py
modified: backend/app/schemas/chat.py
modified: backend/app/services/ai_runtime.py
modified: backend/app/services/chat_memory.py
modified: backend/app/services/probe_calibration_service.py
modified: backend/app/services/recommendation_service.py
modified: backend/tests/ai_eval/cases/golden_contexts.json
modified: backend/tests/ai_eval/eval_golden_set.py
modified: backend/tests/ai_eval/harness.py
modified: backend/tests/ai_eval/README.md
modified: backend/tests/conftest.py
modified: backend/tests/test_ai/test_assistant.py
modified: backend/tests/test_ai/test_eval_harness_contracts.py
modified: frontend/src/app/farms/[farmId]/sectors/[sectorId]/page.tsx
modified: frontend/src/components/ai/StructuredAIResult.tsx
modified: frontend/src/components/ai/__tests__/StructuredAIResult.test.tsx
modified: frontend/src/components/chat/ChatButton.tsx
modified: frontend/src/components/chat/ChatPanel.test.tsx
modified: frontend/src/components/chat/ChatPanel.tsx
modified: frontend/src/components/sectors/SectorAnalysis.tsx
modified: frontend/src/lib/api.ts
modified: frontend/src/types/index.ts
new:      backend/alembic/versions/019a556f37dd_ai_grounding_chat_actions_and_provenance.py
new:      backend/alembic/versions/a0d5b179c368_link_chat_answers_to_durable_user_turns.py
new:      backend/app/ai/answer_confidence.py
new:      backend/app/ai/chat_grounding.py
new:      backend/app/models/chat_action.py
new:      backend/app/services/ai_provenance.py
new:      backend/app/services/chat_actions.py
new:      backend/app/services/field_observation_service.py
new:      backend/scripts/assess_farm_recovery.py
new:      backend/tests/ai_eval/cases/chat_multiturn.json
new:      backend/tests/ai_eval/eval_chat_multiturn.py
new:      backend/tests/test_ai/test_ai_provenance.py
new:      backend/tests/test_ai/test_answer_confidence.py
new:      backend/tests/test_ai/test_chat_grounding.py
new:      backend/tests/test_ai/test_probe_guard_semantics.py
new:      backend/tests/test_ai/test_tools_scope_and_memory.py
new:      backend/tests/test_api/test_chat_actions.py
new:      backend/tests/test_api/test_chat_grounded_stream.py
new:      backend/tests/test_api/test_probe_signal_engine_reasons.py
new:      frontend/src/components/sectors/__tests__/SectorAnalysis.freshness.test.tsx
new:      frontend/src/lib/__tests__/aiCacheScope.test.ts
```

### Where to start

| Concern | Read first |
| --- | --- |
| Confidence semantics (A1) | `backend/app/ai/answer_confidence.py`, then the guard in `backend/app/ai/assistant.py` |
| Chat grounding (A2) | `backend/app/ai/chat_grounding.py`, then `backend/app/ai/chat_agent.py` |
| Action lifecycle (A2) | `backend/app/services/chat_actions.py` + `backend/app/models/chat_action.py` |
| Freshness (A3) | `backend/app/services/ai_provenance.py`, `frontend/src/components/sectors/SectorAnalysis.tsx` |
| Streaming (A3) | `stream_farm_chat` in `backend/app/api/v1/chat.py` |
| Evaluation (A4) | `backend/tests/ai_eval/harness.py`, `backend/tests/ai_eval/eval_chat_multiturn.py` |

The purest units — `answer_confidence.py`, `chat_grounding.py`, `ai_provenance.py` —
have no DB and no I/O and are covered by table-driven tests, in the same idiom as
`engine/soil_bounds.py` and `engine/calibration_policy.py`.

### Reproducing the verification

```bash
docker compose exec -T backend python -m pytest -q                    # 1 pre-existing failure, 892 passed
docker compose exec -T backend alembic check                          # clean, head 019a556f37dd
cd frontend && npm run test:run && npx eslint src --ext .ts,.tsx && npm run build
# Live (needs LLM_PROVIDER=openai + key; skips cleanly without one)
docker compose exec -T backend python -m pytest tests/ai_eval/eval_golden_set.py -q
docker compose exec -T backend python -m pytest tests/ai_eval/eval_chat_multiturn.py -q -s
```

The dev DB is already migrated to `019a556f37dd`; a reviewer starting from a clean DB
must run `alembic upgrade head` before the API tests.
