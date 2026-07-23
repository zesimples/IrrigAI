# Claude Code review handoff: AI P3–P6 implementation

Date: 2026-07-23

Review range: `b472cc3..1f7ab1c`

Primary implementation: `62d3179 feat(ai): complete memory robustness and outcome surfaces`

Follow-up fix: `1f7ab1c fix(ai): simplify verified evidence display`

## Review objective

Please review the completed AI-context roadmap phases P3–P6 and the evidence-display
follow-up. Concentrate on correctness, tenant isolation, deterministic-engine
authority, degraded/error behaviour, query parity, and whether the new UI exposes
the intended existing backend capabilities without creating a second source of
agronomic truth.

The deterministic recommendation pipeline, calibration engine, and outcome
evaluator remain authoritative. The LLM may explain results and propose actions,
but must not calculate irrigation decisions, FC/PMP/refill bounds, dose residuals,
or calibration coefficients.

## What was implemented

### P3 — Persistent memory and chat

New persistence:

- `ChatConversation`: user + farm scope, optional sector scope, title and activity
  timestamp.
- `ChatMessage`: persisted user/assistant turns, proposed action, degraded flag,
  model name and token-count placeholders.
- `FieldObservation`: sector, author, type, structured value/text, observed/expiry
  timestamps, and verification metadata.

New or expanded routes:

- `POST /farms/{farm_id}/chat`
- `POST /farms/{farm_id}/chat/stream`
- `GET /farms/{farm_id}/chat/conversations`
- `GET /farms/{farm_id}/chat/conversations/{conversation_id}`
- `DELETE /farms/{farm_id}/chat/conversations/{conversation_id}`
- `GET/POST /sectors/{sector_id}/field-observations`
- `PATCH /field-observations/{observation_id}/verification`
- `DELETE /field-observations/{observation_id}`

Chat conversations are constrained by current user and farm. A sector-scoped
conversation cannot be resumed with a different supplied sector. Supplied sectors
are checked against the conversation farm before the agent or tools run.

The frontend chat panel:

- resumes the most recent conversation for the current farm/sector;
- persists new turns on the server;
- uses the SSE endpoint;
- supports starting a new conversation;
- shows an explicit degraded-response warning;
- records thumbs feedback for persisted assistant messages.

The sector analysis form now persists entered field notes as seven-day
`field_check` observations before requesting an explanation. Active observations
are included under `crop_state.field_observations` in `SectorAIContextV2`.
Unverified observations are not silently upgraded; their verification state and
user-observation source are included in context.

Five read-only tools were added:

- `get_outcomes`
- `get_calibration_status`
- `get_recommendation_history`
- `get_flowmeter_summary`
- `get_stress_projection`

They reuse canonical V2 context blocks and retain sector/farm access checks. Numeric
arguments on older window/day tools are now bounded.

### P4 — Cost, resilience and observability

Request controls:

- `/auth/token`: 10/minute.
- `/auth/register`: 5/hour.
- Chat and structured AI endpoints have per-minute limits.
- Chat message, supplied history, field-note text and change-analysis windows are
  bounded by request schemas.
- Redis daily per-user LLM quota, default 200 requests.
- Mock-provider requests bypass the daily quota.
- Redis failure is fail-open and logged so an observability outage does not block
  deterministic product functionality.

OpenAI runtime settings:

- `LLM_TIMEOUT_SECONDS`
- `LLM_MAX_RETRIES`
- `LLM_DAILY_REQUEST_LIMIT`
- `LLM_FARM_SUMMARY_CACHE_TTL_SECONDS`

Structured-completion failures:

- are logged with surface and exception type;
- increment `irrigai_ai_degraded_responses_total`;
- return a grounded `AgronomicInterpretation` with `degraded=true` and
  `error_code=llm_unavailable`;
- are visibly labelled as contingency output in `StructuredAIResult`.

Chat failures similarly persist and return an explicit degraded assistant message
instead of returning an opaque 500 after the user's turn has been accepted.

Other changes:

- Farm summaries are cached in Redis by surface/entity/canonical-context digest.
- JSON inserted into prompts uses compact separators instead of indentation.
- Farm context no longer serially calls the full sector builder for every sector.
  It performs bounded aggregate queries for active sectors/plots, latest
  recommendations, reasons, configurations and alerts.
- `AIResponseFeedback` stores bounded-surface thumbs feedback.
- Feedback metrics use bounded labels to avoid user-controlled Prometheus
  cardinality.

### P5 — Product surfaces

New sector tab: `Eficácia da rega`.

It exposes:

- recent `RecommendationOutcome` records;
- recommended dose, actual dose and deterministic dose error;
- qualitative response by probe depth;
- calibration run history;
- application of pending calibration candidates;
- probe-ingestion diagnostics;
- the existing 72-hour change-analysis endpoint;
- a new structured AI explanation of irrigation effectiveness.

