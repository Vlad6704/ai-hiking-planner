import asyncio
import json

import httpx
import pytest

from app.agents.tools import bind_tools
from private_agent_helpers import make_context, scoped
from app.route_catalog.seed import seed_store
from app.route_catalog.service import CatalogService
from app.route_catalog.store import CatalogStore, utcnow
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario


@pytest.mark.parametrize("keywords", [[], ["Enol"]])
@pytest.mark.parametrize("stale", [False, True])
def test_search_content_is_compact_but_trace_and_observed_keep_full_data(tmp_path, keywords, stale):
    async def run():
        trip = SimulationRunner(load_scenario("happy_path"), Settings(), 42)
        store = CatalogStore(tmp_path / "routes.sqlite3")
        seed_store(store, checked_at="2000-01-01T12:00:00+00:00" if stale else utcnow())
        async with httpx.AsyncClient() as client:
            context = make_context(catalog=CatalogService(store, client, refresh_enabled=False), client=client)
            state = {}
            tool = next(tool for tool in bind_tools("agent_a", context) if tool.name == "search_hiking_routes")
            with scoped(context, state):
                message = await tool.ainvoke(dict(
                    type="tool_call", id="route-search", name=tool.name,
                    args={"keywords": keywords},
                ))
            result = json.loads(message.content)
        assert result["status"] == ("degraded" if stale else "success")
        assert result["data"]
        allowed = {"route_id", "name", "difficulty", "distance_km", "duration_hours",
                   "elevation_gain_m", "elevation_loss_m", "snippet"}
        for row in result["data"]:
            assert set(row) <= allowed
            assert ("snippet" in row) == bool(keywords)
        assert "metadata" not in result
        full = next(iter(state["observations"].values()))["result"]["data"]
        assert full[0]["description"] and full[0]["source"] and full[0]["content_hash"]
        event = next(event for event in context.trace.events if event["type"] == "tool.completed")
        assert event["data"]["output"]["data"] == full
    asyncio.run(run())


def test_route_details_keep_full_sections_without_duplicate_aggregate(tmp_path):
    async def run():
        trip = SimulationRunner(load_scenario("happy_path"), Settings(), 42)
        store = CatalogStore(tmp_path / "routes.sqlite3")
        seed_store(store, checked_at=utcnow())
        async with httpx.AsyncClient() as client:
            context = make_context(catalog=CatalogService(store, client, refresh_enabled=False), client=client)
            state = {}
            tool = next(tool for tool in bind_tools("agent_a", context) if tool.name == "get_route_details")
            with scoped(context, state):
                result = await tool.ainvoke({"route_id": "PR-PNPE-2:long"})
            with scoped(context, state):
                error = await tool.ainvoke({"route_id": "invented"})
        row = result["data"]
        full = store.details("PR-PNPE-2:long")
        assert row["description"] == full["description"]
        assert row["instructions"] == full["instructions"]
        assert row["constraints"] == full["constraints"]
        assert row["source"] == full["source"]
        assert "full_text" not in row and "content_hash" not in row
        assert next(iter(state["observations"].values()))["result"]["data"] == full
        assert error["status"] == "error" and error["error"]["code"] == "route_not_found"
    asyncio.run(run())
