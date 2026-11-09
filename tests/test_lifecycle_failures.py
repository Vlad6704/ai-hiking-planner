import asyncio
from uuid import uuid4

import pytest

from app.humans.simulator import HumanSimulator
from app.models.contracts import TripResult
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario
from app.tools.operator import MockOperator, OperatorTools


def make_run():
    run = SimulationRunner(load_scenario("happy_path"), Settings(), 42)
    run.operator = OperatorTools(run.rid, run.approvals, MockOperator({}, {}, []))
    return run


def test_uncertain_booking_prevents_terminal_delivery():
    run = make_run()
    run.operator.terms = {"route_id": "PR-PNPE-2"}
    result = TripResult(
        request_id=run.rid, status="failed", failure_reason="No booking was made"
    )
    with pytest.raises(RuntimeError, match="booking_outcome_uncertain"):
        asyncio.run(run.finalize(result, result.failure_reason))
    assert not run.humans["agent_a"].messages


def test_two_submissions_deliver_once():
    class YieldingSink(HumanSimulator):
        async def deliver(self, actor, mid, text):
            await asyncio.sleep(0)
            await super().deliver(actor, mid, text)

    async def execute():
        run = make_run()
        run.humans["agent_a"] = YieldingSink({})
        result = TripResult(
            request_id=run.rid, status="failed", failure_reason="No safe forecast"
        )
        responses = await asyncio.gather(
            *(run.finalize(result, result.failure_reason) for _ in range(2)),
            return_exceptions=True,
        )
        assert sum(isinstance(r, ValueError) for r in responses) == 1
        assert len(run.humans["agent_a"].messages) == 1
        assert sum(e["type"] == "simulation.completed" for e in run.trace.events) == 1

    asyncio.run(execute())


def test_invalid_fallback_and_no_reservation():
    from app.agents.tools import bind_tools

    async def execute():
        run = make_run()
        run.case["weather_failure"] = True
        run.case["fallback"] = False
        planner = {t.name: t for t in bind_tools(run, "agent_a")}
        response = await planner["get_weather_forecast"].ainvoke(
            {"location": "Picos de Europa", "date": "2026-11-10"}
        )
        assert response["status"] == "error"
        assert len([e for e in run.trace.events if e["type"] == "tool.failed"]) == 3
        assert not run.operator.result

    asyncio.run(execute())
