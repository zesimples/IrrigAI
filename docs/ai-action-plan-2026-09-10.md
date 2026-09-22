# IrrigAI AI action plan — 2026-09-10

Status: proposed implementation plan. This document authorises no deployment or
external notification. No application changes are included in this planning task.

Objective: first make AI answers consistently grounded, current, and understandable;
then connect the existing capabilities into daily decisions, irrigation follow-up,
scenario comparison, field memory, troubleshooting, and operational planning.

## Starting point and boundaries

The reviewed checkout already implements scoped persisted chat, read tools,
proposed actions requiring user confirmation, structured evidence, field observations,
AI feedback, quotas, fallback responses, model routing, a canonical sector context,
stress projection, and irrigation outcomes. Extend these components rather than
rebuilding them. The review was of source code, not a production smoke test.

Preserve throughout:

- Numerical agronomy, CC/refill calibration, and irrigation decisions remain in
  deterministic engine/services. Preserve existing configured calibration policies;
  this roadmap does not change automatic application settings.
- Water-entry detection stays probe-only. Flowmeters, weather, and logged events may
  inform a separate outcome investigation, never the detector's inputs. Automatic
  water-entry markers remain unlogged until user classification.
- Tenant access goes through `access.py`; current operations use active-record
  selectors. Archived history is accessible only in an explicitly historical view.
- AI proposals require confirmation before mutation. Confirmation is revalidated
  against current permissions, scope, and resource state.
- User-facing copy is PT-PT, with existing decimal formatting and meaningful units.
- Build on the existing stack. No model migration, vector database, controller
  integration, or replacement crop model is a prerequisite.

## Delivery order

| Release | Work | Depends on | Completion gate |
| --- | --- | --- | --- |
| A0 | Regression cases and measurements | None | Reproducible baseline for each identified gap |
| A1 | Confidence, weather scope, observation access | A0 | All surfaces use the correct scope and honest data-quality language |
| A2 | Grounded chat and durable proposed actions | A1 | Validated answer contract and reliable confirmation lifecycle |
| A3 | Analysis freshness and responsive streaming | A2 | Current answers, visible progress, recoverable interruptions |
| A4 | Expanded evaluations and pilot verification | A1–A3 | Foundation release gate passes |
| B1 | Daily action briefing | A4 | Grower can identify and open today's priority tasks |
| B2 | Automatic irrigation follow-up | B1 | Outcome cards distinguish delivery, response, and insufficient evidence |
| B3 | Interactive scenario comparison | B2 | Deterministic, reproducible comparisons with explicit assumptions |
| B4 | Editable field memory and voice notes | B3; reuses A1/A2 | Confirmed observations survive conversations and respect expiry |
| B5 | Guided fault investigation | B2 and B4 | Evidence-led investigation can be resumed and resolved |
| B6 | Farm-wide operational planning | B3–B5 | Feasible plans respect configured resource constraints |

This is the default implementation sequence. Each release is independently
reviewable. Reassess later priorities using pilot feedback; do not start feature
implementation before A4 passes. Effort should be estimated per release after its
schema and acceptance cases are reviewed, rather than committing to calendar dates
without capacity or a measured baseline.

## Part A — Address existing gaps

### A0 — Establish regression coverage and a baseline

1. Add focused reproductions for: inflated confidence; sector chat using the wrong
   weather scope; missing field notes in chat; unsupported chat claims; stale stored
   analyses; delayed first streaming output; and repeated action confirmation.
2. Record time to first progress event, first validated answer content, and complete
   answer separately. Extend existing request/token/fallback metrics with surface
   and bounded outcome labels; keep tenant identifiers out of metric labels.
3. Capture anonymised contexts for single-station and multi-station farms, missing
   or stale probes, conflicting notes, and irrigation outcomes with incomplete data.
4. Run relevant existing backend/frontend suites and record pre-existing failures
   separately. Extend the existing evaluation harness instead of starting a new one.

Acceptance: every identified gap has a regression case or an explicit reproducible
measurement; baseline results are recorded before implementation.

