"""Selected operational evidence and a compact view for the receiving model."""

from copy import deepcopy
import json

from app.models.messages import PlanningFact


ROUTE_FIELDS = ('route_id', 'name', 'difficulty', 'distance_km', 'duration_hours',
                'elevation_gain_m', 'elevation_loss_m', 'constraints')


def selected_planning_facts(state, terms):
    """Project original observations without exposing the catalog to a peer."""
    route_id, date = terms['route_id'], str(terms['date'])
    selected = {}
    for identity, record in state.get('observations', {}).items():
        tool, result = record['tool'], record['result']
        if result['status'] == 'error':
            continue
        query, data = record['query'], result['data']
        scope = route_id
        if tool in ('search_hiking_routes', 'get_route_details'):
            rows = data if tool == 'search_hiking_routes' else [data]
            row = next((row for row in rows if row['route_id'] == route_id), None)
            if row is None:
                continue
            compact = {key: deepcopy(row[key]) for key in ROUTE_FIELDS if key in row}
            data = [compact] if tool == 'search_hiking_routes' else compact
            category = 'route'
        elif tool == 'get_weather_forecast':
            days = [day for day in data['days'] if str(day['date']) == date]
            if not days:
                continue
            data = {**{key: deepcopy(data[key]) for key in ('location', 'issued_at', 'provider')},
                    'days': [deepcopy(days[-1])]}
            query = {'location': data['location'], 'date': date}
            scope, category = f'{route_id}:{date}', 'weather'
        elif tool == 'get_hiking_equipment':
            if query['route']['route_id'] != route_id or str(query['weather']['date']) != date:
                continue
            data = {key: deepcopy(data[key]) for key in ('required', 'recommended', 'missing')}
            data['reasons'] = {}
            scope, category = f'{route_id}:{date}', 'equipment'
        else:
            continue
        compact_result = {key: deepcopy(result[key]) for key in ('status', 'source', 'mode')}
        compact_result['data'] = data
        fact = PlanningFact(id=f'{identity}:{scope}', tool=tool,
                            query=deepcopy(query), result=compact_result)
        # Route details take precedence over a search summary for this route.
        if category == 'route' and tool == 'search_hiking_routes' and category in selected:
            if selected[category].tool == 'get_route_details':
                continue
        selected[category] = fact

    sent = [fact for record in state.get('outbox', {}).values()
            for fact in (record.get('envelope', record).get('payload') or {}).get('planning_facts', [])]
    def evidence(fact):
        return {key: value for key, value in fact.items() if key != 'id'}
    return [fact for fact in selected.values()
            if not any(evidence(fact.model_dump(mode='json')) == evidence(prior) for prior in sent)]


def peer_model_content(envelope):
    """Keep transport/audit wrappers out of the model's conversation history."""
    payload = deepcopy(envelope.get('payload'))
    if payload:
        facts = payload.pop('planning_facts', [])
        if facts:
            payload['facts'] = [dict(tool=fact['tool'], data=fact['result']['data']) for fact in facts]
        observations = payload.pop('observations', [])
        if observations:
            payload['availability'] = [dict(tool=fact['tool'], query=fact['query'],
                                          result=fact['result']) for fact in observations]
    content = f"Peer message type: {envelope['type']}. {envelope['content']}"
    if payload:
        content += '\nStructured facts: ' + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return content
