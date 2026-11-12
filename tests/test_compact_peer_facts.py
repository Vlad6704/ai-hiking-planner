import json
from copy import deepcopy

from private_agent_helpers import make_context, scoped


TERMS = dict(route_id='chosen', date='2026-11-10', equipment={'rain jacket': 1})


def observations():
    route = dict(route_id='chosen', name='Lake walk', difficulty='easy', duration_hours=3,
                 distance_km=5, description='LONG PRIVATE DESCRIPTION ' * 1000,
                 constraints=['Stay on marked paths'], source='catalog', full_text='RAW TEXT',
                 instructions='NAVIGATION', content_hash='HASH')
    day = dict(date=TERMS['date'], temperature_c=12, precipitation_probability=10,
               precipitation_mm=0, wind_kmh=8)
    def record(tool, query, data):
        return dict(tool=tool, query=query, result=dict(status='success', data=data,
                    source=tool, mode='mock', metadata={'audit': 'PRIVATE METADATA'}))
    return {
        'routes': record('search_hiking_routes', {'limit': 30},
                         [route, {**route, 'route_id': 'unrelated'}]),
        'weather': record('get_weather_forecast', {'location': 'Picos', 'date': TERMS['date']},
                          dict(location='Picos', days=[day, {**day, 'date': '2026-11-11'}],
                               issued_at='2026-11-08T12:00:00Z', provider='mock')),
    }


def test_request_contains_only_selected_compact_evidence():
    context = make_context()
    state = {'observations': observations()}
    original = deepcopy(state['observations'])
    with scoped(context, state):
        identity = context.stage_message('Check this trip', 'request', TERMS)['queued']
    payload = state['outbox'][identity]['payload']
    encoded = json.dumps(payload)
    assert 'unrelated' not in encoded
    for forbidden in ('description', 'full_text', 'instructions', 'content_hash', 'metadata'):
        assert forbidden not in encoded
    route_fact = next(f for f in payload['planning_facts'] if f['tool'] == 'search_hiking_routes')
    assert route_fact['result']['data'][0]['constraints'] == ['Stay on marked paths']
    weather = next(f for f in payload['planning_facts'] if f['tool'] == 'get_weather_forecast')
    assert [d['date'] for d in weather['result']['data']['days']] == [TERMS['date']]
    assert len(encoded) < 2500
    assert state['observations'] == original


def test_decision_does_not_resend_evidence_and_new_date_adds_only_new_evidence():
    context = make_context()
    state = {'observations': observations()}
    with scoped(context, state):
        context.stage_message('Check', 'request', TERMS)
    proposal = {**TERMS, 'guide_id': 'luis'}
    state.update(offer=dict(message_id='offer', proposal=proposal), customer_reply=dict(
        proposal=proposal, interaction_id='reply', response_event_id='event', text='Yes'))
    with scoped(context, state):
        identity = context.reply_with_customer_decision('accepted')['queued']
    assert state['outbox'][identity]['envelope']['payload']['planning_facts'] == []
    state['offer']['proposal'] = {**proposal, 'date': '2026-11-11'}
    state['offer']['message_id'] = 'new-offer'
    state['customer_reply']['proposal'] = state['offer']['proposal']
    with scoped(context, state):
        identity = context.reply_with_customer_decision('accepted')['queued']
    facts = state['outbox'][identity]['envelope']['payload']['planning_facts']
    assert {f['tool'] for f in facts} == {'get_weather_forecast'}
    weather = next(f for f in facts if f['tool'] == 'get_weather_forecast')
    assert weather['result']['data']['days'][0]['date'] == '2026-11-11'


def test_model_message_omits_evidence_wrappers():
    from app.agents.peer_facts import peer_model_content
    context = make_context()
    state = {'observations': observations()}
    with scoped(context, state):
        identity = context.stage_message('Check', 'request', TERMS)['queued']
    content = peer_model_content(state['outbox'][identity])
    assert 'chosen' in content and 'issued_at' in content
    assert 'query' not in content and 'metadata' not in content
    assert 'description' not in content and 'unrelated' not in content
    assert len(content) < 2000


def test_route_details_and_equipment_are_projected_without_explanation_text():
    from app.agents.peer_facts import selected_planning_facts
    state = {'observations': observations()}
    route = state['observations']['routes']['result']['data'][0]
    day = state['observations']['weather']['result']['data']['days'][0]
    state['observations']['details'] = dict(tool='get_route_details', query={'route_id': 'chosen'},
        result=dict(status='success', data=route, source='catalog', mode='mock'))
    state['observations']['gear'] = dict(tool='get_hiking_equipment', query=dict(
        route={key: route[key] for key in ('route_id', 'name', 'difficulty', 'duration_hours')},
        weather=day, duration_hours=3), result=dict(status='success', source='gear', mode='mock',
        data=dict(required=['rain jacket'], recommended=['poles'], missing=['rain jacket'],
                  reasons={'rain jacket': 'LONG EXPLANATION ' * 1000})))
    facts = selected_planning_facts(state, TERMS)
    assert {fact.tool for fact in facts} == {'get_route_details', 'get_weather_forecast', 'get_hiking_equipment'}
    encoded = json.dumps([fact.model_dump(mode='json') for fact in facts])
    assert 'LONG EXPLANATION' not in encoded and 'LONG PRIVATE DESCRIPTION' not in encoded
    assert 'Stay on marked paths' in encoded and 'rain jacket' in encoded


def test_full_catalog_rows_are_rejected_by_peer_contract():
    import pytest
    from pydantic import ValidationError
    from app.models.messages import PlanningFact
    record = observations()['routes']
    with pytest.raises(ValidationError):
        PlanningFact(id='raw', **record)
