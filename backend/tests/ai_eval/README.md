# Golden-set AI evaluations

This directory contains opt-in tests against the configured OpenAI model. The
live runner is named `eval_golden_set.py`, so default pytest and CI discovery do
not call a paid or non-deterministic external service. It skips cleanly if
`OPENAI_API_KEY` is absent or `LLM_PROVIDER` is not `openai`.

There are two live runners:

| Runner | What it evaluates |
| --- | --- |
| `eval_golden_set.py` | Recommendation, probe advisory, farm summary, alert explanation, change analysis, irrigation effectiveness. |
| `eval_chat_multiturn.py` | Multi-turn chat grounding, weather scope, note-injection resistance, and the proposed-action lifecycle. |

Run from `backend/` only with both database URLs explicitly targeting an isolated
test database (pytest's autouse fixtures delete rows), and a separate Redis:

```bash
LLM_PROVIDER=openai OPENAI_API_KEY=... pytest -q tests/ai_eval/eval_golden_set.py -s
LLM_PROVIDER=openai OPENAI_API_KEY=... pytest -q tests/ai_eval/eval_chat_multiturn.py -s
```

`eval_chat_multiturn.py` prints a ledger separating **model failures** (the answer
failed a deterministic check) from **provider failures** (the API call itself broke)
and from **skips** (no credentials — nothing was evaluated and nothing is proven).
Never read a skipped run or a degraded fallback as evidence of model quality.

Its tool execution is stubbed from `cases/chat_multiturn.json` so the model is the
only variable; ownership, the engine, and the DB are covered by deterministic tests.
The runner accumulates verified evidence across turns exactly as the API does — an
evaluation with less context than production measures a handicapped product.

Production model routing can be evaluated without changing code:

```bash
OPENAI_MODEL=gpt-4o-mini \
OPENAI_MODEL_CHAT=... \
OPENAI_MODEL_STRUCTURED=... \
OPENAI_MODEL_SUMMARY=... \
LLM_PROVIDER=openai OPENAI_API_KEY=... \
pytest -q tests/ai_eval/eval_golden_set.py -s
```

Blank routing overrides inherit `OPENAI_MODEL`. Promote a route only when the
complete golden set passes; never relax the deterministic guard or evidence
assertions to make a cheaper model pass.

The 20 cases in `cases/golden_contexts.json` are anonymised, compacted snapshots
that preserve the actual JSON field names and value types sent by the
recommendation, probe-advisory, and farm-summary surfaces. They cover
irrigate/skip/defer, fresh/stale/missing probes, rain, calibrated soil bounds,
detected irrigation response, and mixed farm actions.

Three additional **synthetic** cases in `cases/additional_surfaces.json` cover
alert explanation, change analysis, and irrigation effectiveness using their
production prompts and context shapes. They are regression fixtures, not evidence
from a farm pilot. The card suite now contains 23 cases across six surfaces.
A degraded card response fails live evaluation; unavailable credentials produce
skips, never passes. Multi-turn grounding checks only the current turn's reads.

For the September recovery workspace, use the guarded runner rather than pytest
with inherited development URLs. First start the disposable Redis if absent:

```bash
docker run -d --rm --name irrigai-review-redis-20260921 --network irrigai_default \
  --label irrigai.purpose=isolated-a0-a4-review redis:7-alpine \
  redis-server --save '' --appendonly no
```

Then, from the repository root:

```bash
docker compose run --rm --no-deps -v "$PWD/backend:/app" backend \
  python -m scripts.run_isolated_review live-eval
```

This explicitly opts into the two live fixture suites while pinning **both**
database URLs to `irrigai_ai_review_20260921`, verifying `current_database()`,
and keeping Redis isolated. It uses the existing model routes and credentials;
do not print or commit those credentials. Normal `pytest` mode forces mock LLMs.

For every response the runner checks that:

- user-facing fields are recognisably Portuguese from Portugal;
- confidence matches the deterministic derivation in `app/ai/answer_confidence.py`
  (engine confidence, data quality, explanation availability — never a
  model-authored percentage, and never raised by agreeing with the engine);
- a no-irrigation answer quotes the engine's own reason instead of inventing one;
- each evidence ID, source path, label, and display value matches the backend
  registry generated from that case's context;
- probe advice contains no raw VWC decimals;
- the deterministic probe guard wins for `skip` and `defer` decisions;
- “Rega urgente” names only sectors whose engine action is `irrigate`.

## Adding a case

1. Capture the JSON object immediately before it is formatted into the LLM
   prompt. Remove tenant identifiers, coordinates, credentials, personal data,
   and commercially sensitive names; do not change field names or value types.
2. Add one object with a unique `id`, one of the six supported `surface`
   values, the `context`, and the exact Portuguese `user_message`.
3. Keep the set near 20 cases. If a new regression needs a permanent case,
   replace redundant coverage or update the size guard deliberately.
4. Run the deterministic contract tests first, then the live command above.
   Review failures; do not relax engine-authority assertions to accommodate a
   model response.

The live runner uses the same `IrrigationAssistant._complete_structured()` path as
production. The model sees an ID→path catalogue, emits only `evidence_id`, and the
backend supplies the API's `source`, `label`, and localized `value`. Raw VWC scalar
paths are deliberately absent from the catalogue.

The shared assertion implementation is unit-tested by
`tests/test_ai/test_eval_harness_contracts.py` in the default suite.
