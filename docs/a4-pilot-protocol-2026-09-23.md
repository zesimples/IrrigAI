# A4 pilot protocol — proposal for agreement

Status: **proposal, not started.** Nothing in this document may begin until the farms,
duration, success criteria, stop conditions and budget below are agreed, and until the
A0–A4 build is deployed (see [the deploy plan](deploy-plan-a0-a4-2026-09-23.md)). It is
the A4.5 half of the foundation gate; the human review of representative answers
([review pack](a4-human-review-pack-2026-09-23.md)) is the A4.3 half and can run first.

## What the pilot has to show

That on real farm configurations, over real days, the AI layer:

- never contradicts the deterministic engine in anything a grower sees;
- keeps farm, sector and weather scope straight, including per-plot weather;
- says so honestly when telemetry is stale or missing;
- is fast enough and cheap enough to use daily;
- is useful: growers and the agronomist find the answers correct and actionable.

The synthetic evaluation (28 cases, [completion report](a4-completion-report-2026-09-23.md))
cannot show any of this on real data, and it cannot show the production Caddy route.

## Proposed farms and sectors

Chosen so that each configuration the brief names is covered at least once. Counts come
from the development copy of the data (read-only, 2026-09-23); **exact sectors must be
confirmed on production with a read-only query before the start**, because development
may have drifted.

| Configuration | Farm | Proposed sectors | Why |
|---|---|---|---|
| Per-plot weather, own station | Innoliva | 1 sector in a polo with its own iMetos (e.g. Covadonga) | Weather scope must be the polo's, not the farm's |
| Per-plot weather, forecast-only | Innoliva | 1 sector in Conceição | No observations: answers must say forecast-only |
| Stale telemetry | Innoliva | 1 sector whose probe is > 30 h stale (9 such in dev) | Honesty about stale data |
| Flowmeter-only (water-balance model) | Conqueiros | 2 probe-less sectors (36 in dev) | Soil water is modelled, not measured |
| Probe + flowmeter | Conqueiros | 1 sector (13 in dev) | Both sources present |
| Tension / Watermark | Esporão | 1 olive sector (7 in dev) | Calibration must be refused honestly |
| VWC probe-only | Esporão, Amendoas do Lago | 1 each (ADL spans 3 MyIrrigation projects) | The common case |
| Probe-calibrated soil bounds | — | **none exist in the development copy** | See below |
| Manually configured soil bounds | — | **none exist in the development copy** | See below |

About 11 sectors on 4 farms.

**The two soil-bound configurations need a decision.** If production also has no sector
with an applied probe calibration or a manual soil override, covering them means creating
one — a change to live recommendations. Options: (a) an agronomist applies a calibration
and sets one manual override through the normal UI, on named sectors, with explicit
approval; (b) leave them out and record the gap. This protocol does not assume (a).

## Participants

To be arranged by the project owner:

- **1 agronomist** — reviews answers against agronomic judgement; the only person who may
  confirm a mutating action during the pilot, and only on an agreed sector.
- **2 or more growers**, ideally one per farm type (per-plot weather, flowmeter-based).

## Duration

Proposed: **14 days.** That covers two Monday calibration runs (04:00 UTC), fourteen daily
recommendation runs (05:00 UTC), weekend usage, and enough turns to see rates rather than
anecdotes. Shorter is possible; the sample sizes below would shrink accordingly.

## What participants do

- Use the app as normal: open their sectors, read the recommendation, ask the assistant
  (at least 2 questions per day across their sectors), open the cards.
- Rate answers with the existing feedback buttons; the four reasons (wrong data, stale
  answer, unclear explanation, unhelpful next step) are what the pilot counts.
- **Do not confirm assistant-proposed actions** (calibration, override, accept/reject)
  unless it is the agreed sector and the agronomist is doing it. A proposal can be
  cancelled freely.
- Report anything that looks wrong immediately (see stop conditions).

## What is measured, and where it comes from

All from instrumentation that already exists in production — nothing new is needed.