Primary areas: `backend/tests/test_ai`, `backend/tests/test_api/test_chat_endpoint.py`,
`backend/tests/ai_eval`, `frontend/src/components/chat/ChatPanel.test.tsx`,
`backend/app/metrics.py`.

### A1 — Correct confidence and context scope

1. Define separate concepts for engine confidence, input quality/freshness, and
   explanation availability. Remove the probe guard's artificial minimum of 75%.
   Agreement with the engine must not increase confidence or hide missing data.
2. Preserve the engine's actual reason for skip/defer. Do not automatically describe
   every non-irrigation decision as sufficient soil reserves or every situation as
   low risk. Distinguish irrigation urgency from sensor reliability.
3. Make displayed confidence derive from documented deterministic inputs. Deprecate
   model-authored percentages through a compatible API transition; prefer a short
   qualitative explanation when no meaningful numerical score exists.
4. Resolve chat weather through sector → plot → existing shared weather resolver.
   Return source scope and timestamps. Farm-wide requests must label representative
   weather and avoid implying one station describes every plot.
5. Add a scoped read tool for active field observations, including source, observed
   time, expiry, and verification. Retrieve it when answering relevant sector
   questions; preserve disagreement between an observation and sensor data.
6. Keep tool outputs bounded and reuse canonical context/shared resolvers. Avoid
   rebuilding a complete sector context repeatedly for independent block reads.

Acceptance: two sectors with different stations receive their own weather; fallback
behaviour matches the engine; stale or missing data cannot gain confidence through
the probe guard; a saved note is available in relevant chat; expired notes are not
presented as current facts. All access and active-record tests pass.

Primary areas: `backend/app/ai/assistant.py`, `tools.py`, `context_builder.py`,
`backend/app/schemas/ai.py`, `frontend/src/components/ai/StructuredAIResult.tsx`.

### A2 — Ground chat and persist the proposed-action lifecycle

1. Extend the chat response contract with server-resolved evidence, data timestamps,
   recommendation identity, and context version. Attach citations to the particular
   statement they support, with links to the relevant sector/chart where available.
2. Return actionable irrigation advice in typed fields populated or checked against
   engine outputs. Render doses, units, and decisions from verified fields. Validate
   citations and numerical claims; unsupported claims trigger a bounded repair or a
   deterministic fallback. A valid evidence ID alone does not prove the prose follows
   from that evidence; semantic checks and evaluation remain necessary.
3. Treat user notes and retrieved text as data, not instructions. Add adversarial
   cases for notes that request invented values or actions outside the selected scope.
4. Persist proposed-action status, including pending, succeeded, failed, cancelled,
   and invalidated. Use a server action identity and idempotency protection.
5. Recheck the recommendation/version and authorisation at confirmation time. A
   superseded recommendation requires a fresh proposal. Failures remain retryable
   where appropriate; a reopened conversation shows the actual outcome.
6. Persist action results as conversation events available to the next turn. Refresh
   affected UI data after success. Unify quick-action results with conversation
   persistence so their context, degraded status, and feedback are retained.

Acceptance: chat cannot present a conflicting dose/action as an engine recommendation;
citations resolve within the authorised context; retries do not duplicate writes;
failed actions are not shown as completed; reopen preserves action status. Evidence
and degraded-state rendering work in both streaming and non-streaming chat.

Primary areas: `backend/app/ai/chat_agent.py`, `tools.py`, `evidence.py`,
`backend/app/api/v1/chat.py`, `backend/app/services/chat_memory.py`, chat schemas/models,
`frontend/src/components/chat/ChatPanel.tsx`, `frontend/src/lib/api.ts`.

Data change: additive migration for evidence/provenance and durable action records,
with compatibility for existing conversations. Define legacy pending-action handling
explicitly; never assume an old proposal was executed.

### A3 — Make answers current and chat responsive

1. Bind stored analyses to scope, recommendation ID, relevant input digest, generation
   time, and prompt/contract version. Include timestamps of source observations, not
   request-time noise that would invalidate every cache lookup.
