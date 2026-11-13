import asyncio
import importlib
import json
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("mode", ["mock", "real"])
def test_web_shows_scenario_dates_only_in_mock_mode(mode):
    from fastapi.testclient import TestClient
    from app.simulation.web import create_app
    with TestClient(create_app(mode), base_url='http://127.0.0.1') as client:
        context = client.get('/api/config').json()['simulation_context']
        if mode == 'mock':
            assert '2026-11-08' in context
            assert '2026-11-10' in context
            assert '2026-11-11' in context
        else:
            assert context is None
        assert 'simulation-context' in client.get('/').text


def test_browser_reply_is_correlated_and_selection_validated(tmp_path):
    web = importlib.import_module('app.simulation.web')
    async def run():
        trip = web.BrowserRun('Request', 'happy_path', 'mock', tmp_path)
        item = SimpleNamespace(id='question-one', value=dict(question='Choose', kind='selection', options=['luis'], proposal=None))
        task = asyncio.create_task(trip.resolve_interrupt('agent_b', item))
        await asyncio.sleep(0)
        assert [event['type'] for event in trip.snapshot()['events']] == ['human.interrupt']
        assert trip.snapshot()['events'][0]['data']['question'] == 'Choose'
        assert not task.done()
        with pytest.raises(ValueError):
            trip.reply('agent_b', 'old-question', '1')
        with pytest.raises(ValueError):
            trip.reply('agent_b', 'question-one', '2')
        trip.reply('agent_b', 'question-one', '1')
        reply = await task
        assert reply['text'] == '1'
        from app.agents.context import AgentContext
        context = AgentContext('agent_b', trip.rid, trip.settings, trip.case, trip.trace)
        state = {'observations': {'guides': {'tool': 'check_guide_availability',
            'query': {}, 'result': {'status': 'success', 'data': [{'guide_id': 'luis'}]}}}}
        with context.activate(state):
            context.process_human_reply(item.value, reply)
        assert [event['type'] for event in trip.snapshot()['events']] == ['human.interrupt', 'human.response']
        with pytest.raises(ValueError):
            trip.reply('agent_b', 'question-one', '1')
    asyncio.run(run())


def test_browser_flow_uses_existing_booking_checks_and_saves_trajectory(tmp_path):
    web = importlib.import_module('app.simulation.web')
    from test_integration import ScriptedModel
    async def run():
        trip = web.BrowserRun('Request', 'happy_path', 'mock', tmp_path, model=ScriptedModel())
        trip.case['expected_date'] = '2099-01-01'
        task = asyncio.create_task(trip.execute())
        async with asyncio.timeout(15):
            while not task.done():
                for actor, prompt in list(trip.pending.items()):
                    answer = '2' if prompt['kind'] == 'selection' else 'approve' if prompt['kind'] == 'approval' else 'I have boots, water and a first aid kit.'
                    trip.reply(actor, prompt['id'], answer)
                await asyncio.sleep(0.01)
            await task
        assert trip.status == 'confirmed'
        assert trip.path.is_file()
        assert trip.path.parent == tmp_path
        report = json.loads(trip.path.read_text(encoding='utf-8'))['result']
        assert report['status'] == 'confirmed'
        assert report['trip_result']['date'] == '2026-11-10'
        assert report['error'] is None
        assert not {'passed', 'checks', 'metrics'} & report.keys()
        assert any('Reservation' in message['text'] for message in trip.messages['agent_a'])
    asyncio.run(run())


def test_browser_default_output_is_flat_manual_folder(monkeypatch, tmp_path):
    web = importlib.import_module('app.simulation.web')
    from fastapi.testclient import TestClient
    from test_integration import ScriptedModel
    monkeypatch.setattr('app.simulation.runner.load_model', ScriptedModel)
    monkeypatch.chdir(tmp_path)
    with TestClient(web.create_app('mock'), base_url='http://127.0.0.1') as client:
        assert client.post('/api/session', json={'message': 'Hello'}).status_code == 200
        assert client.post('/api/session/' + client.get('/api/current').json()['id'] + '/cancel').status_code == 200
    paths = list((tmp_path / 'trajectories').rglob('*.json'))
    assert len(paths) == 1
    assert paths[0].parent == tmp_path / 'trajectories/manual'


