import asyncio
import re
from uuid import uuid4

import pytest

from app.models.contracts import BookingRequest
from app.tools.operator import confirmation


def request():
    rid = uuid4()
    return BookingRequest(request_id=rid, idempotency_key=f"booking:{rid}",
                          approval_ref="approved", route_id="route", date="2026-11-10",
                          guide_id="guide", equipment={})


def test_short_codes_are_stable_and_distinct():
    first, second = request(), request()
    code = confirmation(first).reservation_id
    assert re.fullmatch(r"TR-[A-HJ-NP-Z2-9]{8}", code)
    assert confirmation(first).reservation_id == code
    assert confirmation(second).reservation_id != code


def test_code_generator_retries_collisions(monkeypatch):
    from app.tools.reservation_codes import ReservationCodes
    choices = iter("AAAAAAAA" + "AAAAAAAA" + "BBBBBBBB")
    monkeypatch.setattr("app.tools.reservation_codes.secrets.choice", lambda _: next(choices))
    issuer = ReservationCodes()
    assert issuer.issue("first") == "TR-AAAAAAAA"
    assert issuer.issue("first") == "TR-AAAAAAAA"
    assert issuer.issue("second") == "TR-BBBBBBBB"


@pytest.mark.parametrize("external_receipt", [False, True])
@pytest.mark.parametrize("wrong_field", [None, "route_id", "date", "guide_id", "equipment_items"])
def test_submission_tool_excludes_ids_and_runtime_builds_confirmation(external_receipt, wrong_field):
    from app.agents.tools import bind_tools
    from app.agents.context import AgentContext
    from app.models.contracts import TripResult
    from app.simulation.config import Settings
    from app.simulation.scenario import load_scenario
    from app.simulation.outcome import trip_message
    from app.observability.trace import TraceRecorder

    async def run():
        query = request()
        booking = confirmation(query)
        if external_receipt:
            booking.reservation_id = "TR-23456789"
        delivered = []
        async def deliver(result):
            delivered.append(result)
        context = AgentContext('agent_a', str(query.request_id), Settings(), load_scenario('happy_path'),
                               TraceRecorder({}), deliver_final=deliver)
        tool = next(t for t in bind_tools('agent_a', context) if t.name == 'submit_trip_result')
        properties = tool.args_schema.model_json_schema()['properties']
        assert 'final_message' not in properties
        result_schema = tool.args_schema.model_json_schema()['$defs']['TripSubmission']['properties']
        assert not {'request_id', 'reservation_id'} & result_schema.keys()
        business = dict(status='confirmed', route_id='route', date='2026-11-10', guide_id='guide', equipment_items=[])
        state = dict(received_outcome=dict(status='confirmed', reservation=booking.model_dump(mode='json')))
        with context.activate(state) as working:
            if wrong_field:
                wrong = {'route_id':'other-route', 'date':'2026-11-11', 'guide_id':'other-guide', 'equipment_items':['poncho']}
                rejected = await tool.ainvoke(dict(result={**business, wrong_field:wrong[wrong_field]}))
                assert rejected['error'] == 'Result disagrees with booking'
                assert not delivered
            assert await tool.ainvoke(dict(result=business)) == 'Delivered'
            result = TripResult.model_validate(working['result'])
        assert str(result.request_id) == str(query.request_id)
        assert result.reservation_id == booking.reservation_id
        assert f'Reservation {booking.reservation_id}.' in trip_message(delivered[0])
    asyncio.run(run())


def test_short_code_issuance_is_thread_safe():
    from concurrent.futures import ThreadPoolExecutor
    from app.tools.reservation_codes import ReservationCodes
    issuer = ReservationCodes()
    requests = [f"request-{i % 20}" for i in range(100)]
    with ThreadPoolExecutor(max_workers=8) as workers:
        codes = list(workers.map(issuer.issue, requests))
    assert len(set(codes)) == 20
    assert all(code == issuer.issue(key) for key, code in zip(requests, codes))


def test_http_demo_reuses_short_code_for_same_request():
    import httpx
    from app.operator_demo import app
    async def run():
        payload = request().model_dump(mode="json")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://demo") as client:
            first = await client.post("/reservations", json=payload)
            second = await client.post("/reservations", json=payload)
        assert first.status_code == second.status_code == 200
        assert re.fullmatch(r"TR-[A-HJ-NP-Z2-9]{8}", first.json()["reservation_id"])
        assert second.json()["reservation_id"] == first.json()["reservation_id"]
    asyncio.run(run())
