# Dose do dia — from "Regar/Não Regar" to a daily dose recommendation

**Date:** 2026-07-06
**Status:** Approved design, pending implementation plan

## Problem

The headline recommendation is a binary verdict (*Regar / Não Regar*). During irrigation
season clients irrigate on a ≤2-day rhythm regardless, so the binary answer carries no
information — the question they actually have is **"quanto tempo rego hoje?"**. The engine
already computes everything richer than the verdict (dosage mm + runtime, depletion %,
3-day stress projection); the UI collapses it into a switch.

## Concept

Replace the verdict with a **daily dose expressed in irrigation time**, scaling
continuously with the soil deficit. On reserve days the client sees a short run, not a
"no" they'll ignore.

Four presentation bands (a classifier over existing engine outputs — the
`RecommendationAction` enum, alerts, and the AI probe-guard are untouched underneath):

| Band | Example headline | Engine state (r = depletion ÷ effective trigger threshold) |
|------|------------------|--------------|
| Rega reforçada | "Regar 3h00 — repor o défice" | r ≥ 1.0 (trigger fired) |
| Rega normal | "Regar 1h30" | 0.4 ≤ r < 1.0 |
| Rega curta | "Bastam 40 min hoje" | r < 0.4 |
| Pode saltar | "Pode saltar — chuva prevista cobre o défice" | physics-based rain-skip, or gross dose below `min_irrigation_mm` (default 2 mm when unset) |

The 0.4 band boundary is a presentation constant, not agronomy — tune with feedback.

Secondary line reuses the existing 3-day stress projection:
*"Sem chuva à vista — amanhã serão ~2h."*

Scope decisions made during brainstorming:

- **Horizon: today's event.** No weekly budget, no multi-day plan in the headline.
- **Unit: time (hours/min)** — what the client punches into the controller. mm is the
  technical detail, and the fallback when time can't be estimated.
- **Reserve days get a reduced dose, not a skip.** Dose = depletion (current `dosage.py`
  behavior) already produces this. "Pode saltar" survives only for rain-skip and
  negligible doses.
- **Flowmeters are excluded as a learning source** (only one project uses them).
  Probe-detected irrigation events are the only learning input.

## Component 1 — Learned irrigation fingerprint (engine, new module)

A new deterministic module (sibling of `engine/auto_calibration.py` — no LLM involvement)
studies the sector's **persisted probe-detected irrigation events** over a lookback
window of **25 days** (the app is young; longer windows would reach into data that does
not exist or predates current routines) and derives per sector:

- **`typical_event_net_mm`** — per event, integrate ΔVWC × layer thickness across the
  probe's depths (trapezoidal; each sensor's layer spans the midpoints to its adjacent
  sensors; capped at rootzone depth, consistent with `probe_interpreter` weighting).
  Median across usable events.
- **`typical_event_duration_min`** — median VWC-rise duration. Honestly labeled an
  estimate: it is quantized by the probe's reading interval.
- **`n_events`, `confidence`, `computed_at`** — confidence derived from event count,
  classification score quality, and duration quantization.

Event hygiene:

- User-**confirmed** events count fully; **rejected** events are excluded; unreviewed
  events count only if their irrigation-classification score is strong.
- Rain-coincident events are excluded (the detector already cross-references weather).
- Minimum **3 usable events** in the window, else no fingerprint is produced.
- VWC probes only — Watermark/tension sectors cannot learn (same limitation and same
  honest-unavailable treatment as Calibração AI).

## Component 2 — Dose resolution precedence

Same idiom as `engine/soil_bounds.resolve_soil_bounds`. For a needed net dose of X mm
(today's `dosage.py` output — unchanged):

1. **Configured** — application rate or emitter config present → exact minutes
   (unchanged current behavior).
2. **Probe-learned** — fingerprint present, fresh, confident → headline as a **multiple
   of the habitual event**, with estimated minutes when duration confidence allows:
   *"≈1.3× a rega habitual (~2h35, estimado)"*.
3. **mm-only** — *"Aplicar 5 mm hoje"*.

Guards: `typical_event_net_mm` near zero → fall to mm-only. Every recommendation records
`dose_source` (`configured` / `probe_learned` / `mm_only`) in `inputs_snapshot`,
mirroring the `swc_source` pattern.

## Component 3 — Persistence & scheduling

- One `irrigation_fingerprint` row per sector (mirrors `probe_calibration`; upsert).
- Recomputed by the **weekly scheduler job**, alongside the calibration recompute — not
  in the daily pipeline (learning reads 25 days of probe series; too heavy for the daily
  run across 100+ sectors).
- **Staleness guard: 25 days** (matching the lookback) — a fingerprint that has not
  refreshed in 25 days falls through to the next tier. Weekly recompute keeps healthy
  sectors at ≤7 days old; the guard only bites when the job or the probe has been dead.
- Silent — no manual trigger button in v1 (unlike Calibração AI there is no user
  decision to anchor a button to).

## Component 4 — Frontend

Touched components:

- `components/dashboard/editorial/VerdictPill.tsx` — binary pill → 4-band pill.
- `components/dashboard/SectorCard.tsx` and `components/dashboard/editorial/SectorCard.tsx`
  — headline renders per `dose_source`.
- `components/dashboard/editorial/DecisionPanelEditorial.tsx`,
  `components/sectors/RecommendationDetail.tsx` — dose-centric headline + secondary
  stress-projection line; detail card shows the fingerprint basis
  ("baseado em 7 regas detetadas") so estimates are explainable.
- `app/page.tsx` dashboard headline ("Regar N sectores" aggregate) — reframe around
  bands.
- `OverrideModal` unchanged — overrides still speak engine-action language.

All copy in European Portuguese. The AI layer's context gains the dose fields so chat
and card explanations can reference "a tua rega habitual".

## Risks & edge cases

- **Calibration accuracy becomes load-bearing.** The known FC-clamp issue (~18 sectors
  with depletion pinned at 0) would headline "Bastam 10 min" all season. Dose-centric UI
  makes bad calibration visible — flag during rollout; FC calibration is the remedy.
- Probe-derived doses are **net and point-local** — they miss percolation below the
  sensors and assume the probe spot represents the sector. Tier 2 therefore leads with
  relative phrasing, not fake-precise minutes.
- Routine changes (new emitters, split shifts) self-correct within the 25-day window;
  the "baseado em N regas" line is the transparency valve.
- Off-season: no events in window → no fingerprint → mm-only. Correct behavior, no
  special-casing.

## Testing

- **Unit:** fingerprint math on synthetic VWC series (clean event, noisy, rain-coincident
  excluded, rejected excluded, <3 events → none); precedence resolver tiers and guards;
  band classifier boundaries.
- **API:** new recommendation fields present and correct per tier.
- **Frontend (Vitest):** headline rendering per `dose_source` and band.
- Existing engine tests untouched — trigger and dosage math do not change.
