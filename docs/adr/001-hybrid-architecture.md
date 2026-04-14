# ADR 001 — Hybrid Architecture: Deterministic Engine + LLM Explanation

**Status:** Accepted  
**Date:** 2026-04-07

## Context

Irrigation scheduling requires agronomic precision. Water stress at critical phenological stages (e.g. maize tasseling, almond kernel fill) causes irreversible yield loss. Farmers need to trust recommendations and understand why they are made.

LLMs are probabilistic and can hallucinate numerical values. Relying on an LLM to compute irrigation depth from soil water content, ETc, and depletion thresholds introduces unacceptable agronomic risk.

## Decision

All irrigation recommendations are produced by a **deterministic agronomic engine** that applies well-defined equations (FAO-56 water balance, Penman-Monteith ET0, depletion-vs-MAD trigger logic). The engine outputs structured data: action, depth, runtime, confidence score, inputs used, assumptions, and missing-data warnings.

**OpenAI ChatGPT** operates as an **explanation-only layer** on top of the engine output. It receives the structured recommendation and translates it into natural language the farmer can understand. It may ask clarifying questions and summarize alerts, but it **never overrides or replaces engine outputs**.

## Consequences

- Recommendations are reproducible and auditable. Any recommendation can be explained step-by-step with its inputs.
- Agronomists can inspect and override engine parameters without touching LLM prompts.
- System works without an OpenAI API key (LLM_PROVIDER=mock) — engine still runs.
- LLM cost is proportional to user-facing explanation requests, not background computation.
- Adding new crops or tuning agronomic parameters requires no LLM changes.