2. On reopen, compare versions. Mark obsolete results as historical and offer refresh;
   do not present them as advice for the current recommendation. Apply the policy to
   sector, probe, flowmeter, and summary surfaces. Scope local caches by user and
   clear them on logout; preserve explicit historical views.
3. Replace chunking after full completion with an event-producing chat orchestration.
   Emit progress such as reading sector data immediately, followed by validated
   answer blocks as they become available. Keep tool arguments and unchecked
   agronomic claims out of visible deltas. Do not stream raw tokens that bypass A2.
4. Add cancellation, timeout, disconnect, retry, and navigation handling. Persist
   completion reliably and distinguish interrupted responses from completed ones.
   Test through the deployed proxy, not only an in-process SSE client.
5. Provide a conversation picker using the existing list/detail/delete endpoints.
   Historical messages show their original date and scope; follow-up questions fetch
   current data rather than treating old replies as current evidence.

Acceptance: changes in recommendation, calibration, notes, or relevant readings
invalidate affected advice; switching users/scopes cannot show the previous user's
cache. A delayed fake provider demonstrates a progress event before completion and
incremental validated content. Disconnect/retry creates no duplicate completed action.

Primary areas: `backend/app/api/v1/chat.py`, `backend/app/ai/chat_agent.py`, client
adapter, `backend/app/services/ai_runtime.py`, `frontend/src/lib/api.ts`,
`ChatPanel.tsx`, `SectorAnalysis.tsx`, other cached analysis surfaces.

### A4 — Evaluate and release the foundation

1. Expand the live harness beyond recommendation/probe/farm summary to multi-turn
   chat, alert explanation, change analysis, effectiveness, memory retrieval, and
   action lifecycle. Add cases for all Part A regressions.
2. Preserve deterministic tests in normal CI. Use controlled live evaluations for
   prompt/contract/model changes, with a bounded run budget. A skipped live run or
   degraded fallback is not evidence of model quality.
3. Evaluate factual support, engine agreement, correct scope, useful next actions,
   uncertainty handling, PT-PT quality, latency, and token consumption. Review
   representative answers with an agronomist and growers; document qualitative
   failures rather than reducing everything to a single score.
4. Add meaningful feedback reasons: wrong data, stale answer, unclear explanation,
   and unhelpful next step. Tie feedback to response/context versions.
5. Pilot the foundation release on representative farm configurations. Keep the
   deterministic recommendation UI available during AI outages.

Foundation gate: all critical scope, engine-authority, action-idempotency, freshness,
and confidence regression cases pass; no unresolved critical failures in the live
release set; migration and proxy streaming checks pass. Record actual results and
remaining limitations. Choose latency targets from A0 measurements and pilot needs.

## Part B — Implement user-facing improvements

### B1 — Daily action briefing

User outcome: identify what needs attention without opening every sector.

- Build a deterministic briefing service over recommendations, stress projections,
  owned alerts, data quality, and material changes since the last briefing.
- Define separate item types: irrigation decision, field inspection, configuration,
  and monitoring. Rank with explicit rules; missing data creates a verification task,
  never an invented irrigation instruction.
- Render a short ranked list on the farm dashboard with reason, source freshness,
  and a deep link. AI explains the supplied items; it does not determine priority.
- Add “Why?” and “What changed?” actions that open chat with the item identity and
  current scope. Group related alerts while preserving producer ownership.
- Cache by context version. Use existing worker/locking patterns for scheduled
  preparation and refresh on material changes, with explicit background AI budgets.
- Start in-app. Add notification preferences and quiet hours before external delivery.

Acceptance: every item traces to current inputs; ranking is reproducible; unchanged
inputs create no duplicate tasks; a failed AI call still leaves a usable briefing.
Measure time to identify a priority, item opens, and completed follow-up actions.

Implementation areas: new briefing service/schema, existing dashboard API/page,
canonical farm aggregates, scheduler. Persist briefing snapshots/task state if needed
for change tracking and completion; do not rely on the response cache for history.

### B2 — Automatic irrigation follow-up

User outcome: understand delivery and observed soil response after irrigation.

