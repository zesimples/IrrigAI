# LLM Assistant — Sprint 1 Design

**Date:** 2026-06-29
**Scope:** Roadmap items #1 (chat memory), #2 (prose chat answers), #3 (native Structured Outputs), #8 (tool calling / "operator" assistant).
**Status:** Approved design — pending implementation plan.

## Goal

Turn the IrrigAI assistant from a read-only narrator into a conversational operator:
the chat remembers the conversation, answers in prose, can fetch data beyond its
current scope, and can *propose* state-changing actions that the user confirms.
Separately, harden every structured ("card") endpoint by switching to the OpenAI
SDK's native Structured Outputs.

The engine-authority invariant is preserved end-to-end: **the LLM never decides
agronomic numbers and never executes a write itself.**

## Two independent tracks

The work splits into two tracks that share only the OpenAI client.

### Track 1 — Card endpoints (#3 only)

`explain`, `diagnosis`, `summary`, `probe interpret`, `change-analysis` stay
single-shot and structured. They keep `render_structured` and the card UI. The
only change is their shared path (`_complete_structured`) switching to native
json_schema. No tool calling, no memory.

### Track 2 — Chat becomes an agentic operator (#1 + #2 + #8)

A new conversational loop with prose output, client-passed history, and tools.

## Component boundaries

`assistant.py` is already 713 lines, so the chat loop lives in new modules rather
than growing it further.

| Module | Role | Depends on |
|---|---|---|
| `ai/openai_client.py` *(changed)* | Add `complete_structured(system, user, schema)` (native json_schema via SDK `.parse`) and `run_tool_loop(messages, tools)`. Mirror both in `MockChatClient`. | openai SDK |
| `ai/tools.py` *(new)* | Tool registry: OpenAI function specs + an async executor. Read tools fetch data; `propose_*` tools return a `ProposedAction` and never execute. Every tool validates ownership via `AccessController` before returning. | context_builder, access |
| `ai/chat_agent.py` *(new)* | `ChatAgent.run(...)` orchestrates the loop, trims history, collects the proposed action, returns prose + optional action. | openai_client, tools |
| `ai/assistant.py` *(changed)* | `_complete_structured` → native; delete brace-hunting parser + `STRUCTURED_OUTPUT_PT` append. | openai_client |
| `api/v1/chat.py` *(changed)* | `farm_chat` → `ChatAgent`; new request/response shapes. | chat_agent, access |
| `schemas/ai.py` *(changed)* | Add `ChatTurn`, `ProposedAction`; extend `ChatResponse`. | — |
| Frontend: `ChatPanel.tsx`, `lib/api.ts`, `types/index.ts` *(changed)* | Send history; render prose; render confirm card; execute via existing typed endpoints. | — |

## Security

The LLM can pass any `sector_id`/`recommendation_id` to a tool. Each tool runs the
same `AccessController` check the REST endpoints use, scoped to the caller; a
denied id returns `{"error": "not_found_or_forbidden"}` that the model must relay,
never data. Propose tools validate ownership too — you cannot propose an action on
a sector you do not own. Untrusted chat history is placed only in `user`/`assistant`
message slots, never concatenated into the system prompt.

## Chat shapes (client-passed memory)

```python
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []          # prior turns from the client
    sector_id: str | None = None

class ProposedAction(BaseModel):
    type: Literal["override_recommendation", "accept_recommendation",
                  "reject_recommendation", "regenerate_recommendation",
                  "run_calibration"]
    summary: str                          # PT human-readable, shown on the confirm card
    sector_id: str | None = None
    recommendation_id: str | None = None
    params: dict = {}                     # e.g. {"depth_mm": 15}

class ChatResponse(BaseModel):
    reply: str                            # PROSE — the actual answer (#2)
    proposed_action: ProposedAction | None = None
```

### Memory handling

History is trimmed server-side to the **last 8 turns** and validated (roles must
be in the allowed set). The current `message` is appended as the final user turn.

## Agentic loop (`ChatAgent.run`)

Capped at **4 iterations**.

