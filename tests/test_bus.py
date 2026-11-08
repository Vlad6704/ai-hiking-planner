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
