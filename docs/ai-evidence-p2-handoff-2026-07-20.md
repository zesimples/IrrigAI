# AI evidence P2 handoff — 2026-07-20

## Outcome

Phase P2 replaces model-authored evidence paths and values with a backend-owned
evidence registry and renders the validated structured object directly in React.
The deterministic engine and `SectorAIContextV2` remain the authority.

## Backend contract

- `backend/app/ai/evidence.py` walks the supplied context's scalar leaves and
  assigns a stable `ev_<hash>` ID to each citable path.
- The prompt receives only an ID→path catalogue; values are not duplicated in the
  catalogue and the model's structured schema accepts only `evidence_id`.
- The server discards unknown IDs, deduplicates citations, and resolves `source`,
  Portuguese `label`, and localized/unit-aware `value` from the current context.
- Raw VWC/SWC/FC/PWP scalar paths and limitation/configuration prose are excluded
  from the citable registry.
- Empty or invalid model evidence falls back to server-selected registered paths.
- The probe recommendation guard now prepends registry-resolved engine evidence
  instead of manufacturing a combined display string.
- Existing prose response fields (`explanation`, `diagnosis`, `interpretation`,
  `analysis`, `summary`) remain for compatibility during rollout.

API evidence now has:

```json
{
  "evidence_id": "ev_…",
  "source": "water_balance.depletion_mm",
  "label": "Depleção",
  "value": "12,5 mm"
}
```

## Frontend rendering

- `StructuredAIResult` renders summary, risk, irrigation advice, resolved evidence,
  next actions, limitations, and confidence directly from `structured`.
- Recommendation explanation, sector diagnosis, and probe diagnosis cards use the
  shared renderer.
- `parseResultBullets`, `DiagnosisBody`, and `InterpretationBody` were removed.
- Old localStorage/prose responses still display as unparsed plain-text fallbacks.
  New sector analyses persist the structured object alongside the compatibility text.

## Evaluation and verification

- Failing-first backend: the registry contract initially failed at import because
  `app.ai.evidence` did not exist.
- Failing-first frontend: the renderer test initially failed because
  `StructuredAIResult` did not exist.
- Registry tests cover stable IDs, nested list paths, raw-VWC exclusion, localized
  server values, invalid-ID rejection, and the prompt catalogue.
- The opt-in golden-set runner now exercises the production assistant resolver and
  asserts ID/path/label/value agreement with the registry.
- Full backend: `652 passed, 10 skipped`.
- Full frontend: `80 passed`.
- Frontend lint and production build/type-check: clean.
- Changed-file Ruff: clean.

No database migration is required. Deployment must rebuild backend and frontend;
the normal production command may continue to rebuild worker as well.

## Deferred

P3+ remain deferred: field observations and server-side chat persistence, additional
read tools, rate/cost/error hardening, farm-context aggregation, new outcome and
calibration UI surfaces, and model routing.
