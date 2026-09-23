# Independent review of A0–A4 (`05ea921`) — 2026-09-23

Reviewer: Claude Code, four parallel reviewers (security/tenant-isolation, AI
grounding layer, data layer/migrations, frontend), each adversarial and read-only.
Nothing in this review trusts `docs/claude-a0-a4-review-fixes-2026-09-22.md`'s
self-report; every finding below was traced in the code, and the two marked
**verified here** were reproduced directly.

> **Resolution (same day):** all six blocking defects are **fixed and committed** — see [Fixes applied](#fixes-applied-2026-09-23) at the end.
> The "Important" and "Lower" findings remain open.

**Verdict at review time: do not deploy `05ea921` to production as it stood.** Six defects are
blocking. None is architectural — the structure of the work is sound and the parts
most likely to be wrong (tenant isolation on the new LLM tool surface, the
concurrency model for confirmable actions, the two migrations) came back clean.
The blocking defects are concentrated in the grounding validator's regex gate and
in one frontend counter.

---

## Blocking

### B1. A negation anywhere earlier in the sentence disables every engine-authority check
`backend/app/ai/chat_grounding.py:116-126` (`_advises`), gating `:378`, `:415`, `:449`

**Verified here** by executing the module's own patterns:

| model reply | directive detected? |
|---|---|
| `"Hoje não choveu, por isso deves regar 12 mm."` | **False** |
| `"Não há previsão de chuva, por isso aplica 12 mm hoje."` | **False** |
| `"Sem rega nas últimas 48 horas, recomendo regar hoje."` | **False** |
| `"Deves regar 12 mm hoje."` | True |

`_CLAUSE_SPLIT_RE` breaks only on `.;!?\n` and `mas|porém|contudo`, so a
comma-joined sentence is a single clause, and `_NEGATED_CLAUSE_RE` matching
anywhere before the verb makes `_advises` return `False`. `engine_conflict`,
`engine_dose` and `missing_engine` are all gated on it, so they silently do not
run. The answer is marked `validation_status="validated"`, `degraded=false`, no
banner, and persisted.

Failure: engine returns `skip`; model answers *"Hoje não choveu, por isso deves
regar 12 mm."* (12 mm being `depletion_mm`, so the number grounds). The grower is
told to irrigate against the deterministic decision, with no indication anything
is unverified.

### B2. A dose claim is grounded against any mm field in the turn, and the commonest phrasing is not matched
`chat_grounding.py:92-97`, `:195-209`, `:414-426`

`_IRRIGATE_DIRECTIVE_RE` matches `dotação recomendada` but not `dotação de`,
`dotação sugerida`, `dose de`, `lâmina de`. Independently, `GroundedFacts.supports()`
matches a claim against the union of all 14 `_MM_KEYS` across every tool result of
the turn (`taw_mm`, `depletion_mm`, `et0_mm`, `rainfall_mm`, …) — nothing binds a
dose claim to `irrigation_depth_mm`.

Failure: with `taw_mm=120.0` and engine `action="skip"`, the reply *"Recomendo uma
dotação de 120 mm para hoje."* validates. The model has invented a dose from the
sector's total available water, against a skip decision, and it ships unflagged.
120 mm is also the scale of the known uncapped-dose problem, so it reads plausibly.

### B3. The skip direction is barely detected — suppressing irrigation is essentially unguarded
`chat_grounding.py:98-102`, consumed at `:459`

`_SKIP_DIRECTIVE_RE` catches `não regues/regar`, `salta a rega` (imperative only),
`adiar/dispensar a rega`. **Verified here**: `"No Olival Norte podes saltar a
rega."`, `"não é preciso regar hoje"` and `"podes esperar"` all return False.

So the guard is asymmetric: irrigating against a `skip` is partly checked (when B1
does not suppress it), while *not* irrigating against an `irrigate` is not checked
at all. Under-irrigation on a sector at high depletion is the more expensive
agronomic error of the two.

### B4. Loading a conversation mid-request deadlocks the panel after a committed write
`frontend/src/components/chat/ChatPanel.tsx:98` vs `:325`, `:337`

**Verified here.** `loadConversation` does `++generationRef.current`. Every in-flight
operation guards its `finally` with `if (generation === generationRef.current)`, so
moving the counter underneath one means `setLoading(false)` never runs — and unlike a
real scope change, nothing else recovers it (the reset effect only fires on a
`[farmId, sectorId]` change).

Failure: the user clicks **Confirmar** on a `run_calibration` proposal, then opens
**Histórico** while it is in flight. The server executes the write and commits.
`confirmAction` returns early, `onActionCompleted` never fires, the card never
updates, and the panel is stuck on "A pensar…" with the input disabled and a ✕ that
aborts an already-settled controller. **The user concludes the action did not run,
with the soil-bounds write already committed.** The only escape is closing the panel.
No test covers it.

### B5. Confirming a chat calibration destroys an agronomist's manual soil edit, undisclosed
`backend/app/services/probe_calibration_service.py:189-191` via `chat_actions.py:330-338`;
rendered at `ChatPanel.tsx:531`

`run_manual` sets `profile.is_customized = False` and moves the live CC/refill line.
The only thing shown before *Confirmar* is `proposed_action.summary` — for this type
the fixed sentence "Correr a calibração inteligente do setor." The action type, the
sector, and the fact that manual bounds will be overwritten are never rendered.

Failure: an agronomist hand-sets FC/PMP on a sector (`is_customized=True`). A grower
later asks about that sector, the model proposes a calibration, the grower reads one
bland sentence and confirms. The manual numbers are gone and the next 05:00 UTC run
uses the probe-derived envelope. The dedicated `AiCalibrationButton` at least reports
the real "CC 17→24" transition; this path reports nothing until after the write.

### B6. A model-authored `depth_mm` is persisted with no bounds check
`backend/app/ai/tools.py:524-531` → `chat_actions.py:298-300`

`_propose` copies the model's raw `args.get("depth_mm")` into
`params["custom_depth_mm"]`; `_execute` does `float(depth)` with no range check.
Every other model-supplied number in `tools.py` goes through
`_bounded_int(…, minimum, maximum)` — this is the only one that becomes a persisted
agronomic value, and the only one unvalidated. `depth_mm` is not in the tool's
`required` list either, so an omitted value renders "para None mm" while still
setting `is_accepted=True`.

---

## Important (not blocking, fix soon)

- **Histórico picker leaks another sector's transcript.** `chatApi.conversations(farmId)`
  returns every conversation in the farm; rows are labelled only `"Conversa · sector"`
  without naming the sector, and `loadConversation` re-scopes nothing client-side. A
  follow-up then 409s with the **English** string `"Chat conversation sector scope does
  not match"` rendered verbatim to a PT user. `ChatPanel.tsx:442-460`,
  `chat_memory.py:34`. This re-opens, as a feature, the cross-sector confusion `e6959da`
  closed — the two guards from that cycle did survive and are test-pinned.
- **The confirm card never shows `params`.** `ProposedActionOut` carries `type` and
  `params`; the UI renders only the model-written `summary`. The user confirms a
  mutation described in whatever sentence the LLM chose. `ChatPanel.tsx:531`. Compounds
  B5 and B6.
- **`confirm` runs the full pipeline on the request path with no timeout**, holding the
  action row lock for the duration (`chat.py:752-790`). This is the 2026-07-28 sweep
  incident in miniature: the Next proxy drops at ~5 min, the user re-clicks, the retry
  parks on the row lock consuming a pool connection. The write itself is correct; the
  failure mode is availability. The repo's own precedent is 202 + poll, which
  `ChatActionOut` and `GET /chat/actions/{id}` already support.
- **Failed actions show English HTTP status text and discard the real reason.**
  `POST /chat/actions/{id}/confirm` returns 422 with a bare `ChatActionOut` that has
  `error_detail` but no `detail` key, so `api.ts:147`'s `body.detail ?? res.statusText`
  yields `"Unprocessable Entity"` and drops `body.error_detail`. A Watermark-sector
  calibration failure renders *"A acção falhou … (Unprocessable Entity)"* instead of
  `diagnose_unavailable`. Related: `RESOLVED_ACTION_STATUSES` includes `confirmed`
  ("A executar…"), which a 409 can pin permanently with no buttons and no polling.
- **`ingest_probe_readings_sync` defaults `farm_id=None`** (`ingestion.py:816-843`),
  which defeats the recovery fix on that path — `active_probes_stmt(None)` filters only
  the archived chain, then `.scalar_one_or_none()` raises `MultipleResultsFound` when two
  active farms share a provider id (the commit's own test constructs exactly that case).
  The async path is safe by caller discipline only. Make `farm_id` required.
- **Two scripts still resolve probes globally by `external_id`** —
  `backend/scripts/add_conqueiros_depths.py:39-41` and
  `backend/scripts/onboard_innoliva.py:240-242`. Post-recovery these can bind to an
  **archived** replacement probe and create `ProbeDepth` rows there, leaving the active
  probe with none — and `ingestion._store_readings` then silently skips every reading for
  that sector. Conqueiros is one of the three recreated farms. `sync_probe_depths.py` and
  `flowmeter_ingestion.py:238-242` ignore archived hierarchy too.
- **Farm-level measurements are ungroundable in any multi-sector turn.**
  `collect_facts` discards the `unscoped` bucket when >1 sector is grouped, and
  `get_weather` has no top-level `sector_id`. A correct *"Prevê-se 8 mm de chuva"* —
  exactly what the tool returned — comes back `ambiguous_scope`, costs a repair
  round-trip, then falls back to text containing no weather at all.
  `chat_grounding.py:262-271`, `:342-365`. Two-line fix.
- **Three card surfaces now permanently report "Confiança por determinar".**
  `_complete_structured` applies `derive_answer_confidence(context)` to every surface,
  but `alert_explanation` and `farm_summary` pass contexts carrying neither
  `engine_decision` nor `probe_state`, so the score is a constant 0.32 and a fixed
  bullet is appended to every one — including alerts derived from a `high`-confidence
  recommendation. `assistant.py:647`, `answer_confidence.py:110-147`.
- **A grounding failure is reported to the user as an AI outage.** `chat_agent.py:266`
  sets `degraded = (status == "fallback")`, so the panel renders both *"Resposta
  determinística…"* and *"Resposta de contingência — o serviço de IA não estava
  disponível."* The second is false; it sends people chasing a provider incident.
- **The only test that exercises the real SSE path is unreachable.**
  `playwright.config.ts` adds `testIgnore: "**/chat-review.spec.ts"`, and
  `playwright.chat-review.config.ts` is referenced by no npm script and no CI job. Given
  that the whole point of the `no-transform` header was a buffering proxy, this is the
  one regression guard that matters and nothing runs it.

## Lower

`engine_dose` false-positives on a correctly-labelled depletion figure in the same
clause (`"Deves regar hoje: a depleção já atingiu 12 mm."` → flagged); `_NUMBER_PATTERN`'s
leading `[+-]?` parses the range `"12-15 mm"` as −15 mm; `GroundedFacts.quoted` /
`add_quoted` / `is_measured` are populated and never read, so the user-amount protection
is not a mechanism; the live eval re-runs the same heuristic it is testing and imports
the product's `_advises`, inheriting B1 verbatim; quick-action turns are `validated` live
and `fallback` after reload; "Nova" mid-stream does not bump the generation counter, so
the old `conversation_id` is restored into the supposedly-new conversation; cancelling a
stream discards text already read; the ✕ button is inert for `runQuickAction` and
`confirmAction`; the `SectorAnalysis` field-note double-persist is unfixed and the new
"Actualizar análise" button adds a second trigger for it; `unknown` (0.40) outranks `low`
(0.35) in the confidence table; `_sector_provenance` builds the canonical context three
times per card request; chat-triggered writes are audited with `user_id=NULL`; the
`irrigai_ai_response_feedback_total` label set changed, which breaks existing Grafana
panels; two new `recommendation_id` FKs are `ON DELETE SET NULL` with no index, making
bulk farm-subtree deletes quadratic; `_open_turn` releases its advisory lock at `commit()`
before taking the row lock, leaving a small double-runner window.

---

## Checked and clean

These are the areas most likely to have been wrong, and they hold up:

- **Tenant isolation on the new LLM tool surface.** Every tool routes through
  `AccessController`; `execute_tool:306-309` rejects model-supplied `farm_id`/`sector_id`
  that differ from conversation scope *before* dispatch; `_require_sector_scope` re-checks
  `sector_in_farm`; `_propose` re-binds to the recommendation's own sector. No hand-rolled
  query bypasses the controller.
- **Confirm/cancel ownership and concurrency.** `get_owned_action` filters
  `id AND farm_id AND user_id` (404 for both missing and cross-tenant). The claim is a
  conditional `UPDATE … RETURNING`, genuinely atomic under READ COMMITTED — not a Python
  check that would race across `uvicorn --workers 4`. `_revalidate` re-checks scope at
  confirm time.
- **Both migrations are production-safe.** No table rewrite, no hypertable touched, no
  constraint a pre-existing row can violate; `status` uses a PG11+ fast default. This is
  not a repeat of the `37eabad4a828` hazard. Downgrades correctly reverse upgrades.
  Model/migration agreement verified column by column.
- **The probe recommendation guard still fires** and was broadened, not bypassed; it now
  quotes engine-authored `RecommendationReason.message_pt` rather than inventing text.
- **Confidence is genuinely deterministic** — `confidence_score` was removed from the
  model-facing schema, the old `max(…, 0.75)` floor is gone, and the minimum reachable
  score is 0.23.
- **Provenance handles the same-row/same-timestamp case**, because the version hashes
  context *content*, not timestamps.
- **The PT structured-output contract is untouched** and still forces pt-PT and registry
  evidence IDs. The `fmt_pt(…).rstrip("0")` truncation bug does not recur.
- **The two `e6959da` ChatPanel race fixes survived** and are pinned by tests that fail
  if the guard is deleted.
- **SSE reader buffering is correct** across split chunks and multi-byte characters.

---

## Suggested minimum fix set

B1–B3 are one defect class: the engine-authority checks are gated on a regex predicate
that is both too narrow (phrasing) and too easily suppressed (negation). Patching the
regexes invites the same bug back in a different sentence. The robust shape is to invert
the gate — run the engine-action check on every reply regardless of whether a directive
was detected, defaulting to "stance unproven → repair" rather than "no directive →
pass", and bind `supports()` per-field rather than per-unit so a dose can only ground
against `irrigation_depth_mm`.

B4 is a one-line fix (do not bump `generationRef` in `loadConversation`; use a separate
guard, or clear `loading` unconditionally). B5 and B6 are server-built summary text plus
a bounds check. None of the six is large.

---

## Fixes applied (2026-09-23)

All six blocking defects fixed test-first.

- **B1–B3 — one fix, not three regex patches.** A negation now inverts a directive only
  when it is *attached*: every word between them must be modal/advice vocabulary
  (`_NEGATION_BRIDGE_RE` — `é`, `necessário`, `preciso`, `deves`, `vale a pena`, `antes
  de`…). An unrecognised word (`choveu`) or any punctuation means the negation belongs to
  another proposition. That is the high-recall direction, which is the safe one: a false
  positive costs one repair ending in the deterministic fallback; a false negative ships a
  contradiction of the engine marked `validated`. And **a negated irrigation directive is
  now itself a skip stance** (`_advises_skip`), which is what closes B3 — "Não é preciso
  regar hoje" is advice not to irrigate. Dose-labelled numbers (`dotação`, `dose`,
  `lâmina`, `aplica*`, `regar`, `rega`) now bind only to the engine dose or an applied
  amount (`_DOSE_KEYS`), never to any mm field in the turn; `engine_dose` requires advice
  *and* a dose label, so a measurement quoted beside advice is no longer read as the dose.
  The six negated phrasings the 2026-09-10 fix protected all still pass — that
  over-correction history is why the regexes were not simply reverted. The eval harness
  imports `_advises` with an unchanged signature, so the live eval inherits the fix.
- **B4.** `loadConversation` now refuses while a send, quick action or confirmation owns
  the transcript (`busyRef`, set and cleared through one `setBusy` helper — a ref because
  `loadConversation` is a `useCallback` closing over a stale `loading`). Histórico, Nova
  and picker rows are disabled while busy. Side effect: this also closes the "Nova
  mid-stream restores the old conversation id" item in the Lower list.
- **B5.** The server builds the calibration summary: it names the sector, and when the
  *resolved* soil source is `scp_override` it states "Atenção: isto substitui os limites
  de solo definidos manualmente (CC/PMP)…". Keyed on the resolved source, not the raw
  `is_customized` flag, per the rule in `CLAUDE.md`.
- **B6.** `validate_override_depth` bounds the model's `depth_mm` to a finite
  `[0, 200]` mm (a sanity bound, not an agronomic one), enforced at proposal **and again
  at execution** — params sit in a DB row between the two. `depth_mm` is now `required`
  in the tool schema. Before the fix, confirming `-40`, `1e9`, or no depth at all returned
  `succeeded`.

**Verification** (both DB URLs pinned to `irrigai_ai_review_20260921`, isolated Redis,
`current_database()` checked by the runner — development never touched): full backend
**960 passed, 10 skipped, 0 failed**; affected suites re-run on the final code after
formatting, **290 passed**; frontend **142 passed**, ESLint clean, `tsc --noEmit` **0
errors** (the old 20-error baseline no longer exists); Ruff lint + format clean on all
changed files; `git diff --check` clean. Two existing unit tests needed the new soil-bound
resolver stubbed on their mocked `db`; their assertions are unchanged.

One regression was caught *during* the fix and is worth knowing about: `sendMessage`
cleared `loading` through a block-form `finally` the first pass missed, which would have
left `busyRef` stuck and silently disabled Histórico after any chat turn. A dedicated test
(`allows switching conversations again once the turn has finished`) now pins it.

**Live evaluation** (`run_isolated_review live-eval`, real OpenAI model routes, same
isolated DB and Redis): **28 passed, 0 skipped** — all 23 card cases and all 5 multi-turn
chat cases. The harness fails any degraded response, so no real model answer fell through
to the deterministic fallback under the stricter validator. This was one run; live-model
output is non-deterministic, and a repair that then succeeded is not visible in the pass
count.