| Measure | Source |
|---|---|
| Time to first visible progress, first answer, completion | `irrigai_ai_chat_stage_seconds{stage}` — **server-side**, from turn start; excludes the Caddy hop |
| Progress through the real proxy | The post-deploy browser check (deploy plan, step 7), repeated once mid-pilot |
| Tokens and cost | `irrigai_ai_tokens_input_total` / `_output_total` by model |
| Repair, fallback, interruption, failure rates | `irrigai_ai_chat_turns_total{outcome}` |
| Degraded (AI unavailable) responses | `irrigai_ai_degraded_responses_total` |
| Usefulness and corrections | `ai_response_feedback` rows (rating + reason) and participant notes |
| Critical findings | Participant reports + agronomist review, triaged daily |

Report every rate with its sample size (turns, days, participants).

## Success criteria — to agree, not assumed

These are proposals. The numbers in brackets are **reference points from the synthetic
evaluation, not targets**: production contexts are larger, and real questions differ.

| Criterion | Proposed rule | Reference |
|---|---|---|
| Engine contradictions shown to a grower | **Zero.** Non-negotiable | 0 in the release set |
| Scope errors (wrong farm/sector/weather) | **Zero** | 0 |
| Dishonest staleness (stale data presented as current) | **Zero** | 0 |
| Fallback rate | ≤ ___ % (agree) | 1 of 35 chat turns in repeated runs |
| Repair rate | reported, not gated | 8 of 35 turns |
| Server p50 time to first progress | ≤ ___ s (agree) | local proxy: 0.15 s |
| Server p50 completion | ≤ ___ s (agree) | eval: 3.7 s per card, 6.4 s per chat case |
| "Helpful" feedback share | ≥ ___ % (agree) | none yet |
| Spend | within the agreed budget | see below |

## Stop conditions

Pause the AI immediately on any of:

1. An answer shown to a grower that contradicts the engine, uses another sector's or farm's
   data, or presents stale data as current.
2. Any mutating action executed outside the agreed sector, or without the agronomist.
3. Spend reaching the agreed budget.
4. A production incident unrelated to the AI (disk, database, ingestion) — the pilot's
   measurements would be meaningless.

**How to pause:** there is **no dedicated AI switch.** `LLM_DAILY_REQUEST_LIMIT=0` means
*unlimited*, not off, and `LLM_PROVIDER=mock` would show mock text to growers — use
neither. **Do not unset `OPENAI_API_KEY` either:** the client is built per request and an
empty key raises inside the FastAPI dependency, so every AI endpoint would return 500
instead of the honest message.

What works today: set `OPENAI_API_KEY` to a **non-empty invalid value** (e.g.
`pilot-paused`) and recreate `backend` with the three-file procedure. Verified locally on
2026-09-23: the client still builds, each call fails in ~0.5 s with `AuthenticationError`,
and both the chat and card paths catch it, so every AI surface shows the honest
"assistente temporariamente indisponível" message while the **deterministic
recommendation UI keeps working** (`test_an_ai_outage_is_honest_and_leaves_the_engine_recommendation_available`).
Restoring the real key and recreating `backend` resumes. A proper per-feature switch, and
honest degradation for an empty key, are in the backlog.

## Budget

Proposed cap: **US$ 20** for the pilot, checked daily against the token counters.

Basis, at `gpt-4o-mini` list prices of US$ 0.15 / 1M input and US$ 0.60 / 1M output
tokens (**verify current pricing before agreeing**): the synthetic evaluation cost about
US$ 0.0005 per chat turn including repairs and US$ 0.0003 per card. Assume production
contexts are 3–5× larger — roughly US$ 0.002 per turn. Five participants × 20 turns a day
× 14 days is 1,400 turns, about US$ 3. The cap leaves a wide margin; the per-user daily
quota (`LLM_DAILY_REQUEST_LIMIT`, default 200) bounds runaway usage per person.

## Load and concurrency

**No load testing on production**, implicit or explicit. Pilot figures are observed usage
only. If concurrency needs measuring, it is done locally against the isolated review
environment and reported separately.

## Output

A pilot report: participants and configurations actually covered, turns and days, every
metric above with its sample size, all findings with severity and resolution, and an
explicit statement of which A4 criteria it satisfies.
