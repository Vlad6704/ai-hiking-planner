"""Finalization validates only the planner's checkpointed received evidence."""

import asyncio

import pytest

from app.agents.context import AgentContext
from app.humans.simulator import HumanSimulator
from app.models.contracts import BookingRequest, TripSubmission
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario
from app.tools.operator import confirmation


def make_run():
    return SimulationRunner(load_scenario('happy_path'), Settings(), 42)


def planner_context(run):
    return AgentContext('agent_a', run.rid, run.settings, run.case, run.trace,
                        human=run.humans['agent_a'], deliver_final=run._deliver_result)


def receipt():
    return confirmation(BookingRequest(request_id='d748573e-e51f-40d0-9ddf-26227a2aed1b',
        idempotency_key='booking', approval_ref='approved', route_id='PR-PNPE-2:long',
        date='2026-11-10', guide_id='luis', equipment={}))


def test_uncertain_booking_prevents_terminal_delivery():
    run = make_run()
    context = planner_context(run)
    with context.activate({'request_id': run.rid, 'booking_progress': {'status': 'pending'}}):
        with pytest.raises(RuntimeError, match='booking_outcome_uncertain'):
            context.make_result(TripSubmission(status='failed', failure_reason='No booking was made'))
    assert not run.humans['agent_a'].messages


def test_two_submissions_deliver_once():
    class YieldingSink(HumanSimulator):
        async def deliver(self, actor, mid, text):
            await asyncio.sleep(0)
            await super().deliver(actor, mid, text)

    async def check():
        run = make_run()
        run.humans['agent_a'] = YieldingSink({})
        context = planner_context(run)
        with context.activate({'request_id': run.rid}):
            result = context.make_result(TripSubmission(status='failed', failure_reason='No safe forecast'))
        responses = await asyncio.gather(run._deliver_result(result), run._deliver_result(result),
                                         return_exceptions=True)
        assert sum(isinstance(response, ValueError) for response in responses) == 1
        assert len(run.humans['agent_a'].messages) == 1
        assert sum(event['type'] == 'human.message_delivered' for event in run.trace.events) == 1

    asyncio.run(check())


def test_invalid_fallback_and_no_reservation():
    from test_integration import ScriptedModel

    async def check():
        case = load_scenario('happy_path')
        case['weather_failure'] = True
        case['fallback'] = False
        run = SimulationRunner(case, Settings(), 42, ScriptedModel())
        await run.run()
        state = await run.drivers['agent_a'].get_state()
        weather = [record for record in state.get('observations', {}).values()
                   if record['tool'] == 'get_weather_forecast']
        assert weather and all(record['result']['status'] == 'error' for record in weather)
        assert not state.get('received_outcome', {}).get('reservation')
        assert not any(event['type'] == 'tool.completed' and
                       event['data'].get('tool') == 'create_tour_reservation'
                       for event in run.trace.events)

    asyncio.run(check())


@pytest.mark.parametrize('via_tool', [True, False])
@pytest.mark.parametrize('confirmed', [True, False])
def test_finalization_uses_received_outcome_without_reading_operator(via_tool, confirmed):
    from app.agents.tools import bind_tools

    async def check():
        run = make_run()
        booking = receipt()
        state = {'request_id': run.rid}
        if confirmed:
            state['received_outcome'] = {'status': 'confirmed',
                                        'reservation': booking.model_dump(mode='json')}
            submission = TripSubmission(status='confirmed', route_id=booking.route_id,
                date=booking.date, guide_id=booking.guide_id)
        else:
            submission = TripSubmission(status='failed', failure_reason='No safe route')
        context = planner_context(run)
        # A's received outcome establishes completion independently of B's
        # Python task still unwinding after it sent that outcome.
        run.active.add('agent_b')
        with context.activate(state):
            if via_tool:
                tool = next(tool for tool in bind_tools('agent_a', context)
                            if tool.name == 'submit_trip_result')
                assert await tool.ainvoke({'result': submission.model_dump(mode='json')}) == 'Delivered'
                saved = context.state['result']
                assert saved['reservation_id'] == (booking.reservation_id if confirmed else None)
            else:
                result = context.make_result(submission)
                await run._deliver_result(result)
        assert len(run.humans['agent_a'].messages) == 1
        if confirmed:
            assert booking.reservation_id in next(iter(run.humans['agent_a'].messages.values()))

    asyncio.run(check())
