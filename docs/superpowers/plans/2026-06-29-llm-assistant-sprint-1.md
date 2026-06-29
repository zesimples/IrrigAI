# LLM Assistant — Sprint 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the IrrigAI chat assistant conversation memory, prose answers, a server-side tool loop that can read data beyond the current scope and *propose* (never execute) state-changing actions, and migrate every structured "card" endpoint to native OpenAI Structured Outputs.

**Architecture:** Two tracks sharing one OpenAI client. Track 1 swaps the structured-output path to the SDK's native `.parse` (json_schema). Track 2 adds a new agentic chat loop (`ChatAgent`) backed by a tool registry (`ai/tools.py`); read tools execute server-side with per-tenant access checks, `propose_*` tools return a `ProposedAction` the frontend confirms and executes via existing typed endpoints. The LLM never decides agronomic numbers and never performs a write.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, `openai>=1.40.0`, pytest-asyncio (`asyncio_mode=auto`), Next.js 14 / React, Vitest.

## Global Constraints

- `openai>=1.40.0` — required for `client.beta.chat.completions.parse`. Already the pinned floor in `backend/pyproject.toml`.
- CI runs `LLM_PROVIDER=mock` for all providers — every new client method MUST be mirrored on `MockChatClient` and behave deterministically with no network calls.
- The LLM never computes agronomic values and never executes writes. Writes are propose-only; the frontend calls existing typed endpoints after user confirmation.
- Every tool validates per-tenant ownership via `AccessController` (`app/access.py`) before returning data: farm tools → `access.farm(id)`, sector tools → `access.sector(id)`, recommendation tools → `access.recommendation(id)`. A denied/missing id returns `{"error": "not_found_or_forbidden"}`, never data.
- Untrusted chat history goes only into `user`/`assistant` message slots — never concatenated into the system prompt.
- Language: Portuguese (Portugal). Default `DEFAULT_LANGUAGE=pt`.
- History trimmed server-side to the last 8 turns. Agentic loop capped at 4 iterations.
- Python: ruff, line-length 100, target py312. Commit frequently (one commit per task).

## File structure

| File | Responsibility |
|---|---|
| `backend/app/ai/openai_client.py` *(modify)* | Add `complete_structured`, `run_tool_loop`, normalized `LLMToolResponse`/`LLMToolCall` dataclasses, `LLMRefusalError`. Mirror new methods on `MockChatClient`. |
| `backend/app/ai/assistant.py` *(modify)* | Rewrite `_complete_structured` to use `complete_structured`; delete `_parse_structured_output`; lower fallback confidence. |
| `backend/app/ai/prompt_templates.py` *(modify)* | Delete `STRUCTURED_OUTPUT_PT`; trim the JSON skeleton block from `PROBE_ADVISORY_PT`; add `CHAT_AGENT_SYSTEM_PT`. |
| `backend/app/schemas/ai.py` *(modify)* | Add `ChatTurn`, `ProposedAction`; extend `ChatResponse` (in `chat.py`). |
| `backend/app/ai/tools.py` *(new)* | Tool specs (`TOOL_SPECS`) + `execute_tool(...)` executor (read + propose). |
| `backend/app/ai/chat_agent.py` *(new)* | `ChatAgent.run(...)` loop; history trimming; scope seeding. |
| `backend/app/api/v1/chat.py` *(modify)* | `farm_chat` → `ChatAgent`; new request/response shapes; `get_chat_agent` dependency. |
| `backend/tests/test_ai/test_openai_client.py` *(modify)* | Tests for mock `complete_structured` + `run_tool_loop`. |
| `backend/tests/test_ai/test_tools.py` *(new)* | Read-tool shapes, access denial, propose tools no-mutation. |
| `backend/tests/test_ai/test_chat_agent.py` *(new)* | Prose path, history trim, proposed-action path, foreign-id denial, iteration cap. |
| `backend/tests/test_ai/test_assistant.py` *(modify)* | Structured path via native `complete_structured`; fallback confidence ≤0.3. |
| `frontend/src/types/index.ts` *(modify)* | `ChatTurn`, `ProposedAction`, extended chat response. |
| `frontend/src/lib/api.ts` *(modify)* | `chatApi.chat` gains `history`. |
| `frontend/src/components/chat/ChatPanel.tsx` *(modify)* | Send history; render prose; confirm card + dispatch. |
| `frontend/src/components/chat/ChatPanel.test.tsx` *(new)* | History sent; confirm card; dispatch on confirm. |

---

## Task 1: Native Structured Outputs on the client

**Files:**
- Modify: `backend/app/ai/openai_client.py`
- Test: `backend/tests/test_ai/test_openai_client.py`

**Interfaces:**
- Produces:
  - `class LLMRefusalError(Exception)`
  - `OpenAIChatClient.complete_structured(system_prompt: str, user_message: str, schema_model: type[BaseModel], *, max_tokens: int = 900, temperature: float = 0.1) -> BaseModel`
  - `MockChatClient.complete_structured(...)` — same signature, returns an `AgronomicInterpretation` instance.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_ai/test_openai_client.py`:

```python
from app.schemas.ai import AgronomicInterpretation


@pytest.mark.asyncio
async def test_mock_complete_structured_returns_valid_interpretation():
    client = MockChatClient()
    result = await client.complete_structured(
        system_prompt="Interpreta a recomendação de irrigar o setor",
        user_message="Explica",
        schema_model=AgronomicInterpretation,
    )
    assert isinstance(result, AgronomicInterpretation)
    assert result.summary
    assert result.risk_level in ("low", "medium", "high")
    assert 0.0 <= result.confidence_score <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ai/test_openai_client.py::test_mock_complete_structured_returns_valid_interpretation -x -q`
Expected: FAIL — `AttributeError: 'MockChatClient' object has no attribute 'complete_structured'`.

- [ ] **Step 3: Implement on both clients**

In `backend/app/ai/openai_client.py`, add imports at the top:

```python
from pydantic import BaseModel
from app.schemas.ai import AgronomicEvidence, AgronomicInterpretation
```

Add after the imports (module level):

```python
class LLMRefusalError(Exception):
    """Raised when the model refuses to produce structured output."""