1. Build `messages = [system_prompt] + trimmed_history + [user_message]`. System
   prompt states: role; the engine-authority rule ("you never decide agronomic
   numbers; to change irrigation state you MUST call a `propose_*` tool and you
   must NOT claim you performed the action"); current farm/sector scope; PT-PT.
2. Call `client.run_tool_loop(messages, tools)`.
3. If the model returns **read tool calls** → execute each (with access checks),
   append results, loop.
4. If the model returns a **`propose_*` tool call** → capture one `ProposedAction`,
   append a tool result ("proposta registada; aguarda confirmação"), loop once more
   so the model writes a natural-language summary, then stop.
5. If the model returns **plain content** → that is the prose `reply`. Return.
6. Iteration cap hit → return whatever prose exists plus a soft note.

**One proposed action per turn** (if the model emits several, keep the first).
Chat returns `reply` prose directly and never calls `render_structured` (#2).

## Tool registry (`ai/tools.py`)

### Read tools (execute server-side, results fed back)

| Tool | Params | Returns |
|---|---|---|
| `get_farm_overview` | `farm_id` | per-sector latest action (irrigate/skip/defer) + depletion |
| `get_sector_status` | `sector_id` | latest recommendation, depletion, confidence, data-quality |
| `diagnose_sector` | `sector_id` | root-cause diagnosis (reuses existing diagnosis logic) |
| `get_probe_readings` | `sector_id`, `depth_cm?`, `window_hours?` | recent VWC series summary per depth (qualitative + deltas) |
| `get_water_events` | `sector_id`, `days?` | detected irrigation/rain events |
| `get_weather` | `farm_id` | recent obs + short forecast |

### Propose-write tools (return a `ProposedAction`, never execute)

| Tool | Maps to on confirm |
|---|---|
| `propose_override` | `POST /recommendations/{id}/override` |
| `propose_accept_recommendation` | `POST /recommendations/{id}/accept` |
| `propose_reject_recommendation` | `POST /recommendations/{id}/reject` |
| `propose_regenerate_recommendation` | `POST /sectors/{id}/recommendations/generate` |
| `propose_run_calibration` | `POST /sectors/{id}/auto-calibration/run` |

### Executor contract

One async `execute_tool(name, args, *, access, db) -> dict`. Read tools first call
the matching `AccessController` check (`access.sector/farm/recommendation`); on
`HTTPException` they return `{"error": "not_found_or_forbidden"}`. Propose tools
validate ownership, then return the structured `ProposedAction` dict. Tool results
use compact values to keep token cost bounded.

## Native Structured Outputs + client methods (#3)

`OpenAIChatClient` gains two methods, both keeping the existing token/request
metrics:

- `complete_structured(system, user, schema_model, *, max_tokens, temperature=0.1) -> BaseModel`
  — uses the SDK's `beta.chat.completions.parse(..., response_format=AgronomicInterpretation)`,
  returns the parsed object. On a model refusal/empty parse, raises — the caller's
  existing `try/except` produces the fallback.
- `run_tool_loop(messages, tools, *, max_tokens, temperature) -> AssistantMessage`
  — one model call returning either `tool_calls` or `content`; `ChatAgent` owns
  iteration.

`assistant._complete_structured` is rewritten to call `complete_structured`.
**Deleted:** `_parse_structured_output` (brace-hunting) and the
`STRUCTURED_OUTPUT_PT` append. Prompts keep semantic field guidance (what
`summary`/`irrigation_advice` should contain, the qualitative-language rules in
`PROBE_ADVISORY_PT`) but drop the now-redundant JSON-skeleton blocks. The
fallback's misleading 0.65 confidence drops to ≤0.3, since fallback now only fires
on a real API/refusal error, not a parse miss.

`requires openai>=1.40.0` (already the pinned floor) for `.parse`.

## Mock client (CI runs `LLM_PROVIDER=mock`)

`MockChatClient` mirrors both new methods deterministically:

- `complete_structured` → builds a valid `AgronomicInterpretation` from the
  existing keyword matching.
- `run_tool_loop` → returns prose by default; if the user message matches a
  write-intent keyword (`override`/`substituir`/`aceitar`/`rejeitar`/`recalibrar`/
  `regar … mm`), returns the matching `propose_*` tool call with parsed params.

This keeps CI green while exercising both the prose path and the proposed-action
path without real network calls.

## Frontend confirm-card flow (`ChatPanel.tsx`)

- **History:** `sendMessage` sends `{ message, history, sector_id }`. `chatApi.chat`
  gains `history`; `types/index.ts` gets `ChatTurn`, `ProposedAction`, extended
  `ChatResponse`.
- **Prose:** `reply` renders in the existing `whitespace-pre-wrap` bubble.
- **Confirm card:** when `proposed_action` is present, render a card with the PT
  `summary` + **Confirmar** / **Cancelar**.
  - **Confirmar** dispatches via a `type → wrapper` map:
    - `override_recommendation` → `recommendationsApi.override(recId, params)`
    - `accept_recommendation` → `recommendationsApi.accept(recId)`
    - `reject_recommendation` → `recommendationsApi.reject(recId, params.reason)`
    - `regenerate_recommendation` → `recommendationsApi.generateRecommendation(sectorId)`
    - `run_calibration` → `calibrationApi.run(sectorId)`
    On success, push an assistant confirmation message and disable the card. On
    error, push the failure and keep the card.
  - **Cancelar** dismisses the card and pushes "Acção cancelada."
- The card is single-use (disabled after confirm/cancel) so a stale proposal can't
  be re-fired.

All write wrappers already exist in `lib/api.ts`; no new API plumbing beyond
`chatApi.chat` gaining `history`.

## Test plan (all via mock provider)

**Backend** (`tests/test_ai/`):
- `test_chat_agent.py` *(new)*: prose reply path; history accepted & trimmed to 8;
  write-intent message yields correct `proposed_action.type` + params; foreign
  `sector_id` passed to a tool returns an error result, not data; iteration cap
  terminates.
- `test_tools.py` *(new)*: each read tool returns expected shape; access-denied
  returns `{"error": ...}`; propose tools never mutate the DB.
- `test_assistant.py` *(update)*: structured path goes through native
  `complete_structured` and still returns a valid `AgronomicInterpretation`;
  fallback confidence ≤0.3.

**Frontend** (Vitest):
- `ChatPanel` sends history; renders the proposed-action card; **Confirmar** calls
  the mapped wrapper; card disables after use.

## Out of scope (other roadmap items, deferred)

Server-side chat persistence, streaming, rate-limiting on chat, response caching
on chat, retry/timeout on the OpenAI client. No real OpenAI calls in CI.