New backend surface:

- `POST /sectors/{sector_id}/effectiveness-analysis`

The outcome evaluator now stores:

```json
{
  "probe_response_by_depth": [
    {
      "depth_cm": 30,
      "delta_vwc": 0.03,
      "response": "increase"
    }
  ]
}
```

The farmer UI renders only the qualitative state (`respondeu à rega`,
`sem resposta clara`, `continuou a consumir`). Raw VWC/delta remains available to
the deterministic evaluator and is not used by the LLM to change calibration.

The alerts page now calls the existing alert-explanation endpoint and renders the
validated structured response directly.

### P6 — Per-surface model routing

New optional settings:

- `OPENAI_MODEL_CHAT`
- `OPENAI_MODEL_STRUCTURED`
- `OPENAI_MODEL_SUMMARY`

Blank overrides inherit `OPENAI_MODEL`. Structured calls are tagged by surface:

- recommendation;
- farm summary;
- alert explanation;
- sector diagnosis;
- probe diagnosis;
- chat structured output;
- change analysis;
- irrigation effectiveness.

The live golden-set runner now constructs the production client from settings and
passes the corresponding surface tag. No production model override was selected or
promoted because no live candidate comparison was run in this implementation
session.

## Follow-up: verified evidence cleanup

The first production-facing screenshot of `Eficácia da rega` showed repeated
`Dados` labels and raw internal values including UUIDs, `olive`, and
`olive_flowering`.

Commit `1f7ab1c` fixes the shared evidence contract and renderer:

- Evidence registry is now a curated field-label allowlist instead of falling back
  to a generic top-level label.
- UUIDs, IDs, timestamps, raw VWC response values, unknown fields, and unmapped
  underscore-style engine codes are not citable.
- Crop, phenological-stage, outcome, calibration, data-quality and probe-response
  codes are localized to user-facing pt-PT.
- Probe response `increase` is rendered as `Humidade aumentou`, not the
  recommendation-action meaning `Aumentar rega`.
- Server resolution keeps one item per user-facing label and caps evidence at five
  rows.
- `StructuredAIResult` defensively removes `Dados`, UUIDs, unmapped code strings
  and duplicate labels from cached/legacy responses, and also caps at five.

The intended example is now:

```text
Sector             Turno 1 (S05)
Cultura            Olival
Fase fenológica    Floração
Área               1 ha
Depleção           29,04 mm
```

No JSON path, evidence ID, database UUID, or internal enum key should reach the
farmer.

## Database migration

Autogenerated migration:

```text
db60d960f6ea_add_ai_memory_and_feedback
```

Down revision:

```text
n4o5p6q7r8s9
```

Created tables:

- `chat_conversation`
- `chat_message`
- `field_observation`
- `ai_response_feedback`

`alembic check` returned `No new upgrade operations detected` after upgrading the
development database to this head.

The evidence cleanup in `1f7ab1c` is code-only and adds no migration.

## Verification performed

For `62d3179`:

- Full backend: `666 passed, 10 skipped`.
- Final focused chat/API regression after the full run: `7 passed`.
- Frontend: `83 passed`.
- Frontend lint: clean.
- Next.js production build and type-check: clean.
- Changed Python files: Ruff clean using the repository's FastAPI `B008`
  convention.
- Alembic model/schema check: clean.
- `git diff --check`: clean.

For `1f7ab1c`:

- Focused evidence/assistant/eval-contract backend suite: `35 passed`.
- Final registry-only suite after the effectiveness wording assertion: `8 passed`.
- Full frontend: `84 passed`.
- Frontend lint: clean.
- Next.js production build and type-check: clean.
- Ruff and `git diff --check`: clean.

The full backend suite was not rerun after `1f7ab1c`; the changed backend module was
covered by the focused registry, assistant and eval-contract suites.

The full backend run still reported five non-failing, pre-existing async-mock or
asyncpg cancellation warnings in alert, ingestion and audit tests.

## Review hotspots and known trade-offs

Please explicitly review these points rather than assuming the passing suite
settles them:

1. **SSE semantics.** The endpoint uses SSE transport, but `_run_persisted_chat`
   completes the tool loop before `_reply_chunks()` emits the final reply in
   chunks. It is not token-level OpenAI streaming. Confirm whether transport-level
   progressive delivery satisfies the product requirement or implement true
   streaming without weakening tool-call persistence.

2. **Farm-context parity.** `_build_farm_sector_contexts()` eliminates the 77×
   serial context build, but currently fills `last_irrigation_date=None`,
   `total_irrigation_7d_mm=0.0`, and `probe_live=None`, deriving confidence from the
   recommendation snapshot. Check whether farm-summary prompt behaviour requires
   aggregate live irrigation/probe parity rather than these reduced fields.

