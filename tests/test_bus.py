import asyncio

import pytest

from app.messaging.bus import MessageBus
from app.observability.trace import TraceRecorder


def test_request_reply():
    async def run():
        bus = MessageBus("r", TraceRecorder({}), 30, 20)
        request = bus.send("agent_a", "proposal", "request")
        assert await bus.receive("agent_b") == request
        reply = bus.send("agent_b", "confirmed", "response", request)
        assert (await bus.receive("agent_a"))["correlation_id"] == request["message_id"]
        with pytest.raises(ValueError):
            bus.send("agent_b", "duplicate", "response", request)
        assert not bus.pending

    asyncio.run(run())


def test_peer_send_in_request_turn_closes_request():
    from app.agents.tools import bind_tools
    from app.simulation.runner import SimulationRunner
    from app.simulation.scenario import load_scenario
    from app.simulation.config import Settings
    from app.tools.operator import MockOperator

    async def execute():
        run = SimulationRunner(load_scenario("happy_path"), Settings(), 42)
        run.provider = MockOperator({}, {}, [])
        req = run.bus.send("agent_a", "proposal", "request")
        run.incoming["agent_b"] = await run.bus.receive("agent_b")
        send = next(t for t in bind_tools(run, "agent_b") if t.name == "send_to_agent")
        await send.ainvoke({"content": "operator update", "kind": "notification"})
        reply = await run.bus.receive("agent_a")
        assert reply["correlation_id"] == req["message_id"] and not run.bus.pending

    asyncio.run(execute())
