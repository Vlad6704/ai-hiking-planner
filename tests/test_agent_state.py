from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError


def envelope(**changes):
    return dict(message_id=str(uuid4()), request_id=str(uuid4()), sender='agent_a',
                recipient='agent_b', correlation_id=None, type='request', content='Plan',
                timestamp='2026-11-12T12:00:00Z', payload=dict(kind='trip_request',
                terms=dict(route_id='route', date='2026-11-10', equipment={})), **changes)


def test_structured_message_roundtrip_and_role_validation():
    from app.models.messages import PeerEnvelope
    data = envelope()
    message = PeerEnvelope.model_validate(data)
    assert PeerEnvelope.model_validate_json(message.model_dump_json()) == message
    data['sender'], data['recipient'] = 'agent_b', 'agent_a'
    with pytest.raises(ValidationError):
        PeerEnvelope.model_validate(data)


def test_missing_terms_and_invalid_reservation_are_rejected():
    from app.models.messages import PeerEnvelope
    data = envelope()
    data['payload']['terms'].pop('date')
    with pytest.raises(ValidationError):
        PeerEnvelope.model_validate(data)
    data = envelope()
    data.update(sender='agent_b', recipient='agent_a')
    data['payload'] = dict(kind='reservation_outcome', status='confirmed', reservation=None)
    with pytest.raises(ValidationError):
        PeerEnvelope.model_validate(data)


def test_record_merge_is_idempotent_isolated_and_conflict_checked():
    from app.agents.state import merge_records
    original = {'a': {'value': [1]}}
    merged = merge_records(original, {'b': {'value': [2]}})
    assert merge_records(merged, deepcopy(original)) == merged
    merged['a']['value'].append(3)
    assert original['a']['value'] == [1]
    with pytest.raises(ValueError, match='conflicting_record'):
        merge_records(original, {'a': {'value': [9]}})


def test_availability_message_carries_validated_operational_facts():
    from app.models.messages import AvailabilityResultPayload
    from private_agent_helpers import make_context, scoped
    context = make_context('agent_b')
    state = {'observations': {'guides': dict(tool='check_guide_availability',
        query=dict(route_id='route', date='2026-11-10'),
        result=dict(status='success', data=[], source='mock', mode='mock'))}}
    with scoped(context, state):
        identity = context.stage_message('No guides available', 'notification')['queued']
    payload = state['outbox'][identity]['payload']
    assert payload['observations'][0]['query']['date'] == '2026-11-10'
    assert payload['observations'][0]['result']['data'] == []
    payload['observations'][0]['query']['date'] = 'invalid'
    with pytest.raises(ValidationError):
        AvailabilityResultPayload.model_validate(payload)


def test_parallel_agent_facts_survive_checkpoint_roundtrip():
    from app.agents.state import PlannerState
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    workflow = StateGraph(PlannerState)
    workflow.add_node('weather', lambda state: {'observations': {'weather': {'tool': 'weather'}}})
    workflow.add_node('routes', lambda state: {'observations': {'routes': {'tool': 'routes'}}})
    workflow.add_edge(START, 'weather')
    workflow.add_edge(START, 'routes')
    workflow.add_edge('weather', END)
    workflow.add_edge('routes', END)
    saver = InMemorySaver()
    config = {'configurable': {'thread_id': 'private-a'}}
    graph = workflow.compile(checkpointer=saver)
    graph.invoke({'request_id': 'trip', 'messages': []}, config)
    restored = workflow.compile(checkpointer=saver)
    assert set(restored.get_state(config).values['observations']) == {'weather', 'routes'}
    assert not restored.get_state({'configurable': {'thread_id': 'private-b'}}).values


def test_planning_facts_validate_provider_contracts():
    from app.models.messages import PlanningFact
    with pytest.raises(ValidationError):
        PlanningFact(id='weather', tool='get_weather_forecast',
            query={'location': 'Picos de Europa', 'date': '2026-11-10'},
            result={'status': 'success', 'source': 'weather', 'mode': 'mock', 'data': {'days': []}})