```

Add this method to `OpenAIChatClient` (after `complete`):

```python
    async def complete_structured(
        self,
        system_prompt: str,
        user_message: str,
        schema_model: type[BaseModel],
        *,
        max_tokens: int = 900,
        temperature: float = 0.1,
    ) -> BaseModel:
        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format=schema_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = response.usage
            if usage:
                ai_tokens_input_total.labels("openai", self.model).inc(usage.prompt_tokens)
                ai_tokens_output_total.labels("openai", self.model).inc(usage.completion_tokens)
            message = response.choices[0].message
            if getattr(message, "refusal", None):
                ai_requests_total.labels("openai", self.model, "refusal").inc()
                raise LLMRefusalError(message.refusal)
            if message.parsed is None:
                ai_requests_total.labels("openai", self.model, "failure").inc()
                raise LLMRefusalError("empty parsed structured output")
            ai_requests_total.labels("openai", self.model, "success").inc()
            return message.parsed
        except LLMRefusalError:
            raise
        except Exception:
            ai_requests_total.labels("openai", self.model, "failure").inc()
            raise
```

Add this method to `MockChatClient` (after `complete`):

```python
    async def complete_structured(
        self,
        system_prompt: str,
        user_message: str,
        schema_model: type[BaseModel],
        *,
        max_tokens: int = 900,
        temperature: float = 0.1,
    ) -> BaseModel:
        prompt_lower = system_prompt.lower()
        if "irrigar" in prompt_lower or "irrigate" in prompt_lower:
            risk, advice = "high", "Regar este setor — depleção acima do limiar."
        elif "skip" in prompt_lower or "defer" in prompt_lower or "não regar" in prompt_lower:
            risk, advice = "low", "Não regar — o balanço hídrico tem reserva suficiente."
        else:
            risk, advice = "medium", "Monitorizar a evolução do solo antes de alterar a rega."
        return AgronomicInterpretation(
            summary="Análise simulada do estado hídrico do setor.",
            risk_level=risk,  # type: ignore[arg-type]
            irrigation_advice=advice,
            evidence=[AgronomicEvidence(source="water_balance", value="depleção dentro do esperado")],
            missing_data=[],
            confidence_score=0.7,
            confidence_explanation="Resposta simulada para testes.",
            recommended_actions=["Validar com observação de campo."],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ai/test_openai_client.py -x -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/openai_client.py backend/tests/test_ai/test_openai_client.py
git commit -m "feat(ai): native structured-output client method (complete_structured)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Migrate the structured card path to native output

**Files:**
- Modify: `backend/app/ai/assistant.py` (`_complete_structured`, remove `_parse_structured_output`)
- Modify: `backend/app/ai/prompt_templates.py` (delete `STRUCTURED_OUTPUT_PT`, trim `PROBE_ADVISORY_PT` skeleton)
- Test: `backend/tests/test_ai/test_assistant.py`

**Interfaces:**
- Consumes: `OpenAIChatClient.complete_structured` / `MockChatClient.complete_structured` (Task 1).
- Produces: unchanged public methods (`explain_recommendation_structured`, `diagnose_sector_structured`, `summarize_farm_structured`, `interpret_probe_patterns_structured`, `analyze_sector_changes`) still return `AgronomicInterpretation`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_ai/test_assistant.py`:

```python
@pytest.mark.asyncio
async def test_complete_structured_uses_native_parse(monkeypatch):
    """The structured path must call client.complete_structured, not parse JSON text."""
    from app.schemas.ai import AgronomicInterpretation

    client = MockChatClient()
    called = {}

    async def spy_complete_structured(system, user, schema, **kw):
        called["hit"] = True
        return AgronomicInterpretation(
            summary="ok", risk_level="low", irrigation_advice="monitorizar",
            evidence=[], missing_data=[], confidence_score=0.8,
            confidence_explanation="teste", recommended_actions=[],
        )

    monkeypatch.setattr(client, "complete_structured", spy_complete_structured)
    assistant = IrrigationAssistant(
        context_builder=AssistantContextBuilder(), client=client, language="pt"
    )
    result = await assistant._complete_structured(
        system_prompt="x", user_message="y", context={"known_limitations": []},
    )
    assert called.get("hit") is True
    assert result.summary == "ok"


@pytest.mark.asyncio
async def test_complete_structured_fallback_low_confidence_on_error(monkeypatch):
    client = MockChatClient()

    async def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(client, "complete_structured", boom)
    assistant = IrrigationAssistant(
        context_builder=AssistantContextBuilder(), client=client, language="pt"
    )
    result = await assistant._complete_structured(
        system_prompt="x", user_message="y", context={"known_limitations": ["sem sondas"]},
    )
    assert result.confidence_score <= 0.3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ai/test_assistant.py::test_complete_structured_uses_native_parse -x -q`
Expected: FAIL — current `_complete_structured` calls `self.client.complete`, so the spy on `complete_structured` is never hit (`called` empty → AssertionError).

- [ ] **Step 3: Rewrite `_complete_structured` and delete the JSON parser**

In `backend/app/ai/assistant.py`, replace the entire `_complete_structured` method body with:

```python
    async def _complete_structured(
        self,
        *,
        system_prompt: str,
        user_message: str,
        context: dict | list | None,
        fallback_risk: str = "medium",
        max_tokens: int = 900,
    ) -> AgronomicInterpretation:
        try:
            parsed = await self.client.complete_structured(
                system_prompt,
                user_message,
                AgronomicInterpretation,
                max_tokens=max_tokens,
                temperature=0.1,
            )
        except Exception:
            parsed = self._fallback_structured(
                "",
                context=context,
                risk_level=fallback_risk,
                confidence_score=0.3,
            )

        if not parsed.evidence:
            parsed.evidence = self._default_evidence(context)
        if not parsed.missing_data:
            parsed.missing_data = self._known_limitations(context)
        return parsed
```

Delete the entire `_parse_structured_output` method (no longer referenced).

- [ ] **Step 4: Remove the now-redundant prompt scaffolding**

In `backend/app/ai/prompt_templates.py`:
- Delete the `STRUCTURED_OUTPUT_PT = """ ... """` block entirely.
- In `PROBE_ADVISORY_PT`, delete the block from the line `FORMATO ESTRUTURADO OBRIGATÓRIO — responde APENAS com JSON válido, sem Markdown:` through the closing `}}` skeleton (the literal `{{ ... }}` JSON example and the lines listing `"source"`/`"value"` rules immediately after it). Keep everything above (the agronomic content rules) and the trailing `ESTATÍSTICAS DA SONDA:\n{signal_json}` line. The `{signal_json}` placeholder MUST remain.

Verify no other references remain:

Run: `cd backend && grep -rn "STRUCTURED_OUTPUT_PT\|_parse_structured_output" app/ | grep -v ".pyc"`
Expected: no output.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai/test_assistant.py -x -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/assistant.py backend/app/ai/prompt_templates.py backend/tests/test_ai/test_assistant.py
git commit -m "refactor(ai): structured card path uses native json_schema; drop brace parser

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Chat schemas (ChatTurn, ProposedAction)

**Files:**
- Modify: `backend/app/schemas/ai.py`
- Test: `backend/tests/test_ai/test_chat_agent.py` (created here, expanded in Task 6)

**Interfaces:**
- Produces:
  - `class ChatTurn(BaseModel)` — `role: Literal["user", "assistant"]`, `content: str`
  - `class ProposedAction(BaseModel)` — `type`, `summary`, `sector_id`, `recommendation_id`, `params`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ai/test_chat_agent.py`:

