import asyncio
from uuid import uuid4

import pytest

from app.humans.simulator import HumanSimulator
from app.models.contracts import TripResult
from app.observability.trace import TraceRecorder
from app.simulation.runner import deliver_final


def test_customer_receives_final_result():
    result = TripResult(
        request_id=uuid4(), status="failed", failure_reason="Weather unavailable"
    )
    trace = TraceRecorder({})
    human = HumanSimulator({})
    asyncio.run(deliver_final(result, "We couldn't complete your request. Please try again later.", human, trace))
    delivery, completed = trace.events[-2:]
    assert completed["caused_by"] == delivery["event_id"]
    assert delivery["data"]["message_id"] in human.messages


def test_reject_invalid_completion():
    result = TripResult(
        request_id=uuid4(), status="failed", failure_reason="Weather unavailable"
    )
    with pytest.raises(ValueError):
        asyncio.run(
            deliver_final(result, "Confirmed", HumanSimulator({}), TraceRecorder({}))
        )
