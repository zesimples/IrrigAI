"""A0/A1 regressions for chat tool scope, field memory, and context reuse.

Chat weather used to be fetched farm-wide even in a sector conversation, so on a
per-plot-weather farm (Innoliva) the assistant answered one polo's question with
another polo's station. Saved field notes existed in the DB but no chat tool could
read them. And every sector context block rebuilt the whole canonical context.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.ai.tools import TOOL_SPECS, ToolScope, execute_tool


def _tool_names() -> set[str]:
    return {spec["function"]["name"] for spec in TOOL_SPECS}


class TestWeatherScope:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "name,arguments",
        [
            ("get_farm_overview", {"farm_id": "foreign"}),
            ("get_sector_status", {"sector_id": "other"}),
            ("get_weather", {"sector_id": "other"}),
            ("propose_run_calibration", {"sector_id": "other"}),
        ],
    )
    async def test_model_cannot_change_conversation_scope(self, name, arguments):
        access = AsyncMock()
        result = await execute_tool(
            name,
            arguments,
            access=access,
            db=AsyncMock(),
            scope=ToolScope(farm_id="owned", sector_id="selected"),
        )
        assert "error" in result
        access.farm.assert_not_awaited()
        access.sector_in_farm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_foreign_farm_argument_cannot_bypass_selected_sector(self):
        summary = AsyncMock()
        with patch("app.ai.tools.get_weather_summary", summary):
            result = await execute_tool(
                "get_weather",
                {"farm_id": "foreign"},
                access=AsyncMock(),
                db=AsyncMock(),
                scope=ToolScope(farm_id="owned", sector_id="s"),
            )
        assert "error" in result
        summary.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_farm_fallback_is_not_labelled_plot_weather(self):
        access = AsyncMock()
        access.sector_in_farm.return_value = SimpleNamespace(id="s", plot_id="p")
        with patch(
            "app.ai.tools.get_weather_summary",
            AsyncMock(
                return_value={"weather_plot_id": None, "recent_observations": [], "forecast": []}
            ),
        ):
            result = await execute_tool(
                "get_weather",
                {},
                access=access,
                db=AsyncMock(),
                scope=ToolScope(farm_id="f", sector_id="s"),
            )
        assert result["scope"]["level"] == "farm"
        assert result["scope"]["plot_id"] is None

    @pytest.mark.asyncio
    async def test_sector_conversation_resolves_weather_through_the_sector_plot(self):
        access = AsyncMock()
        access.sector_in_farm.return_value = SimpleNamespace(id="sec-1", plot_id="plot-a")
        summary = AsyncMock(return_value={"recent_observations": [], "forecast": []})

        with patch("app.ai.tools.get_weather_summary", summary):
            out = await execute_tool(
                "get_weather",
                {},
                access=access,
                db=AsyncMock(),
                scope=ToolScope(farm_id="farm-1", sector_id="sec-1"),
            )

        assert summary.await_args.kwargs["plot_id"] == "plot-a"
        assert out["scope"]["level"] == "plot"
        assert out["scope"]["plot_id"] == "plot-a"

    @pytest.mark.asyncio
    async def test_two_sectors_on_different_plots_get_different_weather_scopes(self):
        access = AsyncMock()
        summary = AsyncMock(return_value={"recent_observations": [], "forecast": []})
        seen = []

        with patch("app.ai.tools.get_weather_summary", summary):
            for sector_id, plot_id in (("sec-a", "plot-a"), ("sec-b", "plot-b")):
                access.sector_in_farm.return_value = SimpleNamespace(id=sector_id, plot_id=plot_id)
                await execute_tool(
                    "get_weather",
                    {},
                    access=access,
                    db=AsyncMock(),
                    scope=ToolScope(farm_id="farm-1", sector_id=sector_id),
                )
                seen.append(summary.await_args.kwargs["plot_id"])

        assert seen == ["plot-a", "plot-b"]

    @pytest.mark.asyncio
    async def test_farm_wide_weather_is_labelled_representative(self):
        access = AsyncMock()
        summary = AsyncMock(return_value={"recent_observations": [], "forecast": []})

        with patch("app.ai.tools.get_weather_summary", summary):
            out = await execute_tool(
                "get_weather",
                {},
                access=access,
                db=AsyncMock(),
                scope=ToolScope(farm_id="farm-1", sector_id=None),
            )

        assert summary.await_args.kwargs["plot_id"] is None
        assert out["scope"]["level"] == "farm"
        # A single station must not be presented as describing every plot.
        assert "representativ" in out["scope"]["note"].lower()

    @pytest.mark.asyncio
    async def test_weather_reports_observation_timestamps(self):
        access = AsyncMock()
        access.sector_in_farm.return_value = SimpleNamespace(id="s", plot_id="p")
        payload = {
            "recent_observations": [{"timestamp": "2026-09-09T06:00:00+00:00", "et0_mm": 4.1}],
            "forecast": [{"date": "2026-09-10", "rainfall_mm": 0.0}],
        }
        with patch("app.ai.tools.get_weather_summary", AsyncMock(return_value=payload)):
            out = await execute_tool(
                "get_weather",
                {},
                access=access,
                db=AsyncMock(),
                scope=ToolScope(farm_id="f", sector_id="s"),
            )
        assert out["latest_observation_at"] == "2026-09-09T06:00:00+00:00"


class TestFieldObservationTool:
    def test_tool_is_registered(self):
        assert "get_field_observations" in _tool_names()

    @pytest.mark.asyncio
    async def test_returns_active_notes_with_provenance(self):
        access = AsyncMock()
        now = datetime.now(UTC)
        rows = [
            SimpleNamespace(
                id="obs-1",
                observation_type="field_check",
                text="Gotejadores entupidos na linha 4.",
                structured_value={"visual_soil_condition": "dry"},
                observed_at=now - timedelta(hours=5),
                expires_at=now + timedelta(days=5),
                is_verified=False,
            )
        ]
        with patch("app.ai.tools.get_active_field_observations", AsyncMock(return_value=rows)):
            out = await execute_tool(
                "get_field_observations",
                {},
                access=access,
                db=AsyncMock(),
                scope=ToolScope(farm_id="f", sector_id="s"),
            )

        note = out["field_observations"][0]
        assert note["text"] == "Gotejadores entupidos na linha 4."
        assert note["verified"] is False
        assert note["source"] == "user_field_observation"
        assert note["observed_at"].startswith(str(now.year))
        assert note["expires_at"]

    @pytest.mark.asyncio
    async def test_access_is_checked_before_reading_notes(self):
        access = AsyncMock()
        access.sector_in_farm.side_effect = HTTPException(status_code=404)
        out = await execute_tool(
            "get_field_observations",
            {"sector_id": "foreign"},
            access=access,
            db=AsyncMock(),
            scope=ToolScope(farm_id="f", sector_id=None),
        )
        assert out == {"error": "not_found_or_forbidden"}

    @pytest.mark.asyncio
    async def test_expired_notes_are_not_returned(self):
        """The DB helper filters by expiry; the tool must not widen it."""
        access = AsyncMock()
        query = AsyncMock(return_value=[])
        with patch("app.ai.tools.get_active_field_observations", query):
            out = await execute_tool(
                "get_field_observations",
                {},
                access=access,
                db=AsyncMock(),
                scope=ToolScope(farm_id="f", sector_id="s"),
            )
        assert out["field_observations"] == []
        assert query.await_args.kwargs.get("active_only", True) is True


class TestContextReuse:
    @pytest.mark.asyncio
    async def test_independent_block_reads_share_one_canonical_context(self):
        """Rebuilding the ten-block context per tool call is the A1.6 gap."""
        from app.ai.tools import ToolSession

        context = SimpleNamespace(
            to_dict=lambda: {
                "outcomes": {"rows": []},
                "calibration": {"soil_bounds": {}},
                "engine_decision": {"history": []},
                "irrigation_execution": {},
                "crop_state": {"stress_projection": None},
                "water_balance": {},
            }
        )
        builder = AsyncMock(return_value=context)
        session = ToolSession()
        access = AsyncMock()

        with patch("app.ai.tools.AssistantContextBuilder.build_sector_ai_context", builder):
            for name in ("get_outcomes", "get_calibration_status", "get_stress_projection"):
                await execute_tool(
                    name,
                    {},
                    access=access,
                    db=AsyncMock(),
                    scope=ToolScope(farm_id="f", sector_id="sec-1"),
                    session=session,
                )

        assert builder.await_count == 1