```python
"""Tests for the agentic chat layer (schemas, tools, ChatAgent)."""

from __future__ import annotations

import pytest

from app.schemas.ai import ChatTurn, ProposedAction


def test_chat_turn_rejects_bad_role():
    with pytest.raises(Exception):
        ChatTurn(role="system", content="x")


def test_proposed_action_minimal():
    a = ProposedAction(type="run_calibration", summary="Calibrar setor", sector_id="sec-1")
    assert a.type == "run_calibration"
    assert a.params == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ai/test_chat_agent.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'ChatTurn'`.

- [ ] **Step 3: Add the schemas**

Append to `backend/app/schemas/ai.py`:

```python
ProposedActionType = Literal[
    "override_recommendation",
    "accept_recommendation",
    "reject_recommendation",
    "regenerate_recommendation",
    "run_calibration",
]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ProposedAction(BaseModel):
    type: ProposedActionType
    summary: str
    sector_id: str | None = None
    recommendation_id: str | None = None
    params: dict = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ai/test_chat_agent.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/ai.py backend/tests/test_ai/test_chat_agent.py
git commit -m "feat(ai): ChatTurn and ProposedAction schemas

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Tool registry and executor (`ai/tools.py`)

**Files:**
- Create: `backend/app/ai/tools.py`
- Test: `backend/tests/test_ai/test_tools.py`

**Interfaces:**
- Consumes: `AccessController` (`app/access.py`), `AssistantContextBuilder`, `get_sector_water_events`, `get_weather_summary`, `build_sector_change_context` (`app/ai/context_builder.py`), `ProposedAction` (Task 3).
- Produces:
  - `TOOL_SPECS: list[dict]` — OpenAI function specs.
  - `class ToolScope` — `farm_id: str | None`, `sector_id: str | None`.
  - `async def execute_tool(name: str, args: dict, *, access: AccessController, db: AsyncSession, scope: ToolScope) -> dict`
    - Read tools return a compact data dict, or `{"error": "not_found_or_forbidden"}`.
    - `propose_*` tools return `{"proposed_action": <ProposedAction.model_dump()>, "status": "awaiting_confirmation"}` or `{"error": ...}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ai/test_tools.py`:

```python
"""Tests for the chat tool registry/executor (no network, no LLM)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.ai.tools import TOOL_SPECS, ToolScope, execute_tool


def test_tool_specs_shape():
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert "get_sector_status" in names
    assert "propose_override" in names
    for t in TOOL_SPECS:
        assert t["type"] == "function"
        assert "parameters" in t["function"]


@pytest.mark.asyncio
async def test_read_tool_access_denied_returns_error():
    access = AsyncMock()
    access.sector.side_effect = HTTPException(status_code=404)
    db = AsyncMock()
    out = await execute_tool(
        "get_sector_status", {"sector_id": "foreign"},
        access=access, db=db, scope=ToolScope(farm_id="f1", sector_id=None),
    )
    assert out == {"error": "not_found_or_forbidden"}


@pytest.mark.asyncio
async def test_propose_override_no_mutation_and_validates_access():
    access = AsyncMock()
    access.recommendation.return_value = object()  # ownership ok
    db = AsyncMock()
    out = await execute_tool(
        "propose_override",
        {"recommendation_id": "rec-1", "depth_mm": 15, "reason": "campo seco"},
        access=access, db=db, scope=ToolScope(farm_id="f1", sector_id="sec-1"),
    )
    assert out["status"] == "awaiting_confirmation"
    pa = out["proposed_action"]
    assert pa["type"] == "override_recommendation"
    assert pa["recommendation_id"] == "rec-1"
    assert pa["params"]["custom_depth_mm"] == 15
    db.commit.assert_not_called()  # propose-only: never writes


@pytest.mark.asyncio
async def test_propose_run_calibration_uses_scope_sector():
    access = AsyncMock()
    access.sector.return_value = object()
    db = AsyncMock()
    out = await execute_tool(
        "propose_run_calibration", {},
        access=access, db=db, scope=ToolScope(farm_id="f1", sector_id="sec-9"),
    )
    assert out["proposed_action"]["type"] == "run_calibration"
    assert out["proposed_action"]["sector_id"] == "sec-9"
    db.commit.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ai/test_tools.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.tools'`.

- [ ] **Step 3: Implement the tool registry**

Create `backend/app/ai/tools.py`:

```python
"""Chat tool registry + executor.

Read tools fetch data (access-checked); propose_* tools return a ProposedAction
and NEVER execute a write. The LLM can pass any id, so every tool validates
ownership via AccessController before returning anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import AccessController
from app.ai.context_builder import (
    AssistantContextBuilder,
    build_sector_change_context,
    get_sector_water_events,
    get_weather_summary,
)
from app.schemas.ai import ProposedAction


