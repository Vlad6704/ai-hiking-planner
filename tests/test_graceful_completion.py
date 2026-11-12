import asyncio

import pytest

from app.models.contracts import TripResult
from app.simulation.config import Settings
from app.simulation.outcome import trip_message
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario
from app.tools.execution import execute
from app.observability.trace import TraceRecorder


async def attach_planner(run):
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import InMemorySaver
    from app.agents.state import PlannerState
    from app.agents.driver import AgentDriver
    workflow = StateGraph(PlannerState)
    workflow.add_node('work', lambda state: {})
    workflow.add_edge(START, 'work')
    workflow.add_edge('work', END)
    graph = workflow.compile(checkpointer=InMemorySaver())
    config = {'configurable': {'thread_id': run.rid + ':agent_a'}}
    await graph.ainvoke({'request_id': run.rid, 'messages': []}, config)
    driver = AgentDriver(graph, 'agent_a', config, run.bus)
    run.drivers['agent_a'] = driver
    return driver


def test_failed_message_hides_internal_reason():
    result = TripResult(request_id='d748573e-e51f-40d0-9ddf-26227a2aed1b', status='failed', failure_reason='inventory timeout')
    assert trip_message(result) == "We couldn't complete your request. Please try again later."
    assert result.failure_reason == 'inventory timeout'


def test_queued_message_cannot_prevent_notification_at_work_limit():
    from app.models.messages import PeerEnvelope

    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(steps=5), 42)
        driver = await attach_planner(run)
        await driver.update({'booking_progress': {'status': 'pending'}})
        run.bus.send_envelope(PeerEnvelope(
            message_id='late-message', request_id=run.rid, sender='agent_b', recipient='agent_a',
            type='notification', content='Still processing', timestamp='2026-11-12T12:00:00Z',
            payload={'kind': 'availability_result', 'reason': 'pending'}))
        while len(run.trace.events) < 4:
            run.trace.emit('work', 'agent_a', {})
        await run.notify_runtime_failure('step_limit')
        assert len(run.humans['agent_a'].messages) == 1
        assert run.trace.events[-1]['data']['delivered'] is True
        assert run.result is None

    asyncio.run(check())


def test_retry_error_marks_exhaustion():
    async def check():
        async def fail():
            raise TimeoutError()
        result = await execute('inventory', {}, fail, Settings(attempts=1), TraceRecorder({}), 'agent_b')
        assert result['error']['attempts_exhausted'] is True
    asyncio.run(check())


@pytest.mark.parametrize('booking_state', ['confirmed', 'uncertain', 'uncertain_outcome'])
def test_runtime_notice_preserves_booking_status(booking_state):
    from app.tools.operator import confirmation
    from app.models.contracts import BookingRequest
    from app.models.messages import PeerEnvelope
    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(), 42)
        booking = confirmation(BookingRequest(request_id=run.rid, idempotency_key='key',
            approval_ref='approved', route_id='route', date='2026-11-10', guide_id='luis', equipment={}))
        await attach_planner(run)
        terms = booking.model_dump(mode='json', include={'route_id', 'date', 'guide_id', 'equipment'})
        payload = (dict(kind='reservation_outcome', status='confirmed',
                        reservation=booking.model_dump(mode='json'), proposal=terms, approval_ref='approved')
                   if booking_state == 'confirmed' else
                   dict(kind='reservation_progress', status='pending', proposal=terms, idempotency_key='key'))
        envelope = PeerEnvelope(message_id='booking-message', request_id=run.rid,
            sender='agent_b', recipient='agent_a', type='notification',
            timestamp='2026-11-12T12:00:00Z', payload=payload)
        if booking_state == 'uncertain_outcome':
            from app.models.messages import ReservationOutcomePayload
            envelope = envelope.model_copy(update={
                'payload': ReservationOutcomePayload(status='uncertain', proposal=terms),
            })
        run.bus.send_envelope(envelope)
        await run.notify_runtime_failure('peer_timeout')
        message = next(iter(run.humans['agent_a'].messages.values()))
        if booking_state == 'confirmed':
            assert run.result.reservation_id == booking.reservation_id
            assert booking.reservation_id in message
        else:
            assert run.result is None
            assert 'booking status' in message
            assert 'not created' not in message
        assert run.trace.events[-1]['data']['delivered'] is True
    asyncio.run(check())


@pytest.mark.parametrize('wrapped', [False, True])
def test_pending_customer_decision_keeps_runtime_notice_unconfirmed(wrapped):
    from app.models.messages import PeerEnvelope

    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(), 42)
        driver = await attach_planner(run)
        envelope = PeerEnvelope(
            message_id='customer-decision', request_id=run.rid,
            sender='agent_a', recipient='agent_b', type='request',
            timestamp='2026-11-12T12:00:00Z', payload=dict(
                kind='customer_decision', offer_message_id='offer-one',
                proposal=dict(route_id='route', date='2026-11-10', guide_id='luis', equipment={}),
                decision='accepted', interaction_id='interaction-one',
                response_event_id='response-one', reply_text='Yes'))
        record = envelope.model_dump(mode='json')
        if wrapped:
            record = {'envelope': record, 'caused_by': None}
        await driver.update({'outbox': {envelope.message_id: record}})
        await driver.flush_outbox()
        await run.notify_runtime_failure('peer_timeout')
        assert run.result is None
        assert next(iter(run.humans['agent_a'].messages.values())) == (
            "We couldn't confirm your booking status. Please contact the operator before trying again.")
        assert run.trace.events[-1]['data']['delivered'] is True

    asyncio.run(check())


