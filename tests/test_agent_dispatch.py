import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.state import OperatorState, PlannerState
from app.messaging.bus import MessageBus
from app.observability.trace import TraceRecorder


def setup(actor, saver=None, bus=None):
    graph = StateGraph(PlannerState if actor == 'agent_a' else OperatorState)
    graph.add_node('work', lambda state: {})
    graph.add_edge(START, 'work')
    graph.add_edge('work', END)
    compiled = graph.compile(checkpointer=saver or InMemorySaver())
    config = {'configurable': {'thread_id': 'trip:' + actor}}
    return compiled, config, bus or MessageBus('trip', TraceRecorder({}), 90, 20)


def message():
    return dict(message_id='message-one', request_id='trip', sender='agent_a',
        recipient='agent_b', correlation_id=None, type='request', content='Plan',
        timestamp='2026-11-12T12:00:00Z', payload=dict(kind='trip_request',
        terms=dict(route_id='route', date='2026-11-10', equipment={})))


def test_receive_checkpoints_once_and_restores_without_shadow_state():
    from app.agents.driver import AgentDriver

    async def run():
        saver = InMemorySaver()
        graph, config, bus = setup('agent_b', saver)
        await graph.ainvoke({'request_id': 'trip', 'messages': []}, config)
        driver = AgentDriver(graph, 'agent_b', config, bus)
        data = message()
        assert await driver.receive(data)
        data['payload']['terms']['equipment']['poncho'] = 3
        restored_graph, _, _ = setup('agent_b', saver, bus)
        restored = AgentDriver(restored_graph, 'agent_b', config, bus)
        state = await restored.get_state()
        assert state['original_proposal']['equipment'] == {}
        assert not await restored.receive(message())
        bad = message()
        bad['content'] = 'Changed under same ID'
        with pytest.raises(ValueError, match='conflict'):
            await restored.receive(bad)

    asyncio.run(run())


def test_dispatch_retry_keeps_identity_and_recipient_checkpoint_before_ack(monkeypatch):
    from app.agents.driver import AgentDriver

    async def run():
        graph, config, bus = setup('agent_a')
        data = message()
        await graph.ainvoke({'request_id': 'trip', 'messages': [], 'outbox': {'message-one': data}}, config)
        driver = AgentDriver(graph, 'agent_a', config, bus)
        update = graph.aupdate_state

        async def broken(*args, **kwargs):
            raise RuntimeError('checkpoint unavailable')

        monkeypatch.setattr(graph, 'aupdate_state', broken)
        with pytest.raises(RuntimeError):
            await driver.flush_outbox()
        assert bus.count == 1
        monkeypatch.setattr(graph, 'aupdate_state', update)
        await driver.flush_outbox()
        assert bus.count == 1
        assert (await driver.get_state())['dispatch_ack']['message-one'] == 'sent'
        receiver_graph, receiver_config, _ = setup('agent_b', bus=bus)
        await receiver_graph.ainvoke({'request_id': 'trip', 'messages': []}, receiver_config)
        receiver = AgentDriver(receiver_graph, 'agent_b', receiver_config, bus)
        queued = await bus.receive('agent_b')
        monkeypatch.setattr(receiver_graph, 'aupdate_state', broken)
        with pytest.raises(RuntimeError):
            await receiver.receive(queued)
        assert 'message-one' not in bus.seen
        monkeypatch.setattr(receiver_graph, 'aupdate_state', update)
        await receiver.receive(queued)
        assert 'message-one' in bus.seen

    asyncio.run(run())


def test_invalid_request_and_recipient_cannot_change_state():
    from app.agents.driver import AgentDriver

    async def run():
        graph, config, bus = setup('agent_b')
        await graph.ainvoke({'request_id': 'trip', 'messages': []}, config)
        driver = AgentDriver(graph, 'agent_b', config, bus)
        bad = message()
        bad['request_id'] = 'other'
        with pytest.raises(ValueError):
            await driver.receive(bad)
        assert not (await driver.get_state()).get('inbox')

    asyncio.run(run())


def test_dispatch_checkpoint_preserves_paused_tool_execution():
    from app.agents.driver import AgentDriver

    async def run():
        model_calls = []
        tools_called = []
        workflow = StateGraph(PlannerState)

        def model(state):
            model_calls.append(1)
            return {'outbox': {'message-one': message()}}

        def tools(state):
            tools_called.append(1)
            assert state['dispatch_ack']['message-one'] == 'sent'
            return {'observations': {'one': {'value': 'done'}}}

        workflow.add_node('model', model)
        workflow.add_node('tools', tools)
        workflow.add_edge(START, 'model')
        workflow.add_edge('model', 'tools')
        workflow.add_edge('tools', END)
        saver = InMemorySaver()
        graph = workflow.compile(checkpointer=saver, interrupt_before=['tools'])
        config = {'configurable': {'thread_id': 'paused-a'}}
        bus = MessageBus('trip', TraceRecorder({}), 90, 20)
        driver = AgentDriver(graph, 'agent_a', config, bus)
        await graph.ainvoke({'request_id': 'trip', 'messages': []}, config)
        assert (await graph.aget_state(config)).next == ('tools',)
        await driver.flush_outbox()
        assert (await graph.aget_state(config)).next == ('tools',)
        restored = workflow.compile(checkpointer=saver, interrupt_before=['tools'])
        await restored.ainvoke(None, config)
        assert model_calls == tools_called == [1]
        assert (await restored.aget_state(config)).values['observations']['one']['value'] == 'done'

    asyncio.run(run())


def test_langchain_middleware_pause_preserves_selected_tool_after_dispatch():
    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import tool
    from app.agents.driver import AgentDriver

    calls = []

    class Model(BaseChatModel):
        @property
        def _llm_type(self):
            return 'dispatch-test'

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            calls.append(1)
            response = AIMessage(content='Done') if messages[-1].type == 'tool' else AIMessage(
                content='', tool_calls=[{'name': 'read_value', 'args': {}, 'id': 'tool-one'}])
            return ChatResult(generations=[ChatGeneration(message=response)])

    class Stage(AgentMiddleware):
        def after_model(self, state, runtime):
            if state['messages'][-1].tool_calls:
                return {'outbox': {'message-one': message()}}
            return None

    @tool
    def read_value():
        """Return the test observation."""
        return 'observed'

    async def run():
        graph = create_agent(Model(), tools=[read_value], middleware=[Stage()],
            state_schema=PlannerState, checkpointer=InMemorySaver(), interrupt_before=['tools'])
        config = {'configurable': {'thread_id': 'langchain-a'}}
        bus = MessageBus('trip', TraceRecorder({}), 90, 20)
        driver = AgentDriver(graph, 'agent_a', config, bus)
        await graph.ainvoke({'request_id': 'trip', 'messages': [('user', 'Read')]}, config)
        assert (await graph.aget_state(config)).next == ('tools',)
        await driver.flush_outbox()
        assert (await graph.aget_state(config)).next == ('tools',)
        final = await graph.ainvoke(None, config)
        assert final['messages'][-1].content == 'Done'
        assert len(calls) == 2
        assert bus.count == 1

    asyncio.run(run())