def test_web_rejects_cross_origin_and_stale_session(tmp_path):
    web = importlib.import_module('app.simulation.web')
    from fastapi.testclient import TestClient
    app = web.create_app('mock', output=tmp_path)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.get('/').status_code == 200
        assert client.post('/api/session', json={'message': 'hi'}, headers={'Origin': 'http://evil.example'}).status_code == 403
        assert client.get('/api/session/missing').status_code == 404
        assert client.get('/', headers={'Host': 'evil.example'}).status_code == 400


def test_cancelling_waiting_browser_trip_saves_trajectory(tmp_path):
    web = importlib.import_module('app.simulation.web')
    from test_integration import ScriptedModel
    async def run():
        trip = web.BrowserRun('Request', 'happy_path', 'mock', tmp_path, model=ScriptedModel())
        task = asyncio.create_task(trip.execute())
        async with asyncio.timeout(10):
            while not trip.pending:
                await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert trip.status == 'cancelled' and trip.path.is_file()
        report = json.loads(trip.path.read_text(encoding='utf-8'))['result']
        assert report['status'] == 'cancelled'
        assert report['trip_result'] is None
        assert report['error']
        assert not {'passed', 'checks', 'metrics'} & report.keys()
        assert not trip.pending
    asyncio.run(run())


@pytest.mark.parametrize('technical_error', [False, True])
def test_browser_export_distinguishes_controlled_failure_from_runtime_error(tmp_path, technical_error):
    from app.models.contracts import TripResult
    web = importlib.import_module('app.simulation.web')
    async def run():
        trip = web.BrowserRun('Request', 'happy_path', 'mock', tmp_path)
        async def finish():
            if technical_error:
                raise RuntimeError('Test runtime error')
            trip.result = TripResult(request_id=trip.rid, status='failed', failure_reason='No safe date')
        trip.run = finish
        await trip.execute()
        report = json.loads(trip.path.read_text(encoding='utf-8'))['result']
        assert set(report) == {'status', 'trip_result', 'error'}
        assert report['status'] == ('error' if technical_error else 'failed')
        if technical_error:
            assert report['trip_result'] is None and report['error']
        else:
            assert report['trip_result']['failure_reason'] == 'No safe date'
            assert report['error'] is None
    asyncio.run(run())


def test_live_trajectory_snapshot_is_ordered_redacted_and_detached(tmp_path):
    web = importlib.import_module('app.simulation.web')
    trip = web.BrowserRun('Request', 'happy_path', 'mock', tmp_path)
    trip.trace.emit('tool.called', 'agent_a', {'tool': 'weather', 'api_key': 'private-key'})
    first = trip.snapshot()
    assert first['events'][0]['seq'] == 1
    assert first['events'][0]['data']['api_key'] == '[redacted]'
    assert not first['trajectory'] and first['status'] == 'running'
    trip.trace.emit('tool.completed', 'agent_a', {'tool': 'weather'})
    assert len(first['events']) == 1
    assert [event['seq'] for event in trip.snapshot()['events']] == [1, 2]


def test_browser_guide_labels_preserve_ids_and_selection(tmp_path):
    web = importlib.import_module('app.simulation.web')
    async def check():
        trip = web.BrowserRun('Request', 'happy_path', 'mock', tmp_path)
        trip.trace.emit('tool.completed', 'agent_b', dict(tool='check_guide_availability', output=dict(status='success',data=[{'guide_id':'guide-42','name':'María de la Cruz'},{'guide_id':'luis','name':'Luis'}])))
        item = SimpleNamespace(id='choose', value=dict(question='Choose',kind='selection',options=['luis','guide-42','unknown'],proposal=None))
        task = asyncio.create_task(trip.resolve_interrupt('agent_b',item))
        await asyncio.sleep(0)
        prompt = trip.snapshot()['pending']['agent_b']
        assert prompt['option_labels'] == ['Luis','María de la Cruz','unknown']
        assert prompt['options'] == ['luis','guide-42','unknown']
        trip.reply('agent_b','choose','2')
        reply = await task
        assert reply['text'] == '2'
        interrupt = next(e for e in trip.trace.events if e['type'] == 'human.interrupt')
        assert reply['interrupt_event_id'] == interrupt['event_id']
    asyncio.run(check())
