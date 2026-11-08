import asyncio

from app.models.contracts import RouteQuery
from app.observability.trace import TraceRecorder
from app.simulation.config import Settings
from app.tools.execution import execute
from app.tools.planning import details, search


def test_route_and_gear_rules():
    q = RouteQuery(location="Picos de Europa", difficulty="easy", max_hours=4)
    assert search(q)[0].route_id == "PR-PNPE-2"
    assert details("PR-PNPE-2").elevation_gain_m == 50
    assert search(q.model_copy(update={"max_km": 2})) == []


def test_retry_schedule():
    calls = []

    async def call():
        calls.append(1)
        raise TimeoutError()

    trace = TraceRecorder({})
    result = asyncio.run(
        execute(
            "weather",
            {},
            call,
            Settings(),
            trace,
            "agent_a",
            fallback=lambda: {"ok": True},
        )
    )
    assert result["status"] == "degraded" and len(calls) == 3
