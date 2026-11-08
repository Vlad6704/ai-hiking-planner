import asyncio
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.models.contracts import Forecast, TripResult
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner, deliver_final
from app.simulation.scenario import load_scenario
from app.humans.simulator import HumanSimulator
from app.observability.trace import TraceRecorder


def test_new_selection_invalidates_old_approval():
    case = load_scenario("happy_path")
    run = SimulationRunner(case, Settings(), 42)
    run.observed["check_guide_availability"] = [
        [{"guide_id": "luis"}, {"guide_id": "ines"}]
    ]
    run.selected = "luis"
    proposal = {"guide_id": "luis"}
    ref = run.approvals.record(run.rid, proposal, "approved")
    run.human_reply(
        "agent_b",
        SimpleNamespace(
            id="i",
            value=dict(kind="selection", question="Choose", options=["luis", "ines"]),
        ),
    )
    with pytest.raises(ValueError, match="missing_approval"):
        run.approvals.require(run.rid, ref, proposal)


def test_fallback_requires_aware_timestamp():
    weather = load_scenario("happy_path")["weather"]
    weather["issued_at"] = "2026-11-08T12:00:00"
    with pytest.raises(ValidationError):
        Forecast(**weather)


def test_broken_sink_reports_delivery_failure():
    class BrokenSink(HumanSimulator):
        async def deliver(self, *args):
            raise ValueError("offline")

    result = TripResult(request_id=uuid4(), status="failed", failure_reason="weather")
    trace = TraceRecorder({})
    with pytest.raises(RuntimeError, match="delivery_failed"):
        asyncio.run(deliver_final(result, "weather", BrokenSink({}), trace))
    assert not any(e["type"] == "simulation.completed" for e in trace.events)
