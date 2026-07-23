# Golden-set AI evaluations

This directory contains opt-in tests against the configured OpenAI model. The
live runner is named `eval_golden_set.py`, so default pytest and CI discovery do
not call a paid or non-deterministic external service. It skips cleanly if
`OPENAI_API_KEY` is absent or `LLM_PROVIDER` is not `openai`.

Run from `backend/`:

```bash
LLM_PROVIDER=openai OPENAI_API_KEY=... pytest -q tests/ai_eval/eval_golden_set.py -s
```

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

For every response the runner checks that:

- user-facing fields are recognisably Portuguese from Portugal;
- each evidence ID, source path, label, and display value matches the backend
  registry generated from that case's context;
- probe advice contains no raw VWC decimals;
- the deterministic probe guard wins for `skip` and `defer` decisions;
- “Rega urgente” names only sectors whose engine action is `irrigate`.

## Adding a case

1. Capture the JSON object immediately before it is formatted into the LLM
   prompt. Remove tenant identifiers, coordinates, credentials, personal data,
   and commercially sensitive names; do not change field names or value types.
2. Add one object with a unique `id`, one of the three supported `surface`
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
