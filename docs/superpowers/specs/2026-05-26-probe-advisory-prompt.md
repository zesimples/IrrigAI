# Spec: Probe Advisory Prompt for Structured Interpretation

**Date:** 2026-05-26  
**Status:** Approved

---

## Problem

`interpret_probe_patterns_structured` reuses `PROBE_INTERPRETATION_PT` — a prompt designed to enumerate detected signal patterns per depth — with the `AgronomicInterpretation` structured output schema. The mismatch causes the LLM to populate `evidence[]` with items like `source = "depths[50]"`, `value = "Sinal Estável"`, which `render_structured` turns into repetitive, useless bullet lines for the farmer.

---

## Goal

`interpret_probe_patterns_structured` produces a short, actionable advisory the farmer can act on — e.g. "Sonda mostra humidade estável e adequada. Não há necessidade de regar nos próximos 1–2 dias; monitoriza a tendência." — with `evidence[]` citing real signal data paths, not per-depth pattern labels.

---

## Scope

- Backend only. No schema changes, no frontend changes, no new DB queries.
- `PROBE_INTERPRETATION_PT` and the unstructured `interpret_probe_patterns` method are **untouched**.
- No ET₀ or weather data enrichment (signal-only advisory).

---

## Design

### Two paths, two prompts

| | `interpret_probe_patterns` | `interpret_probe_patterns_structured` |
|---|---|---|
| Output | Free text bullet list | `AgronomicInterpretation` JSON |
| Purpose | "What patterns exist in this signal?" | "What should the farmer do?" |
| Template | `PROBE_INTERPRETATION_PT` (unchanged) | `PROBE_ADVISORY_PT` (new) |

### New template: `PROBE_ADVISORY_PT`

Added to `backend/app/ai/prompt_templates.py`. Same `{signal_json}` placeholder as `PROBE_INTERPRETATION_PT`.

Key instructions:
- Synthesise the probe situation as a whole — do **not** enumerate patterns per depth.
- `summary`: 1 sentence describing what the probe shows now.
- `irrigation_advice`: concrete farmer action.
- `evidence`: 2–4 items with real JSON paths from the signal stats (e.g. `depths[0].humidade_actual`, `cross_depth_signals.divergencia_entre_profundidades`, `last_irrigation_applied_mm`). Explicitly prohibited: `source = "depths[N]"` with `value = "Sinal Estável"`.
- `recommended_actions`: 1–2 concrete next steps.
- Language rules identical to `PROBE_INTERPRETATION_PT`: qualitative moisture terms, no raw VWC decimals, Portuguese PT, max 25 words per field.

### Change in `assistant.py`

`interpret_probe_patterns_structured` (line ~275): swap `prompt_templates.PROBE_INTERPRETATION_PT` → `prompt_templates.PROBE_ADVISORY_PT`. One line.

---

## Files changed

| File | Change |
|------|--------|
| `backend/app/ai/prompt_templates.py` | Add `PROBE_ADVISORY_PT` constant |
| `backend/app/ai/assistant.py` | Line ~275: use `PROBE_ADVISORY_PT` instead of `PROBE_INTERPRETATION_PT` |

---

## Out of scope

- ET₀ / weather enrichment in `compute_probe_signal_stats` (future work).
- Changes to `render_structured`.
- Changes to `PROBE_INTERPRETATION_PT` or `interpret_probe_patterns`.
- Frontend changes.
