import asyncio
from copy import deepcopy
import importlib
import json

import pytest

from app.agents.tools import bind_tools
from private_agent_helpers import make_context, scoped


def human_reply(text):
    return dict(text=text, interaction_id='interaction-one', interrupt_event_id='question-event',
                matched_intent=['manual'], match_score=1)


def invoke_human(context, state, monkeypatch, tool_name, args, text):
    tools_module = importlib.import_module('app.agents.tools')
    reply = human_reply(text)
    monkeypatch.setattr(tools_module, 'interrupt', lambda _: deepcopy(reply))
    tool = next(t for t in bind_tools(context.actor, context) if t.name == tool_name)
    with scoped(context, state):
        message = asyncio.run(tool.ainvoke(dict(name=tool_name, args=args, id='tool-one', type='tool_call')))
    assert message.tool_call_id == 'tool-one' and message.name == tool_name
    stored = state['interactions']['interaction-one']
    assert stored['matched_intent'] == ['manual'] and stored['match_score'] == 1
    assert stored['interrupt_event_id'] == 'question-event' and stored['response_event_id']
    assert context.trace.events[-1]['type'] == 'human.response'
    return message


@pytest.mark.parametrize('tool_name,args', [
    ('ask_human', {'question': 'What equipment do you have?'}),
    ('send_to_customer', {'content': 'Here are the lake routes.'}),
])
def test_customer_tools_return_only_text_but_retain_audit_state(monkeypatch, tool_name, args):
    context, state = make_context(), {}
    message = invoke_human(context, state, monkeypatch, tool_name, args, 'I have boots.')
    assert message.content == 'I have boots.'
    assert state['requirements']['reply_references']['interaction-one'] == state['interactions']['interaction-one']['response_event_id']


def test_guide_selection_returns_validated_guide_without_internal_ids(monkeypatch):
    context = make_context('agent_b')
    state = {'observations': {'guides': dict(tool='check_guide_availability', query={},
        result=dict(status='success', data=[dict(guide_id='ines'), dict(guide_id='luis')]))}}
    message = invoke_human(context, state, monkeypatch, 'ask_human',
                           dict(question='Select a guide', kind='selection', options=['ines', 'luis']), '2')
    assert json.loads(message.content) == {'text': '2', 'guide_id': 'luis'}
    assert state['selected_guide'] == 'luis'


@pytest.mark.parametrize('text,approved', [('Approved', True), ('Rejected. Offer a poncho instead.', False)])
def test_manager_approval_keeps_private_reference_and_returns_boolean(monkeypatch, text, approved):
    context = make_context('agent_b')
    proposal = dict(route_id='route', date='2026-11-10', equipment={}, guide_id='luis')
    state = dict(original_proposal={k: proposal[k] for k in ('route_id', 'date', 'equipment')}, selected_guide='luis')
    message = invoke_human(context, state, monkeypatch, 'ask_human',
                           dict(question='Approve?', kind='approval', proposal=proposal), text)
    assert json.loads(message.content) == dict(text=text, approved=approved)
    record = state['interactions']['interaction-one']
    assert bool(record['approval_ref']) is approved
    assert bool(state.get('approval')) is approved
    if not approved:
        assert state['rejections'] == [proposal]


def test_compact_customer_reply_still_supports_proposal_bound_consent(monkeypatch):
    context = make_context()
    proposal = dict(route_id='route', date='2026-11-11', equipment={}, guide_id='luis')
    state = dict(offer=dict(message_id='offer-one', proposal=proposal))
    message = invoke_human(context, state, monkeypatch, 'ask_human',
                           dict(question='Accept the alternative?', proposal=proposal), 'Yes, that works.')
    assert message.content == 'Yes, that works.'
    with scoped(context, state):
        identity = context.reply_with_customer_decision('accepted')['queued']
    payload = state['outbox'][identity]['envelope']['payload']
    assert payload['offer_message_id'] == 'offer-one'
    assert payload['response_event_id'] == state['interactions']['interaction-one']['response_event_id']
    assert payload['reply_text'] == 'Yes, that works.' and payload['proposal'] == proposal


def test_approval_validation_failure_keeps_its_existing_error_result():
    context, state = make_context('agent_b'), {}
    tool = next(t for t in bind_tools('agent_b', context) if t.name == 'ask_human')
    with scoped(context, state):
        message = asyncio.run(tool.ainvoke(dict(name='ask_human', args=dict(
            question='Approve?', kind='approval'), id='invalid-approval', type='tool_call')))
    assert json.loads(message.content) == {'error': 'Present exact terms first'}
    assert not state.get('interactions') and not context.trace.events


def test_actual_graph_resume_checkpoints_full_reply_but_model_sees_only_text():
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from app.agents.factory import build_agent
    from test_integration import ScriptedModel

    seen = []

    class QuestionModel(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if isinstance(messages[-1], ToolMessage):
                seen.append(messages[-1].content)
                response = AIMessage(content='Finished')
            else:
                response = AIMessage(content='', tool_calls=[dict(
                    name='ask_human', args={'question': 'What equipment do you own?'}, id='question-call')])
            return ChatResult(generations=[ChatGeneration(message=response)])

    async def check():
        context = make_context()
        graph = build_agent('agent_a', bind_tools('agent_a', context), QuestionModel(),
                            InMemorySaver(), agent_context=context)
        config = {'configurable': {'thread_id': context.rid + ':agent_a'}}
        await graph.ainvoke({'request_id': context.rid, 'messages': [('user', 'Plan a hike')]}, config)
        interrupted = await graph.ainvoke(None, config)
        item = interrupted['__interrupt__'][0]
        reply = human_reply('I have boots.')
        reply['interaction_id'] = item.id
        await graph.ainvoke(Command(resume={item.id: reply}), config)
        saved = (await graph.aget_state(config)).values
        record = saved['interactions'][item.id]
        assert record['text'] == 'I have boots.' and record['response_event_id']
        assert record['matched_intent'] == ['manual'] and record['match_score'] == 1
        assert saved['pending_interaction'] is None
        assert saved['messages'][-1].content == 'I have boots.'
        assert saved['messages'][-1].tool_call_id == 'question-call'
        await graph.ainvoke(None, config)
        assert seen == ['I have boots.']

    asyncio.run(check())
