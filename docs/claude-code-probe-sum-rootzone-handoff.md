# Claude Code handoff: probe depth sum vs. depletion

Date: 2026-07-15  
Implementation commit: `3c183dd fix(probes): align depth sum with root zone`
Display follow-up commit: `f566946 fix(probes): zoom rootzone sum chart`
Final calculation-alignment commit: `6815755 fix(probes): align rootzone chart with depletion`

> **Current state:** commit `6815755` supersedes the arithmetic-sum presentation described in the first two implementation phases below. The UI no longer presents **Soma** as a decision metric; it presents the engine-equivalent weighted **Zona radicular** value instead. The earlier sections remain as diagnosis/history.

## Problem reported

On the sector detail page, depletion could be high while the probe's **Soma** chart appeared to show high soil moisture inside the green comfort band. The concrete report was for **Turno 5 (S20)** and probe **1597/3832**.

This looked like a disagreement between the recommendation engine and the probe chart.

## Live diagnosis

The repository's read-only diagnostic was run inside the backend container:

```bash
docker compose exec -T backend python -m scripts.diagnose_sector_swc "Turno 5"
```

Relevant output:

```text
Effective root depth: 0.75 m

10cm  0.131  IN-ROOTZONE
20cm  0.125  IN-ROOTZONE
30cm  0.151  IN-ROOTZONE
40cm  0.096  IN-ROOTZONE
50cm  0.067  IN-ROOTZONE
60cm  0.078  IN-ROOTZONE
70cm  0.074  IN-ROOTZONE
80cm  0.320
90cm  0.545

all-depth average: 0.176
rootzone simple average: 0.103
```

The old chart summed all nine live depths:

- All-depth sum: approximately `158.7%`.
- Root-zone-only sum (10–70 cm): approximately `72.2%`.
- The 80 cm and 90 cm sensors were below the configured 75 cm root zone and contributed `86.5` percentage points to the displayed sum.

The recommendation engine was already behaving differently and correctly for its purpose: `probe_interpreter._compute_rootzone()` excludes depths below the effective root depth and computes a depth-interval-weighted root-zone VWC. The wet 80/90 cm layers therefore did not reduce depletion.

## Root cause

The mismatch was in presentation semantics, not the depletion formula:

- **Depletion** represented moisture in the effective crop root zone.
- **Soma** represented the arithmetic sum of every live depth, including water below the active root zone.
- Deep wet layers could therefore make Soma look comfortable while the active root zone was dry.

There was already explanatory text below Soma and a root-zone-weighted overlay in the **Profundidades** view, but the primary Soma visualization still invited a direct and misleading comparison with depletion.

## First correction: root-zone-only sum (historical)

### `frontend/src/components/probes/ProbeSumChart.tsx`

- Added `rootDepthCm` to `ProbeSumChart`.
- Added and exported `filterRootzoneDepths()`.
- Soma data now includes only depths where `depth_cm <= rootDepthCm`.
- CC/PMP summed reference bounds use the same filtered depth set.
- Preserved safe fallbacks:
  - If root depth is unavailable, all depths are retained.
  - If no sensor lies inside the configured root zone, all depths are retained, mirroring the engine's no-in-zone fallback.
- Updated the tooltip and summary label to **Soma da zona radicular** / **Soma atual · zona radicular**.

### `frontend/src/components/probes/ProbeReadingsInline.tsx`

- Passes `data.root_depth_cm` into `ProbeSumChart`.
- The CC/PMP edit scale now counts only live depths included in the root-zone sum, so editing `% soma` remains mathematically consistent with the displayed chart.
- Replaced the old all-depth warning with explicit copy stating that Soma is limited to the configured root zone and that deeper sensors remain available in **Profundidades**.
- If root depth is unavailable, the copy accurately states that all depths are included.

### Tests

Updated:

- `frontend/src/components/probes/__tests__/ProbeSumChart.test.tsx`
- `frontend/src/components/probes/__tests__/ProbeReadingsInline.test.tsx`

New regression coverage verifies that:

- Wet sensors below the root zone are excluded from Soma.
- All depths remain available when root depth is null.
- The engine-compatible fallback is used when every sensor is deeper than the root zone.
- The inline explanation describes the new root-zone behavior.

## Verification

Commands run:

```bash
cd frontend
npm run test:run
npx tsc --noEmit
```

Results:

- Frontend: **69/69 tests passed** across 11 test files.
- Targeted probe tests: **16/16 passed**.
- TypeScript: passed with no errors.
- `git diff --check`: passed.

## Result after the first correction (historical)

For Turno 5, Soma will now display the combined 10–70 cm readings rather than being dominated by the wet 80/90 cm layers. The deeper readings are not discarded; users can still inspect them individually in **Profundidades**. This makes the decision-facing visualization refer to the same soil volume as depletion while preserving the full probe profile for diagnosis.

## Second correction: zoomed Soma display (historical)

After the root-zone filter was deployed, a second production screenshot confirmed that the values and thresholds were now consistent but exposed a display problem: the Soma Y-axis still always started at zero.

The concrete chart had:

- Observed root-zone sum: `162.9–197.2%`.
- PMP sum: `154%`.
- CC sum: `201%`.
- Old Y-axis domain: approximately `0–226%`.

