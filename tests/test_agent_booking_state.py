import asyncio

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.context import AgentContext
from app.agents.driver import AgentDriver
from app.agents.state import OperatorState
from app.messaging.bus import MessageBus
from app.observability.trace import TraceRecorder
from app.simulation.config import Settings
from app.simulation.scenario import load_scenario
from app.tools.operator import confirmation


TERMS = dict(route_id='PR-PNPE-2:long', date='2026-11-10', guide_id='luis', equipment={})
RID = 'd748573e-e51f-40d0-9ddf-26227a2aed1b'


class Provider:
    idempotent_reservations = False

    def __init__(self, lose_reply=False):
        self.calls = 0
        self.lose_reply = lose_reply
        self.result = None

    async def reserve(self, query):
        self.calls += 1
        self.result = self.result or confirmation(query)
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError('response lost after booking')
        return self.result


async def setup(provider):
    case = load_scenario('happy_path')
    trace = TraceRecorder({})
    context = AgentContext('agent_b', RID, Settings(), case, trace, provider=provider)
    initial = dict(request_id=RID,
        messages=[AIMessage(content='', tool_calls=[dict(name='create_tour_reservation', args=TERMS, id='book-call')])],
        original_proposal={key: TERMS[key] for key in ('route_id', 'date', 'equipment')},
        selected_guide='luis', approval=dict(reference='approved', proposal=TERMS),
        observations={'guides': dict(tool='check_guide_availability', query=dict(date=TERMS['date'], route_id=TERMS['route_id']),
            result=dict(status='success', data=[dict(guide_id='luis', available=True, qualifications=[TERMS['route_id']])]))},
        planning_facts={
            'weather': dict(tool='get_weather_forecast', result=dict(status='success', data=case['weather'])),
            'routes': dict(tool='search_hiking_routes', result=dict(status='success', data=[dict(route_id=TERMS['route_id'])]))})
    with context.activate(initial) as working:
        working['_tool_call_id'] = 'book-call'
        attempt = context.prepare_booking(TERMS, 'book-call')
        working['dispatch_ack'] = {attempt['progress_message_id']: 'sent'}
        initial = {key: value for key, value in working.items() if not key.startswith('_')}
    workflow = StateGraph(OperatorState)
    workflow.add_node('model', lambda state: {})
    workflow.add_node('tools', lambda state: {})
    workflow.add_edge(START, 'model')
    workflow.add_edge('model', 'tools')
    workflow.add_edge('tools', END)
    graph = workflow.compile(checkpointer=InMemorySaver(), interrupt_before=['tools'])
    config = {'configurable': {'thread_id': RID + ':agent_b'}}
    await graph.ainvoke(initial, config)
    return context, AgentDriver(graph, 'agent_b', config, MessageBus(RID, trace, 90, 20))


def test_execution_claim_is_checkpointed_before_one_use_provider_permission():
    async def run():
        provider = Provider()
        context, driver = await setup(provider)
        assert await driver.claim_booking_execution(context)
        assert (await driver.get_state())['booking_attempt']['status'] == 'executing'
        assert not await driver.claim_booking_execution(context)
        with context.activate(await driver.get_state()) as working:
            working['_tool_call_id'] = 'book-call'
            result = await context.reserve(TERMS)
            assert result.reservation_id
        assert provider.calls == 1

    asyncio.run(run())


def test_crash_after_execution_checkpoint_does_not_repeat_nonidempotent_booking():
    async def run():
        provider = Provider()
        context, driver = await setup(provider)
        await driver.claim_booking_execution(context)
        restored = AgentContext('agent_b', RID, Settings(), load_scenario('happy_path'), driver.bus.trace, provider=provider)
        assert not await driver.claim_booking_execution(restored)
        with restored.activate(await driver.get_state()) as working:
            working['_tool_call_id'] = 'book-call'
            with pytest.raises(RuntimeError, match='booking_outcome_uncertain'):
                await restored.reserve(TERMS)
        assert provider.calls == 0

    asyncio.run(run())


@pytest.mark.parametrize('idempotent', [False, True])
def test_lost_reply_recovery_uses_only_provider_idempotency_contract(idempotent):
    async def run():
        provider = Provider(lose_reply=True)
        provider.idempotent_reservations = idempotent
        context, driver = await setup(provider)
        await driver.claim_booking_execution(context)
        # Simulate losing the entire tool result, including its state updates.
        checkpoint = await driver.get_state()
        with context.activate(checkpoint) as working:
            working['_tool_call_id'] = 'book-call'
            with pytest.raises(TimeoutError):
                await context.reserve(TERMS)
        restored = AgentContext('agent_b', RID, Settings(), load_scenario('happy_path'), driver.bus.trace, provider=provider)
        with restored.activate(checkpoint) as working:
            working['_tool_call_id'] = 'book-call'
            if idempotent:
                assert (await restored.reserve(TERMS)).reservation_id == provider.result.reservation_id
            else:
                with pytest.raises(RuntimeError, match='booking_outcome_uncertain'):
                    await restored.reserve(TERMS)
        assert provider.calls == (2 if idempotent else 1)

    asyncio.run(run())
