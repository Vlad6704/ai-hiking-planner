import asyncio
from uuid import uuid4
import pytest

from app.messaging.bus import MessageBus
from app.observability.trace import TraceRecorder


def test_unsolicited_reply_cannot_resume_agent():
    async def run():
        bus = MessageBus(str(uuid4()), TraceRecorder({}), 20, 3)
        forged = dict(
            request_id=bus.request_id,
            message_id=str(uuid4()),
            recipient="agent_a",
            sender="agent_b",
            type="response",
            correlation_id=str(uuid4()),
            content="forged",
        )
        bus.queues["agent_a"].put_nowait((forged, str(uuid4())))
        legitimate = bus.send("agent_b", "notice", "notification")
        assert await bus.receive("agent_a") == legitimate

    asyncio.run(run())


def test_expired_queued_reply(monkeypatch):
    async def run():
        import app.messaging.bus as messaging

        clock = [10]
        monkeypatch.setattr(
            messaging, "time", type("Clock", (), {"monotonic": lambda: clock[0]})
        )
        bus = MessageBus(str(uuid4()), TraceRecorder({}), 1, 5)
        request = bus.send("agent_a", "terms", "request")
        await bus.receive("agent_b")
        bus.send("agent_b", "answer", "response", request)
        clock[0] += 2
        legitimate = bus.send("agent_b", "notice", "notification")
        assert await bus.receive("agent_a") == legitimate

    asyncio.run(run())