Because the stress `ReferenceArea` extended from zero to PMP, most of the chart remained red even though the signal itself occupied a narrow range around PMP and CC. The variation and individual irrigation responses were visually compressed.

### Follow-up implementation

`frontend/src/components/probes/ProbeSumChart.tsx` now exports `calculateSumDomain()` and uses it for the Y-axis:

1. Collect the observed minimum, observed maximum, PMP sum and CC sum.
2. Calculate the full span across those values.
3. Add padding equal to the greater of 5 percentage points or 12% of the span.
4. Round outward and clamp the lower limit to zero.

For the reported production values, this changes the visible range from approximately `0–226%` to `148–207%`. Both agronomic thresholds and the complete series remain visible, but the red stress band becomes a small contextual portion of the chart instead of dominating it.

The calculation also handles:

- Flat series by applying the minimum 5-point padding.
- Missing CC/PMP reference lines by zooming around the observations.
- Values near zero without producing a negative Y-axis.

### Follow-up verification

Added four regression cases to `frontend/src/components/probes/__tests__/ProbeSumChart.test.tsx`, including the exact production-shaped values above.

```text
Frontend suite: 73/73 tests passed across 11 test files
ProbeSumChart:   16/16 tests passed
TypeScript:      passed with no errors
git diff check:  passed
```

## Final correction: engine-equivalent root-zone chart

A later production screenshot for **Turno 4 (S18)** showed that limiting and zooming the arithmetic sum was not sufficient. The top recommendation reported `35%` depletion while the root-zone sum chart still had values on a different scale. Those quantities could move in the same direction, but they could never correspond numerically because:

- The chart still added depth VWC values without soil-volume weighting.
- Its display envelopes could be per-depth observed CC/PMP values.
- The engine uses one depth-interval-weighted root-zone VWC and one resolved CC/PMP pair.
- The CC/PMP editor/footer still had sum-specific scaling paths, including an all-depth multiplier.

The final correction removes the raw arithmetic sum from the decision-facing UI. The internal component filename remains `ProbeSumChart.tsx` for now, but the user-facing view is **Zona radicular**.

### Final calculation

The chart now consumes `ProbeReadingsResponse.rootzone_swc`, which the backend builds with the same depth-interval weights and effective root depth used by `probe_interpreter._compute_rootzone()`.

For every weighted VWC point, the frontend mirrors `water_balance.build_water_balance()`:

```text
clamped VWC = clamp(VWC, PMP, CC)
depletion % = (CC - clamped VWC) / (CC - PMP) × 100
available water % = 100 - depletion %
```

The root depth cancels when converting `depletion_mm / TAW_mm` to a percentage, so this normalized formula is exactly equivalent to the engine percentage.

Concrete regression example:

```text
CC = 11%
PMP = 1%
weighted root-zone VWC = 7.5%

depletion = (11 - 7.5) / (11 - 1) = 35%
available water = 65%
```

### Final UI behavior

- The view selector is now **Profundidades** / **Zona radicular**, not **Profundidades** / **Soma**.
- The line is **Zona radicular (média ponderada)** in VWC percent.
- CC and PMP lines use the exact sector-resolved bounds returned by the API; they are not summed or replaced by per-depth display envelopes.
- Three current-value cards make the relationship explicit:
  - **Humidade atual · zona radicular**
  - **Água disponível**
  - **Depleção da sonda**
- Inline copy states: depletion is 0% at CC and 100% at PMP, and available water is `100% − depletion`.
- CC/PMP editing always uses ordinary per-volume percentages; all `% soma`, depth-count multiplication and sum footer paths were removed.
- The standalone probe-history page also passes `rootzone_swc` to the corrected view.
- The Y-axis remains dynamically zoomed around weighted VWC plus CC/PMP, now with a minimum one-percentage-point padding.

### Files changed in the final correction

- `frontend/src/components/probes/ProbeSumChart.tsx`
- `frontend/src/components/probes/ProbeReadingsInline.tsx`
- `frontend/src/components/probes/ReadingsControls.tsx`
- `frontend/src/app/farms/[farmId]/sectors/[sectorId]/probes/[probeId]/page.tsx`
- `frontend/src/components/probes/__tests__/ProbeSumChart.test.tsx`
- `frontend/src/components/probes/__tests__/ProbeReadingsInline.test.tsx`

### Final verification

```bash
cd frontend
npm run test:run
npx tsc --noEmit
npm run build
```

Results:

```text
Frontend suite:          66/66 tests passed across 11 test files
Direct root-zone tests:   9/9 passed
Inline probe tests:       4/4 passed
TypeScript:               passed with no errors
Next.js production build: compiled successfully
git diff check:           passed
```

The suite count decreased from 73 to 66 because obsolete arithmetic-sum helper tests were removed and replaced by direct equation, clamping, weighted-series and complement assertions; this is not a loss of current-behavior coverage.

## Scope and deployment notes

- Frontend-only change; no migration or API schema change.
- The backend already returned `root_depth_cm` and `rootzone_swc`, and already used root-zone weighting for recommendations.
- Deploy/rebuild the frontend for the behavior to appear in the application.
- All three implementation phases require only a frontend rebuild/restart; backend, worker, database and Redis do not need to be recreated.