@dataclass
class ToolScope:
    farm_id: str | None
    sector_id: str | None


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_farm_overview",
            "description": "Lista os setores da exploração com a decisão de rega mais recente (irrigate/skip/defer) e a depleção. Usa para responder 'o que preciso de regar hoje?'.",
            "parameters": {
                "type": "object",
                "properties": {"farm_id": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_status",
            "description": "Estado hídrico atual de um setor: ação recomendada, depleção, confiança, qualidade dos dados e razões.",
            "parameters": {
                "type": "object",
                "properties": {"sector_id": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_probe_readings",
            "description": "Resumo recente das leituras de sonda por profundidade (primeira/última, delta, médias) numa janela de horas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_id": {"type": "string"},
                    "window_hours": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_water_events",
            "description": "Eventos de rega/chuva detetados num setor nos últimos N dias.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_id": {"type": "string"},
                    "days": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Observações meteorológicas recentes e previsão de curto prazo da exploração.",
            "parameters": {
                "type": "object",
                "properties": {"farm_id": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_override",
            "description": "Propõe substituir a recomendação de um setor (NÃO executa). Requer recommendation_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recommendation_id": {"type": "string"},
                    "depth_mm": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["recommendation_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_accept_recommendation",
            "description": "Propõe aceitar a recomendação atual (NÃO executa). Requer recommendation_id.",
            "parameters": {
                "type": "object",
                "properties": {"recommendation_id": {"type": "string"}},
                "required": ["recommendation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_reject_recommendation",
            "description": "Propõe rejeitar a recomendação atual (NÃO executa). Requer recommendation_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recommendation_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["recommendation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_regenerate_recommendation",
            "description": "Propõe gerar uma nova recomendação para o setor (NÃO executa).",
            "parameters": {
                "type": "object",
                "properties": {"sector_id": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_run_calibration",
            "description": "Propõe correr a Calibração AI do setor (NÃO executa).",
            "parameters": {
                "type": "object",
                "properties": {"sector_id": {"type": "string"}},
                "required": [],
            },
        },
    },
]

_ACCESS_DENIED = {"error": "not_found_or_forbidden"}


def _resolve(args: dict, scope: ToolScope, key: str) -> str | None:
    return args.get(key) or getattr(scope, key, None)


async def execute_tool(
    name: str,
    args: dict,
    *,
    access: AccessController,
    db: AsyncSession,
    scope: ToolScope,
) -> dict:
    try:
        if name == "get_farm_overview":
            return await _get_farm_overview(_resolve(args, scope, "farm_id"), access, db)
        if name == "get_sector_status":
            return await _get_sector_status(_resolve(args, scope, "sector_id"), access, db)
        if name == "get_probe_readings":
            return await _get_probe_readings(
                _resolve(args, scope, "sector_id"), args.get("window_hours", 72), access, db
            )
        if name == "get_water_events":
            return await _get_water_events(
                _resolve(args, scope, "sector_id"), args.get("days", 14), access, db
            )
        if name == "get_weather":
            return await _get_weather(_resolve(args, scope, "farm_id"), access, db)
        if name.startswith("propose_"):
            return await _propose(name, args, access, db, scope)
        return {"error": f"unknown_tool:{name}"}
    except HTTPException:
        return _ACCESS_DENIED


async def _get_farm_overview(farm_id, access, db) -> dict:
    if not farm_id:
        return {"error": "missing_farm_id"}
    await access.farm(farm_id)
    ctx = await AssistantContextBuilder().build_farm_context(farm_id, db)
    sectors = []
    for s in ctx.sectors:
        depletion_pct = None
        if s.rootzone_depletion_mm is not None and s.rootzone_taw_mm:
            depletion_pct = round(s.rootzone_depletion_mm / s.rootzone_taw_mm * 100, 1)
        sectors.append({
            "sector_id": s.sector_id,
            "name": s.sector_name,
            "action": s.recommendation_action,
            "depletion_pct": depletion_pct,
            "confidence": s.confidence_level,
        })
    return {"farm": ctx.farm_name, "sectors": sectors, "active_alerts": ctx.total_active_alerts}


async def _get_sector_status(sector_id, access, db) -> dict:
    if not sector_id:
        return {"error": "missing_sector_id"}
    await access.sector(sector_id)
    s = await AssistantContextBuilder().build_sector_context(sector_id, db)
    return {
        "sector_id": s.sector_id,
        "name": s.sector_name,
        "crop_type": s.crop_type,
        "action": s.recommendation_action,
        "irrigation_depth_mm": s.irrigation_depth_mm,
        "depletion_mm": s.rootzone_depletion_mm,
        "taw_mm": s.rootzone_taw_mm,
        "confidence_level": s.confidence_level,
        "source_confidence": s.source_confidence,
        "data_quality_explanation": s.data_quality_explanation,
        "reasons": s.reasons,
        "active_alerts": s.active_alerts,
    }


async def _get_probe_readings(sector_id, window_hours, access, db) -> dict:
    if not sector_id:
        return {"error": "missing_sector_id"}
    await access.sector(sector_id)
    ctx = await build_sector_change_context(sector_id, db, window_hours=window_hours)
    if ctx.get("error"):
        return {"error": ctx["error"]}
    return {"window_hours": ctx.get("window_hours"), "probe_changes": ctx.get("probe_changes", [])}


async def _get_water_events(sector_id, days, access, db) -> dict:
    if not sector_id:
        return {"error": "missing_sector_id"}
    await access.sector(sector_id)
    return {"water_events": await get_sector_water_events(sector_id, db, days=days)}


async def _get_weather(farm_id, access, db) -> dict:
    if not farm_id:
        return {"error": "missing_farm_id"}
    await access.farm(farm_id)
    return await get_weather_summary(farm_id, db)


async def _propose(name, args, access, db, scope) -> dict:
    if name in ("propose_override", "propose_accept_recommendation", "propose_reject_recommendation"):
        rec_id = args.get("recommendation_id")
        if not rec_id:
            return {"error": "missing_recommendation_id"}
        try:
            await access.recommendation(rec_id)
        except HTTPException:
            return _ACCESS_DENIED
        if name == "propose_override":
            depth = args.get("depth_mm")
            reason = args.get("reason", "")
            action = ProposedAction(
                type="override_recommendation",
                summary=f"Substituir a recomendação para {depth} mm — {reason}".strip(),
                recommendation_id=rec_id,
                sector_id=scope.sector_id,
                params={"custom_depth_mm": depth, "override_reason": reason},
            )
        elif name == "propose_accept_recommendation":
            action = ProposedAction(
                type="accept_recommendation",
                summary="Aceitar a recomendação atual.",
                recommendation_id=rec_id,
                sector_id=scope.sector_id,
            )
        else:
            reason = args.get("reason", "")
            action = ProposedAction(
                type="reject_recommendation",
                summary="Rejeitar a recomendação atual.",
                recommendation_id=rec_id,
                sector_id=scope.sector_id,
                params={"notes": reason} if reason else {},
            )
    else:
        sector_id = args.get("sector_id") or scope.sector_id
        if not sector_id:
            return {"error": "missing_sector_id"}
        try:
            await access.sector(sector_id)
        except HTTPException:
            return _ACCESS_DENIED
        if name == "propose_regenerate_recommendation":
            action = ProposedAction(
                type="regenerate_recommendation",
                summary="Gerar uma nova recomendação para o setor.",
                sector_id=sector_id,
            )
        else:  # propose_run_calibration
            action = ProposedAction(
                type="run_calibration",
                summary="Correr a Calibração AI do setor.",
                sector_id=sector_id,
            )
    return {"proposed_action": action.model_dump(), "status": "awaiting_confirmation"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai/test_tools.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/tools.py backend/tests/test_ai/test_tools.py
git commit -m "feat(ai): chat tool registry + access-checked executor (read + propose)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `run_tool_loop` on both clients

**Files:**
- Modify: `backend/app/ai/openai_client.py`
- Test: `backend/tests/test_ai/test_openai_client.py`

**Interfaces:**
- Produces:
  - `@dataclass LLMToolCall` — `id: str`, `name: str`, `arguments: dict`
  - `@dataclass LLMToolResponse` — `content: str | None`, `tool_calls: list[LLMToolCall]`
  - `OpenAIChatClient.run_tool_loop(messages: list[dict], tools: list[dict], *, max_tokens: int = 700, temperature: float = 0.2) -> LLMToolResponse`
  - `MockChatClient.run_tool_loop(...)` — deterministic: returns a `propose_*` tool call on write-intent keywords, else prose; returns prose once a tool result is already present in `messages` (loop terminates).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_ai/test_openai_client.py`:

```python
@pytest.mark.asyncio
async def test_mock_run_tool_loop_prose_by_default():
    client = MockChatClient()
    resp = await client.run_tool_loop(
        messages=[{"role": "user", "content": "Quanto choveu esta semana?"}],
        tools=[],
    )
    assert resp.tool_calls == []
    assert resp.content


@pytest.mark.asyncio
async def test_mock_run_tool_loop_proposes_calibration_on_keyword():
    client = MockChatClient()
    resp = await client.run_tool_loop(
        messages=[{"role": "user", "content": "Podes recalibrar este setor?"}],
        tools=[],
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "propose_run_calibration"


@pytest.mark.asyncio
async def test_mock_run_tool_loop_terminates_after_tool_result():
    client = MockChatClient()
    resp = await client.run_tool_loop(
        messages=[
            {"role": "user", "content": "recalibrar"},
            {"role": "assistant", "content": None},
            {"role": "tool", "tool_call_id": "t1", "content": "{}"},
        ],
        tools=[],
    )
    assert resp.tool_calls == []
    assert resp.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ai/test_openai_client.py::test_mock_run_tool_loop_prose_by_default -x -q`
Expected: FAIL — `AttributeError: 'MockChatClient' object has no attribute 'run_tool_loop'`.

- [ ] **Step 3: Implement on both clients**

In `backend/app/ai/openai_client.py`, add to the imports / top-level dataclasses:

```python
import json as _json
import re as _re
from dataclasses import dataclass, field


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMToolResponse:
    content: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
```

Add to `OpenAIChatClient`:

```python
    async def run_tool_loop(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int = 700,
        temperature: float = 0.2,
    ) -> LLMToolResponse:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else None,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = response.usage
            if usage:
                ai_tokens_input_total.labels("openai", self.model).inc(usage.prompt_tokens)
                ai_tokens_output_total.labels("openai", self.model).inc(usage.completion_tokens)
            ai_requests_total.labels("openai", self.model, "success").inc()
            msg = response.choices[0].message
            calls: list[LLMToolCall] = []
            for tc in msg.tool_calls or []:
                try:
                    parsed_args = _json.loads(tc.function.arguments or "{}")
                except _json.JSONDecodeError:
                    parsed_args = {}
                calls.append(LLMToolCall(id=tc.id, name=tc.function.name, arguments=parsed_args))
            return LLMToolResponse(content=msg.content, tool_calls=calls)
        except Exception:
            ai_requests_total.labels("openai", self.model, "failure").inc()
            raise
```

Add to `MockChatClient`:

```python
    async def run_tool_loop(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int = 700,
        temperature: float = 0.2,
    ) -> LLMToolResponse:
        # If a tool result is already present, produce the final prose answer.
        if any(m.get("role") == "tool" for m in messages):
            return LLMToolResponse(
                content="Registei a proposta. Confirma na aplicação para a aplicar.",
                tool_calls=[],
            )
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = (m.get("content") or "").lower()
                break
        if "recalibr" in last_user or "calibra" in last_user:
            return LLMToolResponse(content=None, tool_calls=[
                LLMToolCall(id="mock-1", name="propose_run_calibration", arguments={})
            ])
        if "gerar" in last_user or "nova recomenda" in last_user or "regenera" in last_user:
            return LLMToolResponse(content=None, tool_calls=[
                LLMToolCall(id="mock-1", name="propose_regenerate_recommendation", arguments={})
            ])
        if "aceitar" in last_user:
            return LLMToolResponse(content=None, tool_calls=[
                LLMToolCall(id="mock-1", name="propose_accept_recommendation",
                            arguments={"recommendation_id": "rec-mock"})
            ])
        if "substitu" in last_user or "override" in last_user or "regar" in last_user:
            m = _re.search(r"(\d+(?:\.\d+)?)\s*mm", last_user)
            depth = float(m.group(1)) if m else 10.0
            return LLMToolResponse(content=None, tool_calls=[
                LLMToolCall(id="mock-1", name="propose_override",
                            arguments={"recommendation_id": "rec-mock", "depth_mm": depth,
                                       "reason": "pedido do utilizador"})
            ])
        return LLMToolResponse(
            content=("Com base nos dados disponíveis, o setor está estável e não "
                     "requer rega imediata. Vigia a evolução nas próximas 24-48h."),
            tool_calls=[],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai/test_openai_client.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/openai_client.py backend/tests/test_ai/test_openai_client.py
git commit -m "feat(ai): run_tool_loop on real + mock clients with normalized response

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `ChatAgent` orchestration loop

**Files:**
- Create: `backend/app/ai/chat_agent.py`
- Modify: `backend/app/ai/prompt_templates.py` (add `CHAT_AGENT_SYSTEM_PT`)
- Test: `backend/tests/test_ai/test_chat_agent.py` (expand)

**Interfaces:**
- Consumes: `run_tool_loop` (Task 5), `execute_tool`/`ToolScope`/`TOOL_SPECS` (Task 4), `ChatTurn`/`ProposedAction` (Task 3), `AssistantContextBuilder`.
- Produces:
  - `@dataclass ChatResult` — `reply: str`, `proposed_action: ProposedAction | None`
  - `class ChatAgent` — `__init__(self, client, context_builder, language="pt")`; `async def run(self, *, farm_id, sector_id, message, history, access, db) -> ChatResult`
  - `MAX_HISTORY_TURNS = 8`, `MAX_ITERATIONS = 4`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ai/test_chat_agent.py`:

```python
from unittest.mock import AsyncMock

from app.ai.chat_agent import MAX_HISTORY_TURNS, ChatAgent
from app.ai.openai_client import MockChatClient
from app.ai.context_builder import AssistantContextBuilder


def _agent():
    return ChatAgent(
        client=MockChatClient(),
        context_builder=AssistantContextBuilder(),
        language="pt",
    )


@pytest.mark.asyncio
async def test_chat_agent_prose_reply(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "_seed_scope_context", AsyncMock(return_value={}))
    access = AsyncMock()
    db = AsyncMock()
    result = await agent.run(
        farm_id="f1", sector_id=None, message="Quanto choveu esta semana?",
        history=[], access=access, db=db,
    )
    assert result.proposed_action is None
    assert result.reply


@pytest.mark.asyncio
async def test_chat_agent_propose_calibration(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "_seed_scope_context", AsyncMock(return_value={}))
    access = AsyncMock()
    access.sector.return_value = object()
    db = AsyncMock()
    result = await agent.run(
        farm_id="f1", sector_id="sec-9", message="Podes recalibrar este setor?",
        history=[], access=access, db=db,
    )
    assert result.proposed_action is not None
    assert result.proposed_action.type == "run_calibration"
    assert result.proposed_action.sector_id == "sec-9"
    assert result.reply  # model writes a prose summary after proposing
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_chat_agent_trims_history(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "_seed_scope_context", AsyncMock(return_value={}))
    captured = {}

    async def fake_loop(messages, tools, **kw):
        captured["messages"] = messages
        from app.ai.openai_client import LLMToolResponse
        return LLMToolResponse(content="ok", tool_calls=[])

    monkeypatch.setattr(agent.client, "run_tool_loop", fake_loop)
    history = [ChatTurn(role="user", content=f"m{i}") for i in range(20)]
    await agent.run(
        farm_id="f1", sector_id=None, message="agora", history=history,
        access=AsyncMock(), db=AsyncMock(),
    )
    # system + <=8 history + current user
    assert len(captured["messages"]) <= 1 + MAX_HISTORY_TURNS + 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ai/test_chat_agent.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.chat_agent'`.

- [ ] **Step 3: Add the system prompt template**

Append to `backend/app/ai/prompt_templates.py`:

```python
CHAT_AGENT_SYSTEM_PT = """
És o assistente de rega da IrrigAI. Falas com o agricultor em português de Portugal, de forma directa e prática.

REGRAS:
- NUNCA decides valores agronómicos nem inventas números. O motor determinístico é a autoridade.
- Para responder a perguntas, podes chamar as ferramentas de leitura (get_sector_status, get_farm_overview, get_probe_readings, get_water_events, get_weather).
- Para QUALQUER alteração de estado (substituir, aceitar, rejeitar, gerar nova recomendação, calibrar) NÃO ages diretamente: chamas a ferramenta propose_* correspondente. NUNCA digas que executaste a acção — apenas que a propuseste para confirmação do utilizador.
- Quando uma ferramenta devolve "error", explica que não foi possível aceder a esse recurso; não inventes dados.
- Respostas curtas e úteis. Cita o que observaste nos dados.

CONTEXTO ATUAL (âmbito da conversa):
{scope_json}
"""
```

- [ ] **Step 4: Implement `ChatAgent`**

Create `backend/app/ai/chat_agent.py`:

```python
"""Agentic chat loop: history + tools, prose output, propose-only writes."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.access import AccessController
from app.ai import prompt_templates
from app.ai.context_builder import AssistantContextBuilder
from app.ai.openai_client import MockChatClient, OpenAIChatClient
from app.ai.tools import TOOL_SPECS, ToolScope, execute_tool
from app.schemas.ai import ChatTurn, ProposedAction

MAX_HISTORY_TURNS = 8
MAX_ITERATIONS = 4


@dataclass
class ChatResult:
    reply: str
    proposed_action: ProposedAction | None = None


class ChatAgent:
    def __init__(
        self,
        client: OpenAIChatClient | MockChatClient,
        context_builder: AssistantContextBuilder,
        language: str = "pt",
    ) -> None:
        self.client = client
        self.context_builder = context_builder
        self.language = language

    async def run(
        self,
        *,
        farm_id: str,
        sector_id: str | None,
        message: str,
        history: list[ChatTurn],
        access: AccessController,
        db: AsyncSession,
    ) -> ChatResult:
        scope = ToolScope(farm_id=farm_id, sector_id=sector_id)
        scope_ctx = await self._seed_scope_context(farm_id, sector_id, db)
        system = prompt_templates.CHAT_AGENT_SYSTEM_PT.format(
            scope_json=json.dumps(scope_ctx, ensure_ascii=False, default=str)
        )

        messages: list[dict] = [{"role": "system", "content": system}]
        for turn in history[-MAX_HISTORY_TURNS:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": message})

        proposed: ProposedAction | None = None
        last_content = ""

        for _ in range(MAX_ITERATIONS):
            resp = await self.client.run_tool_loop(messages, TOOL_SPECS)
            if not resp.tool_calls:
                return ChatResult(reply=resp.content or last_content or "", proposed_action=proposed)
            last_content = resp.content or last_content
            messages.append({
                "role": "assistant",
                "content": resp.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in resp.tool_calls
                ],
            })
            for tc in resp.tool_calls:
                result = await execute_tool(tc.name, tc.arguments, access=access, db=db, scope=scope)
                if proposed is None and "proposed_action" in result:
                    proposed = ProposedAction.model_validate(result["proposed_action"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        return ChatResult(
            reply=last_content or "Não consegui concluir a resposta. Tenta reformular.",
            proposed_action=proposed,
        )

    async def _seed_scope_context(
        self, farm_id: str, sector_id: str | None, db: AsyncSession
    ) -> dict:
        """Compact grounding context for the system prompt (best-effort)."""
        try:
            if sector_id:
                s = await self.context_builder.build_sector_context(sector_id, db)
                return {
                    "sector_id": s.sector_id,
                    "name": s.sector_name,
                    "action": s.recommendation_action,
                    "depletion_mm": s.rootzone_depletion_mm,
                    "confidence_level": s.confidence_level,
                    "source_confidence": s.source_confidence,
                }
            ctx = await self.context_builder.build_farm_context(farm_id, db)
            return {
                "farm": ctx.farm_name,
                "sector_count": len(ctx.sectors),
                "active_alerts": ctx.total_active_alerts,
            }
        except Exception:
            return {"farm_id": farm_id, "sector_id": sector_id}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai/test_chat_agent.py -x -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/chat_agent.py backend/app/ai/prompt_templates.py backend/tests/test_ai/test_chat_agent.py
git commit -m "feat(ai): ChatAgent agentic loop (history, tools, propose-only writes)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Wire the chat endpoint to `ChatAgent`

**Files:**
- Modify: `backend/app/api/v1/chat.py`
- Test: `backend/tests/test_api/test_chat_endpoint.py` (new)

**Interfaces:**
- Consumes: `ChatAgent` (Task 6), `ChatTurn`/`ProposedAction` (Task 3).
- Produces: `POST /farms/{farm_id}/chat` accepting `{message, history, sector_id}`, returning `{reply, proposed_action}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api/test_chat_endpoint.py`. This mirrors the seeding pattern in `tests/test_api/test_auto_calibration.py` (`_owned_chain` + `delete_farm_subtree`), seeding under the authenticated owner `you@irrigai.dev`:

```python
"""Chat endpoint integration tests (mock LLM provider)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Farm, Plot, Sector, User
from tests.test_api.conftest import delete_farm_subtree

_OWNER_EMAIL = "you@irrigai.dev"  # matches the authenticated `client` fixture


@pytest.fixture
async def chat_farm(db: AsyncSession):
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()
    farm = Farm(name="Chat Farm", owner_id=owner.id)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Chat Sector", crop_type="almond")
    db.add(sector)
    await db.commit()
    yield {"farm_id": farm.id, "sector_id": sector.id}
    await delete_farm_subtree(db, farm.id)


@pytest.mark.asyncio
async def test_chat_returns_prose_reply(client, chat_farm):
    resp = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={"message": "Quanto choveu esta semana?", "history": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"]
    assert body["proposed_action"] is None


@pytest.mark.asyncio
async def test_chat_accepts_history(client, chat_farm):
    resp = await client.post(
        f"/api/v1/farms/{chat_farm['farm_id']}/chat",
        json={
            "message": "e agora?",
            "history": [
                {"role": "user", "content": "olá"},
                {"role": "assistant", "content": "olá, em que posso ajudar?"},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["reply"]
```

> Confirm `delete_farm_subtree` is exported from `tests/test_api/conftest.py` (it is used by `test_auto_calibration.py`). If its signature differs, match that file's usage.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_api/test_chat_endpoint.py -x -q`
Expected: FAIL — response has no `proposed_action` key (current `ChatResponse` has `reply`/`structured`).

- [ ] **Step 3: Update the endpoint**

In `backend/app/api/v1/chat.py`:

Replace the import of `IrrigationAssistant`-based chat with an added agent dependency. Add imports:

```python
from app.ai.chat_agent import ChatAgent
from app.schemas.ai import ChatTurn, ProposedAction
```

Add a dependency factory near `get_assistant`:

```python
def get_chat_agent() -> ChatAgent:
    settings = get_settings()
    client = get_chat_client(settings)
    builder = AssistantContextBuilder()
    return ChatAgent(client=client, context_builder=builder, language=settings.DEFAULT_LANGUAGE)
```

Replace `ChatRequest` and `ChatResponse`:

```python
class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    sector_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    proposed_action: ProposedAction | None = None
```

Replace the `farm_chat` handler body:

```python
@router.post("/farms/{farm_id}/chat", response_model=ChatResponse)
async def farm_chat(
    farm_id: str,
    body: ChatRequest,
    access: Access,
    db: AsyncSession = Depends(get_db),
    agent: ChatAgent = Depends(get_chat_agent),
):
    """Conversational chat with memory + tools about the farm or a specific sector."""
    await access.farm(farm_id)
    if body.sector_id:
        await access.sector(body.sector_id)
    try:
        result = await agent.run(
            farm_id=farm_id,
            sector_id=body.sector_id,
            message=body.message,
            history=body.history,
            access=access,
            db=db,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Erro ao processar o pedido de chat.") from exc
    return ChatResponse(reply=result.reply, proposed_action=result.proposed_action)
```

> The old `IrrigationAssistant.chat_structured` import path stays for the other endpoints; only `farm_chat` changes. Leave `get_assistant` and the card endpoints untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_api/test_chat_endpoint.py -x -q`
Expected: PASS.

- [ ] **Step 5: Run the full backend AI + chat suite**

Run: `cd backend && pytest tests/test_ai tests/test_api/test_chat_endpoint.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/chat.py backend/tests/test_api/test_chat_endpoint.py
git commit -m "feat(api): chat endpoint uses ChatAgent (history + proposed_action)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Frontend types + API wrapper

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces:
  - `ChatTurn`, `ProposedAction`, `ChatResult` TS types.
  - `chatApi.chat(farmId, message, sectorId?, history?)` → `Promise<ChatResult>`.

- [ ] **Step 1: Add the types**

Append to `frontend/src/types/index.ts`:

```typescript
export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export type ProposedActionType =
  | "override_recommendation"
  | "accept_recommendation"
  | "reject_recommendation"
  | "regenerate_recommendation"
  | "run_calibration";

export interface ProposedAction {
  type: ProposedActionType;
  summary: string;
  sector_id?: string | null;
  recommendation_id?: string | null;
  params: Record<string, unknown>;
}

export interface ChatResult {
  reply: string;
  proposed_action: ProposedAction | null;
}
```

- [ ] **Step 2: Update the API wrapper**

In `frontend/src/lib/api.ts`, add `ChatResult` and `ChatTurn` to the existing type import from `@/types`, then replace `chatApi.chat`:

```typescript
  chat: (farmId: string, message: string, sectorId?: string, history: ChatTurn[] = []) =>
    post<ChatResult>(`/farms/${farmId}/chat`, {
      message,
      sector_id: sectorId ?? null,
      history,
    }),
```

- [ ] **Step 3: Verify the frontend type-checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (ChatPanel still compiles — it reads `r.reply`, which `ChatResult` provides).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/lib/api.ts
git commit -m "feat(web): chat types + history param on chatApi.chat

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: ChatPanel — history, prose, confirm card

**Files:**
- Modify: `frontend/src/components/chat/ChatPanel.tsx`
- Test: `frontend/src/components/chat/ChatPanel.test.tsx` (new)

**Interfaces:**
- Consumes: `chatApi.chat` (Task 8), `recommendationsApi.{override,accept,reject,generateRecommendation}`, `calibrationApi.run`, `ProposedAction` type.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/chat/ChatPanel.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";

vi.mock("@/lib/api", () => ({
  chatApi: { chat: vi.fn() },
  recommendationsApi: { override: vi.fn(), accept: vi.fn(), reject: vi.fn(), generateRecommendation: vi.fn() },
  calibrationApi: { run: vi.fn() },
}));

import { chatApi, calibrationApi } from "@/lib/api";

describe("ChatPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends history with the message", async () => {
    (chatApi.chat as any).mockResolvedValue({ reply: "olá!", proposed_action: null });
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "primeira" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await waitFor(() => expect(chatApi.chat).toHaveBeenCalledWith("f1", "primeira", undefined, []));
  });

  it("renders a confirm card and dispatches on confirm", async () => {
    (chatApi.chat as any).mockResolvedValue({
      reply: "Proponho calibrar.",
      proposed_action: { type: "run_calibration", summary: "Correr a Calibração AI.", sector_id: "sec-9", params: {} },
    });
    (calibrationApi.run as any).mockResolvedValue({});
    render(<ChatPanel farmId="f1" sectorId="sec-9" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "recalibrar" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("Correr a Calibração AI.");
    fireEvent.click(screen.getByText("Confirmar"));
    await waitFor(() => expect(calibrationApi.run).toHaveBeenCalledWith("sec-9"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/chat/ChatPanel.test.tsx`
Expected: FAIL — `chatApi.chat` called with 2 args (no history); no "Confirmar" button rendered.

- [ ] **Step 3: Update ChatPanel**

In `frontend/src/components/chat/ChatPanel.tsx`:

Add imports at the top (extend the existing api import):

```typescript
import { chatApi, recommendationsApi, calibrationApi } from "@/lib/api";
import type { ProposedAction } from "@/types";
```

Extend the `Message` interface and add a pending-action state:

```typescript
interface Message {
  role: "user" | "assistant";
  text: string;
  proposedAction?: ProposedAction | null;
  actionResolved?: boolean;
}
```

In `sendMessage`, send the history and carry the proposed action onto the assistant message. Replace the `try` block body:

```typescript
    try {
      const history = messages.map((m) => ({ role: m.role, content: m.text }));
      const r = await chatApi.chat(farmId, text, sectorId, history);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: r.reply, proposedAction: r.proposed_action },
      ]);
    } catch (e) {
      const detail = e instanceof Error ? e.message : "Erro desconhecido";
      pushAssistant(`Erro ao contactar o assistente: ${detail}. Tente novamente.`);
    } finally {
      setLoading(false);
    }
```

Add a dispatcher and confirm/cancel handlers inside the component:

```typescript
  async function dispatchAction(action: ProposedAction): Promise<string> {
    const p = action.params as Record<string, unknown>;
    switch (action.type) {
      case "override_recommendation":
        await recommendationsApi.override(action.recommendation_id as string, {
          custom_depth_mm: p.custom_depth_mm as number | undefined,
          override_reason: (p.override_reason as string) ?? "Ajuste via assistente",
        });
        return "Feito — recomendação substituída.";
      case "accept_recommendation":
        await recommendationsApi.accept(action.recommendation_id as string);
        return "Feito — recomendação aceite.";
      case "reject_recommendation":
        await recommendationsApi.reject(action.recommendation_id as string, p.notes as string | undefined);
        return "Feito — recomendação rejeitada.";
      case "regenerate_recommendation":
        await recommendationsApi.generateRecommendation(action.sector_id as string);
        return "Feito — nova recomendação gerada.";
      case "run_calibration":
        await calibrationApi.run(action.sector_id as string);
        return "Feito — calibração iniciada.";
      default:
        return "Acção não suportada.";
    }
  }

  function resolveAction(index: number) {
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, actionResolved: true } : m)),
    );
  }

  async function confirmAction(index: number, action: ProposedAction) {
    resolveAction(index);
    setLoading(true);
    try {
      const msg = await dispatchAction(action);
      pushAssistant(msg);
    } catch (e) {
      const detail = e instanceof Error ? e.message : "Erro desconhecido";
      pushAssistant(`Não foi possível executar a acção: ${detail}.`);
    } finally {
      setLoading(false);
    }
  }

  function cancelAction(index: number) {
    resolveAction(index);
    pushAssistant("Acção cancelada.");
  }
```

In the message render loop, after the assistant bubble, render the confirm card when present and unresolved. Replace the message `.map(...)` body's inner content with:

```tsx
        {messages.map((msg, i) => (
          <div key={i} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
                msg.role === "user" ? "bg-emerald-700 text-white" : "bg-slate-100 text-slate-800"
              }`}
            >
              {msg.text}
            </div>
            {msg.proposedAction && !msg.actionResolved && (
              <div className="mt-2 max-w-[85%] rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
                <p className="mb-2 font-medium text-amber-900">{msg.proposedAction.summary}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => confirmAction(i, msg.proposedAction!)}
                    disabled={loading}
                    className="rounded-full bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
                  >
                    Confirmar
                  </button>
                  <button
                    onClick={() => cancelAction(i)}
                    disabled={loading}
                    className="rounded-full border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/chat/ChatPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Type-check + lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/ChatPanel.tsx frontend/src/components/chat/ChatPanel.test.tsx
git commit -m "feat(web): ChatPanel sends history, renders prose + propose-action confirm card

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Backend suite**

Run: `cd backend && pytest -q`
Expected: PASS (no regressions; `LLM_PROVIDER=mock`).

- [ ] **Step 2: Frontend unit suite**

Run: `cd frontend && npm run test:run`
Expected: PASS.

- [ ] **Step 3: Lint**

Run: `cd backend && ruff check app/ai app/api/v1/chat.py app/schemas/ai.py`
Expected: no new errors (pre-existing `B008` on `Depends()` is not gated — ignore those).

- [ ] **Step 4: Sanity grep — no dead references**

Run: `cd backend && grep -rn "STRUCTURED_OUTPUT_PT\|_parse_structured_output" app/ | grep -v ".pyc"`
Expected: no output.

- [ ] **Step 5: Commit (if any lint fixes were applied)**

```bash
git add -A && git commit -m "chore(ai): sprint-1 lint/verification pass

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" || echo "nothing to commit"
```

---

## Self-review notes

- **Spec coverage:** #1 memory → Tasks 6/7/9 (history trimmed to 8, client-passed). #2 prose → Tasks 6/7 (returns `reply`, never `render_structured`). #3 native structured → Tasks 1/2 (shared `_complete_structured` path, all 5 card endpoints). #8 tool calling → Tasks 3/4/5/6/7/9 (read tools + propose-only writes, frontend confirm). Mock support → Tasks 1/5. Security/access → Task 4 + Global Constraints. Out-of-scope items (persistence/streaming/rate-limit/cache/retry) intentionally excluded.
- **Type consistency:** `LLMToolResponse`/`LLMToolCall` (Task 5) consumed in Task 6; `ToolScope`/`execute_tool`/`TOOL_SPECS` (Task 4) consumed in Task 6; `ProposedAction`/`ChatTurn` (Task 3) consumed in Tasks 4/6/7/8/9; override params (`custom_depth_mm`, `override_reason`) match `OverrideRequest` in `app/schemas/recommendation.py`; reject `notes` matches `RejectRequest`.
- **Test seeding:** Task 7 uses a self-contained `chat_farm` fixture copied from the `_owned_chain` + `delete_farm_subtree` pattern in `test_auto_calibration.py` — no missing shared fixture.