3. **Feedback multiplicity.** Ownership and assistant-role checks exist, but there
   is no uniqueness/upsert constraint per user/chat message. Reloading the UI could
   create multiple feedback rows for the same response. Decide whether feedback is
   event-based or should represent one mutable vote.

4. **Field-observation trust.** Unverified observations intentionally enter
   canonical context with `verified=false`. Verify prompts and downstream
   explanations consistently treat them as user claims rather than measured
   facts.

5. **Quota fail-open.** Redis quota failures allow the request and log a warning.
   This preserves availability but weakens cost protection during Redis outages.
   Confirm that this is the intended operational trade-off.

6. **Outcome response query shape.** `_probe_response()` performs two reading
   queries per moisture depth. This is bounded for normal probe depth counts but
   could be converted to a window/aggregate query if outcome evaluation becomes a
   high-volume path.

7. **Evidence allowlist coverage.** Unknown fields are now omitted instead of
   displayed as `Dados`. Review whether every evidence field needed by current
   recommendation, diagnosis, probe, alert, farm-summary, change-analysis and
   effectiveness prompts has an explicit Portuguese label and safe value mapping.

8. **Model promotion.** Routing plumbing is complete, but P6 should not be called an
   evaluated cost optimization until candidate models pass the complete live
   golden set.

## Suggested review commands

From the repository root:

```bash
docker compose run --rm \
  -v "$PWD/backend:/app" \
  backend sh -c \
  "pip install -q -e '.[dev]' && python -m pytest -q --tb=short"

docker compose run --rm \
  -v "$PWD/backend:/app" \
  backend alembic check

cd frontend
npm test -- --run
npm run lint
npm run build
```

Live routing evaluation, only with an intentionally supplied API key:

```bash
cd backend
LLM_PROVIDER=openai \
OPENAI_API_KEY=... \
OPENAI_MODEL=... \
OPENAI_MODEL_CHAT=... \
OPENAI_MODEL_STRUCTURED=... \
OPENAI_MODEL_SUMMARY=... \
pytest -q tests/ai_eval/eval_golden_set.py -s
```

Do not weaken evidence assertions or the probe recommendation guard to make a
candidate model pass.

## Production state and deployment

Git source of truth:

```text
main = origin/main = 1f7ab1c
```

The user supplied a screenshot showing the new effectiveness surface returning a
structured explanation, which strongly indicates the base P3–P6 UI/backend was
deployed. However, no production command output was captured in this session, so
do not treat the deployed commit or Alembic head as independently verified.

Deployment of the follow-up evidence fix was explained but not explicitly
confirmed. Verify on the production host:

```bash
git rev-parse --short HEAD

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.caddy.yml \
  exec -T backend alembic current
```

Expected source commit: `1f7ab1c`

Expected migration head: `db60d960f6ea`

For only the code-only evidence fix:

```bash
git pull --ff-only origin main

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.caddy.yml \
  build backend frontend

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.caddy.yml \
  up -d --no-deps backend frontend
```

Do not use `--remove-orphans`, do not start Compose nginx/certbot, and do not omit
the production-local `docker-compose.caddy.yml`.

## Files to inspect first

Backend:

- `backend/app/ai/evidence.py`
- `backend/app/ai/context_builder.py`
- `backend/app/ai/chat_agent.py`
- `backend/app/ai/openai_client.py`
- `backend/app/ai/tools.py`
- `backend/app/api/v1/chat.py`
- `backend/app/api/v1/field_observations.py`
- `backend/app/services/ai_runtime.py`
- `backend/app/services/chat_memory.py`
- `backend/app/services/recommendation_outcome_service.py`
- `backend/alembic/versions/db60d960f6ea_add_ai_memory_and_feedback.py`

Frontend:

- `frontend/src/components/ai/StructuredAIResult.tsx`
- `frontend/src/components/chat/ChatPanel.tsx`
- `frontend/src/components/sectors/IrrigationEffectivenessPanel.tsx`
- `frontend/src/components/sectors/SectorAnalysis.tsx`
- `frontend/src/app/farms/[farmId]/alerts/page.tsx`
- `frontend/src/app/farms/[farmId]/sectors/[sectorId]/page.tsx`
- `frontend/src/lib/api.ts`

Tests:

- `backend/tests/test_ai/test_evidence_registry.py`
- `backend/tests/test_ai/test_ai_runtime.py`
- `backend/tests/test_ai/test_context_v2.py`
- `backend/tests/test_ai/test_openai_client.py`
- `backend/tests/test_ai/test_tools.py`
- `backend/tests/test_api/test_chat_endpoint.py`
- `backend/tests/test_services/test_recommendation_outcome.py`
- `frontend/src/components/ai/__tests__/StructuredAIResult.test.tsx`
- `frontend/src/components/chat/ChatPanel.test.tsx`
- `frontend/src/components/sectors/__tests__/IrrigationEffectivenessPanel.test.tsx`
