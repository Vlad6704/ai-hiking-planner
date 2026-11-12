import asyncio
from contextlib import contextmanager

from fastapi.testclient import TestClient


def test_modes_switch_between_sessions_without_restarting(monkeypatch, tmp_path):
    from app.simulation import web
    calls = []

    @contextmanager
    def backend(mode):
        calls.append(('start', mode))
        try:
            yield True
        finally:
            calls.append(('stop', mode))

    async def wait(self):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.status = 'cancelled'
            raise

    monkeypatch.setattr(web, 'operator_backend', backend)
    monkeypatch.setattr(web.BrowserRun, 'execute', wait)
    with TestClient(web.create_app('mock', output=tmp_path), base_url='http://127.0.0.1') as client:
        mock = client.get('/api/config?mode=mock').json()
        assert mock['mode'] == 'mock' and mock['simulation_context']
        assert calls == []
        real = client.get('/api/config?mode=real').json()
        assert real['mode'] == 'real' and real['simulation_context'] is None
        assert real['failure_tools'] == [] and real['presets_available']
        assert 'demonstration' in real['data_sources']
        assert calls == [('start', 'real')]
        trip = client.post('/api/session', json={'message': 'Hello', 'mode': 'real'}).json()
        assert trip['mode'] == 'real'
        assert client.get('/api/current').json()['mode'] == 'real'
        assert client.get('/api/config').json()['mode'] == 'real'
        assert client.post('/api/session', json={'message': 'Other', 'mode': 'mock'}).status_code == 409
        assert client.get('/api/config?mode=mock').status_code == 409
        assert client.post('/api/session/' + trip['id'] + '/cancel').status_code == 200
        mock_trip = client.post('/api/session', json={'message': 'Hello again', 'mode': 'mock'}).json()
        assert mock_trip['mode'] == 'mock'
        assert client.get('/api/config').json()['failure_tools']
        client.post('/api/session/' + mock_trip['id'] + '/cancel')
    assert calls == [('start', 'real'), ('stop', 'real')]


def test_real_mode_rejects_mock_settings_and_invalid_mode(monkeypatch, tmp_path):
    from app.simulation import web
    monkeypatch.setenv('OPERATOR_URL', 'https://operator.example/api')
    with TestClient(web.create_app('mock', output=tmp_path), base_url='http://127.0.0.1') as client:
        assert client.post('/api/session', json={'message': 'Hi', 'mode': 'other'}).status_code == 422
        assert client.get('/api/config?mode=other').status_code == 422
        assert client.post('/api/session', json={'message': 'Hi', 'mode': 'real',
            'failure_injection': {'tool': 'check_equipment_inventory', 'timeout_probability': 1}}).status_code == 422
        assert client.post('/api/session', json={'message': 'Hi', 'mode': 'real',
            'preset': {'name': 'no_rain_jackets'}}).status_code == 422
        assert client.get('/api/config?mode=real').json()['presets_available'] is False


def test_backend_failure_does_not_fall_back_to_simulation(monkeypatch):
    from app.simulation import web

    @contextmanager
    def broken(mode):
        raise RuntimeError('demo unavailable')
        yield

    monkeypatch.setattr(web, 'operator_backend', broken)
    with TestClient(web.create_app('mock'), base_url='http://127.0.0.1') as client:
        assert client.get('/api/config?mode=real').status_code == 503
        assert client.get('/api/config?mode=mock').json()['mode'] == 'mock'
        assert client.get('/api/current').json() is None
