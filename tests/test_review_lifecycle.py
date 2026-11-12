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
    from app.agents.context import AgentContext
    context = AgentContext('agent_b', str(uuid4()), Settings(), load_scenario('happy_path'), TraceRecorder({}))
    state = dict(selected_guide='luis', approval={'reference':'old','proposal':{'guide_id':'luis'}},
                 observations={'guides':dict(tool='check_guide_availability', query={},
                     result=dict(status='success',data=[{'guide_id':'luis'},{'guide_id':'ines'}]))})
    with context.activate(state) as working:
        context.process_human_reply(dict(kind='selection', options=['luis','ines']),
                                    dict(text='2',interaction_id='selection'))
        assert working['selected_guide'] == 'ines'
        assert working['approval'] is None


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
        asyncio.run(deliver_final(result, "We couldn't complete your request. Please try again later.", BrokenSink({}), trace))
    assert not any(e["type"] == "simulation.completed" for e in trace.events)
