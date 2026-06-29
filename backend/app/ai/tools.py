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
        return dict(_ACCESS_DENIED)


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
        await access.recommendation(rec_id)
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
        await access.sector(sector_id)
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
