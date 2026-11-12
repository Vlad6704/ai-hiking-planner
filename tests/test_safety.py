import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.models.contracts import Forecast, WeatherQuery, BookingRequest
from app.simulation.scenario import load_scenario
from app.tools.planning import fallback_weather
from app.tools.operator import MockOperator
from app.observability.trace import TraceRecorder


@pytest.mark.parametrize("change", ["expired", "future", "place", "date", "provider"])
def test_fallback_eligibility(change):
    case = load_scenario("external_service_failure")
    forecast = Forecast(**case["weather"])
    now = datetime.fromisoformat(case["clock"])
    query = WeatherQuery(date="2026-11-10", location="Picos de Europa")
    assert fallback_weather(forecast, query, now, 6).days
    if change == "expired":
        now += timedelta(days=1)
    elif change == "future":
        now -= timedelta(days=1)
    elif change == "place":
        query.location = "Madrid"
    elif change == "date":
        query = WeatherQuery(date="2027-01-01", location=query.location)
    else:
        forecast.provider = "unknown"
    with pytest.raises(ValueError):
        fallback_weather(forecast, query, now, 6)


def test_uncertain_outcome():
    class LostResponse(MockOperator):
        async def reserve(self, request):
            first = not self.created
            reservation = await super().reserve(request)
            if first:
                raise TimeoutError()
            return reservation

    async def run():
        rid = str(uuid4())
        provider = LostResponse({"2026-11-10": ["luis"]}, {}, ["trail"])
        req = BookingRequest(route_id='trail', guide_id='luis', date='2026-11-10', equipment={},
            request_id=rid, idempotency_key=f'booking:{rid}', approval_ref='approved')
        with pytest.raises(TimeoutError):
            await provider.reserve(req)
        assert (await provider.reserve(req)).reservation_id == next(iter(provider.created.values())).reservation_id
        assert len(provider.created) == 1

    asyncio.run(run())


def test_hard_trace_limit():
    recorder = TraceRecorder({}, max_steps=3)
    recorder.emit("simulation.started", "runner", {})
    recorder.emit("tool.called", "agent_a", {})
    with pytest.raises(RuntimeError, match="step_limit"):
        recorder.emit("tool.called", "agent_a", {})
    recorder.emit("simulation.failed", "runner", {})
    assert len(recorder.events) == 3
