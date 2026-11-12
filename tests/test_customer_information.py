import asyncio
from types import SimpleNamespace

import pytest

from app.agents.tools import bind_tools
from app.simulation.web import BrowserRun


def test_information_waits_for_customer_without_peer_messages(tmp_path):
    async def run():
        trip = BrowserRun('List routes', 'happy_path', 'mock', tmp_path)
        item = SimpleNamespace(id='info-one', value=dict(question='Available routes: Lakes, Cares.', kind='information', options=[], proposal=None))
        task = asyncio.create_task(trip.resolve_interrupt('agent_a', item))
        await asyncio.sleep(0)
        assert not task.done() and trip.result is None
        assert trip.trace.events[0]['type'] == 'human.information'
        assert trip.messages['agent_a'][-1]['text'].startswith('Available routes')
        trip.reply('agent_a', 'info-one', 'Tell me about Lakes')
        assert (await task)['text'] == 'Tell me about Lakes'
        assert trip.bus.count == 0
    asyncio.run(run())


def test_acknowledgement_is_local_and_orphan_response_not_a_request(tmp_path):
    from private_agent_helpers import make_context, scoped
    async def run():
        context = make_context()
        state = {}
        tools = {tool.name: tool for tool in bind_tools('agent_a', context)}
        with scoped(context, state):
            await tools['acknowledge_message'].ainvoke({})
            assert not context.state.get('outbox')
            reply = await tools['send_to_agent'].ainvoke(dict(content='Acknowledged', kind='response'))
            assert 'error' in reply
            await tools['send_to_agent'].ainvoke(dict(content='An update'))
            assert not context.has_pending_request
    asyncio.run(run())


def test_actual_graph_lists_routes_and_resumes_customer_dialogue_without_operator(tmp_path):
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class ListingModel(BaseChatModel):
        @property
        def _llm_type(self):
            return 'listing-regression'
        def bind_tools(self, tools, **kwargs):
            return self
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            count = sum(isinstance(message, ToolMessage) for message in messages)
            name, args = ('search_hiking_routes', {}) if count == 0 else ('send_to_customer', {'content': 'Available routes: Lakes.' if count == 1 else 'Lakes is an easy route.'})
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[dict(name=name, args=args, id=f'call-{count}')]))])

    async def run():
        trip = BrowserRun('Just list routes', 'happy_path', 'mock', tmp_path, model=ListingModel())
        task = asyncio.create_task(trip.execute())
        try:
            async with asyncio.timeout(10):
                while not trip.pending:
                    await asyncio.sleep(0.01)
                assert trip.pending['agent_a']['kind'] == 'information'
                question = trip.pending['agent_a']['id']
                trip.reply('agent_a', question, 'Tell me more about Lakes')
                while not trip.pending or trip.pending['agent_a']['id'] == question:
                    await asyncio.sleep(0.01)
            assert trip.messages['agent_a'][-1]['text'] == 'Lakes is an easy route.'
            assert trip.result is None and trip.bus.count == 0 and trip.error is None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_local_acknowledgement_ends_worker_turn_without_reminder_or_echo(tmp_path):
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver
    from app.agents.factory import build_agent
    from private_agent_helpers import make_context
    from test_integration import ScriptedModel
    class AckModel(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[
                dict(name='acknowledge_message', args={}, id='local-ack')]))])
    async def run():
        context = make_context('agent_b')
        graph = build_agent('agent_b', bind_tools('agent_b', context), AckModel(), InMemorySaver(), agent_context=context)
        config = {'configurable': {'thread_id': 'ack'}}
        await graph.ainvoke({'messages': [('user', 'No action required')], 'request_id': context.rid}, config)
        result = await graph.ainvoke(None, config)
        assert not result.get('outbox')
        assert sum(e['type'] == 'agent.acknowledged' for e in context.trace.events) == 1
        assert not (await graph.aget_state(config)).next
    asyncio.run(run())