- Extend `recommendation_outcome_service.py` with explicit matching provenance,
  evaluation maturity, event groups, and telemetry coverage. Support split irrigation
  without double counting manual and detected representations of the same event.
- Preserve recommendation adherence as one view. Provide a separate event-led view
  for observed irrigations with no accepted recommendation; do not fabricate a match.
- Distinguish pending, adequate evidence, ambiguous association, and insufficient
  telemetry. Absence of recorded flow must not establish zero irrigation when the
  meter was unavailable.
- Evaluate delivery against the recommendation and response by depth separately.
  Match comparison events by documented conditions and a minimum sample requirement.
  Describe observed differences without claiming causation or crop benefit.
- Update follow-up cards after sufficient post-event data arrives. Reconcile after
  late readings; notify only on a material new finding. Add briefing links and an
  inspection action for unresolved discrepancies.

Acceptance: split, overlapping, duplicate, delayed, and missing-data fixtures produce
stable outcomes. Reprocessing is idempotent. Delivery compliance is not labelled
agronomic success. The probe-only detector remains unchanged.

Data change: likely outcome-to-event association and evaluation-version/maturity
fields. Preserve existing historical outcomes and avoid destructive backfills.
Measure evaluable-event coverage, matching errors, and follow-up usefulness.

### B3 — Interactive “what if?” planning

User outcome: compare the current plan with delaying irrigation or changing dose.

- Add a pure scenario engine/service reusing water balance, effective soil bounds,
  rainfall treatment, and stress projection. Inputs include a fixed baseline version,
  horizon, proposed irrigation time/dose, and explicit weather assumptions.
- First support the existing 72-hour horizon and a small set of side-by-side options:
  current plan, delay, alternative dose, and forecast rain absent. Treat these as
  assumptions, not calibrated probabilities or precise crop-yield predictions.
- Render depletion trajectories, threshold crossing, total water, and limitations.
  Show unavailable quantities when inputs cannot support calculation.
- Let chat translate a question into typed scenario inputs, ask for an essential
  missing value, invoke the numerical service, and explain the returned comparison.
- Keep simulations separate from active recommendations. Applying an option requires
  a confirmed action and baseline revalidation through A2.

Acceptance: scenarios are reproducible and side-effect free; zero-change matches the
shared baseline calculation within documented tolerance; unit, mass-balance, horizon,
and missing-input cases pass. Validate representative cases with agronomic review.

Implementation areas: engine/service, typed scenario API and read tool, comparison
component, saved scenario provenance if users need history. Measure task completion
and assumption comprehension; do not claim savings from simulations alone.

### B4 — Editable field memory and voice notes

User outcome: record field knowledge once and retrieve it in later conversations.

- Extend A1's observation access into a visible memory manager with edit, expiry,
  verification, supersession, and removal. Separate temporary observations from
  durable configuration and operational constraints.
- Add a propose-save-observation action. Extract dates, scope, and structured values
  from conversation, show a reviewable draft, and save only after confirmation.
  “Pump unavailable until Friday” becomes a dated operational constraint; it does
  not change soil bounds or silently alter numerical recommendations.
- Retrieve active relevant records across conversations with their provenance.
  Add a bounded conversation summary if needed, but keep confirmed structured
  records as the source of truth and refresh current numerical facts from tools.
- Add optional voice transcription into the same editable draft, with cancellation
  and clear recording state. Choose provider, retention, and cost limits before
  implementation; the text path remains available.
- Handle contradictory and expired notes explicitly. Consider photo attachment only
  after the note workflow is validated, initially as documentation for inspection.

Acceptance: a confirmed note is retrieved in a new conversation; edits supersede old
versions; expiry works in farm-local time; cancelled drafts are not stored; another
tenant cannot retrieve them; voice misrecognition can be corrected before saving.

Data change: observation revision/supersession and typed operational constraints as
needed, reusing existing verification and authorship. Measure correction rates and
successful retrieval, not the number of stored memories.

### B5 — Guided fault investigation

User outcome: work through an unexplained signal and keep track of the inspection.

- Start with three workflows: stale/implausible probe readings, unusual delivery,
  and delivery with weak or inconsistent depth response.
