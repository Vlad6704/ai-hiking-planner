import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.context import AgentContext
from app.agents.driver import AgentDriver
from app.agents.state import PlannerState
from app.messaging.bus import MessageBus
from app.models.contracts import TripSubmission
from app.observability.trace import TraceRecorder
from app.simulation.config import Settings
from app.simulation.scenario import load_scenario


def test_confirmation_is_unavailable_until_received_and_survives_driver_recreation():
    async def check():
        request_id = str(uuid4())
        trace = TraceRecorder({})
        bus = MessageBus(request_id, trace, 90, 20)
        saver = InMemorySaver()

        def driver():
            builder = StateGraph(PlannerState)
            builder.add_node('work', lambda state: {})
            builder.add_edge(START, 'work')
            builder.add_edge('work', END)
            graph = builder.compile(checkpointer=saver)
            return AgentDriver(graph, 'agent_a', {'configurable': {'thread_id': request_id}}, bus)

        current = driver()
        await current.graph.ainvoke({'request_id': request_id, 'messages': []}, current.config)
        terms = dict(route_id='route', date='2026-11-10', guide_id='guide', equipment={})
        receipt = dict(**terms, reservation_id='TR-ABCDEFGH', status='confirmed', created_at='2026-11-12T12:00:00Z')
        sender_state = {'booking': receipt}
        submission = TripSubmission(status='confirmed', route_id='route', date='2026-11-10', guide_id='guide')

        def context():
            return AgentContext('agent_a', request_id, Settings(), load_scenario('happy_path'), trace)

        planner = context()
        with planner.activate(await current.get_state()):
            with pytest.raises(ValueError, match='No verified reservation'):
                planner.make_result(submission)
        message = dict(message_id=str(uuid4()), request_id=request_id, sender='agent_b', recipient='agent_a',
                       type='notification', content='Confirmed', timestamp='2026-11-12T12:00:00Z',
                       payload=dict(kind='reservation_outcome', status='confirmed',
                                    reservation=deepcopy(sender_state['booking']), approval_ref='approved'))
        await current.receive(message)
        sender_state['booking']['reservation_id'] = 'TR-23456789'
        restored = driver()
        planner = context()
        with planner.activate(await restored.get_state()):
            assert planner.make_result(submission).reservation_id == 'TR-ABCDEFGH'
        assert not await restored.receive(message)

    asyncio.run(check())


def test_role_context_has_no_business_state_outside_checkpoint_scope():
    context = AgentContext('agent_a', str(uuid4()), Settings(), load_scenario('happy_path'), TraceRecorder({}))
    assert context.provider is None
    with pytest.raises(RuntimeError, match='active tool scope'):
        _ = context.state


def test_runner_uses_injected_private_checkpointers_for_complete_business_state():
    from test_integration import ScriptedModel
    from app.simulation.runner import SimulationRunner

    async def check():
        savers = {'agent_a': InMemorySaver(), 'agent_b': InMemorySaver()}
        run = SimulationRunner(load_scenario('happy_path'), Settings(), 42,
                               ScriptedModel(), checkpointers=savers)
        await run.run()
        assert run.error is None
        assert run.result.status == 'confirmed'
        assert not any(hasattr(run, field) for field in ('operator', 'observed', 'approvals', 'selected', 'substitution'))
        a = await run.drivers['agent_a'].get_state()
        b = await run.drivers['agent_b'].get_state()
        assert a['received_outcome']['reservation'] == b['booking']
        assert a['requirements']['reply_references']
        assert a['observations'] and b['observations']
        assert 'approval' not in a
        assert b['approval']['reference']
        assert 'requirements' not in b
        assert a['pending_interaction'] is None
        assert b['pending_interaction'] is None
        for actor, saver in savers.items():
            assert await saver.aget_tuple(run.drivers[actor].config) is not None

    asyncio.run(check())