def test_safety_delivery_cannot_read_unreceived_operator_receipt():
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import InMemorySaver
    from app.agents.driver import AgentDriver
    from app.agents.state import OperatorState

    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(), 42)
        await attach_planner(run)
        workflow = StateGraph(OperatorState)
        workflow.add_node('work', lambda state: {})
        workflow.add_edge(START, 'work')
        workflow.add_edge('work', END)
        graph = workflow.compile(checkpointer=InMemorySaver())
        config = {'configurable': {'thread_id': run.rid + ':agent_b'}}
        await graph.ainvoke({'request_id': run.rid, 'messages': [], 'booking': {'reservation_id': 'TR-ABCDEFGH'}}, config)
        run.drivers['agent_b'] = AgentDriver(graph, 'agent_b', config, run.bus)
        await run.notify_runtime_failure('deadlock')
        assert run.result.status == 'failed'
        assert run.result.reservation_id is None
        assert 'TR-ABCDEFGH' not in next(iter(run.humans['agent_a'].messages.values()))

    asyncio.run(check())


def test_failed_runtime_notification_is_not_retried():
    class BrokenHuman:
        calls = 0
        async def deliver(self, *args):
            self.calls += 1
            raise OSError('socket failed')
    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(), 42)
        human = BrokenHuman()
        run.humans['agent_a'] = human
        await run.notify_runtime_failure('deadlock')
        await run.notify_runtime_failure('deadlock')
        assert human.calls == 1
        assert run.trace.events[-1]['data']['delivered'] is False
        assert run.trace.events[-1]['data']['delivery_error'] == 'socket failed'
        assert run.result is None
    asyncio.run(check())


def test_existing_final_delivery_is_not_duplicated():
    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(), 42)
        run.trace.emit('human.message_delivered', 'agent_a', dict(message_kind='final_result'))
        await run.notify_runtime_failure('late error')
        assert not run.humans['agent_a'].messages
        assert run.trace.events[-1]['data']['delivered'] is True
    asyncio.run(check())


def test_terminal_allowance_is_finite_and_does_not_allow_work():
    trace = TraceRecorder({}, max_steps=2)
    trace.emit('work', 'runner', {})
    trace.reserve_terminal_events()
    with pytest.raises(RuntimeError, match='step_limit'):
        trace.emit('work', 'runner', {})
    for _ in range(3):
        trace.emit('runtime.notification_started', 'runner', {})
    with pytest.raises(RuntimeError, match='step_limit'):
        trace.emit('runtime.notification_started', 'runner', {})


def test_browser_exposes_generic_error_but_retains_internal_cause(tmp_path):
    from app.simulation.web import BrowserRun
    async def check():
        run = BrowserRun('Hello', 'happy_path', 'mock', tmp_path)
        await run.notify_runtime_failure('verified_equipment_required')
        snapshot = run.snapshot()
        assert 'verified_equipment_required' not in snapshot['error']
        assert snapshot['error'] == "We couldn't complete your request. Please try again later."
        assert run.error == 'verified_equipment_required'
    asyncio.run(check())


def test_uncertain_booking_from_previous_final_attempt_is_not_retried():
    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(), 42)
        run.final_delivery_attempted = True
        await run.notify_runtime_failure('delivery_failed')
        assert not run.humans['agent_a'].messages
        assert run.trace.events[-1]['data']['delivered'] is False
    asyncio.run(check())


@pytest.mark.parametrize('stop', ['deadlock', 'timeout', 'step_limit'])
def test_run_entrypoint_notifies_after_worker_shutdown(stop):
    from test_integration import ScriptedModel
    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(timeout=0.1, steps=5), 42, ScriptedModel())
        async def worker(actor, graph):
            if stop == 'timeout':
                run.active.add(actor)
                await asyncio.Event().wait()
            elif stop == 'step_limit' and actor == 'agent_a':
                while True:
                    run.trace.emit('work', actor, {})
        run.worker = worker
        await run.run()
        assert run.error
        assert run.result.status == 'failed'
        assert len(run.humans['agent_a'].messages) == 1
        assert run.trace.events[-1]['type'] == 'simulation.failed'
        assert run.trace.events[-1]['data']['delivered'] is True
    asyncio.run(check())


@pytest.mark.parametrize('reason', ['deadlock', 'step_limit', 'peer_timeout'])
def test_runtime_stop_delivers_generic_notice_at_work_limit(reason):
    async def check():
        run = SimulationRunner(load_scenario('happy_path'), Settings(steps=5), 42)
        for _ in range(4):
            run.trace.emit('work', 'agent_a', {})
        await run.notify_runtime_failure(reason)
        assert len(run.humans['agent_a'].messages) == 1
        assert run.result.status == 'failed'
        assert run.result.failure_reason == reason
        assert run.trace.events[-1]['type'] == 'simulation.failed'
        assert run.trace.events[-1]['data']['delivered'] is True
        assert not any(e['type'] == 'simulation.completed' for e in run.trace.events)
        await run.notify_runtime_failure(reason)
        assert len(run.humans['agent_a'].messages) == 1
    asyncio.run(check())