- Assemble facts using existing diagnostics, alerts, outcomes, calibration, and
  confirmed field notes. Compute discrepancy flags deterministically; AI explains
  possible causes and selects a useful follow-up from supported checks.
- Separate observed facts, hypotheses, and unresolved questions. Avoid unsupported
  probability percentages or declaring a specific equipment fault from one signal.
- Persist the investigation, completed checks, next step, and resolution. Allow
  resumption from a briefing or chat. Export an agronomist-readable report on demand.
- Reconcile investigation tasks without taking ownership of another producer's
  alerts. New data may invalidate a hypothesis without rewriting historical findings.

Acceptance: insufficient evidence leads to an explicit check; conflicting evidence
is retained; resolved investigations do not reopen without a new qualifying change;
the report shows provenance and observations separately from hypotheses.

Data change: scoped investigation/check records. Measure completed investigations,
time to resolution, and grower corrections to suggested explanations.

### B6 — Farm-wide operational planning

User outcome: produce a feasible irrigation sequence across sectors.

- Add validated configuration for shared pumps/resources, simultaneous-sector rules,
  flow/capacity limits, operating windows, and available water. Collect energy tariffs
  only if cost optimisation is included and reliable tariff inputs exist.
- Combine scenario outputs and confirmed constraints in a deterministic scheduling
  service. Define hard constraints and a documented priority objective before choosing
  an optimisation implementation. Start with a fixed planning horizon.
- Make infeasibility explicit: identify the blocking constraint and affected sectors.
  AI explains the plan and trade-offs; it cannot relax constraints silently.
- Show a timeline, per-sector allocations, resource use, and assumptions. Validate
  altered plans after every edit or changed input. Preserve versioned draft/confirmed
  plans and the confirmation lifecycle.
- Initial delivery is a reviewed plan and export. Irrigation-controller execution
  requires a separate integration scope and explicit product decision.

Acceptance: simultaneous capacity, water limits, windows, equipment outages, and
infeasible combinations have deterministic tests. Compare small instances against
known feasible/optimal examples. Do not label a heuristic result globally optimal.

Data change: shared resources, constraints, plan versions, and allocations. Measure
feasible-plan rate, manual changes, and delivery adherence. Estimate cost/water savings
only with a documented baseline and sufficient observed data.

## Verification and rollout for each release

1. Keep changes focused by subsystem; pair schema changes with additive migrations
   and compatibility handling. Use repository migration conventions and verify the
   actual current Alembic head rather than relying on older handoff documents.
2. Run targeted regressions during development. At the release gate, run relevant
   Docker backend tests, frontend unit tests, lint/build, and selected Playwright
   flows. Cover auth/ownership, ingestion, and engine changes as required by AGENTS.md.
3. For engine changes, compare against fixed numerical fixtures and document any
   intended change in behaviour. For AI contract changes, run the expanded evaluation
   set; distinguish model failures, provider failures, and skipped runs.
4. Verify upgrade on a test database, compatibility with historical records, worker
   reconciliation/retry behaviour, and resource/cost limits. Keep a per-feature
   disable path; rollback must not require deleting observations or action history.
5. When deployment is requested, follow the current three-file Caddy procedure:
   build backend/worker/frontend, migrate, then recreate those services only using
   `up -d --no-deps`. Do not start nginx/certbot or use `--remove-orphans`. Check
   loopback/public health, worker logs, migrations, and representative user flows.
6. Record screenshots for UI changes, test/evaluation results, migration notes,
   measured latency/cost changes, limitations, and pilot feedback in each handoff.

## First implementation batch

Start with A0 and A1 as the first focused batch: reproduce the issues, correct
confidence semantics, align chat weather with sector scope, and expose field notes
through a scoped read tool. Then implement A2's response/action contracts before
changing streaming or cache behaviour. Complete A4 before beginning B1.

No outstanding user choice blocks Part A or the in-app B1 design. Voice-provider
selection, external notification channels, and operational optimisation objectives
can be resolved at their respective phase boundaries with concrete options and
pilot evidence.
