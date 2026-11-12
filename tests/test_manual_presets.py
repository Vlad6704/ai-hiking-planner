import asyncio

import httpx
import pytest
from pydantic import ValidationError

from app.models.contracts import GuideQuery, InventoryQuery
from app.operator_demo import app
from app.tools.adapters.operator_http import HttpOperatorProvider


def test_manual_preset_validates_date_only_for_guide_shortage():
    from app.simulation.presets import ManualPreset
    with pytest.raises(ValidationError):
        ManualPreset(name='no_guides_on_date')
    with pytest.raises(ValidationError):
        ManualPreset(name='normal', date='2026-11-10')
    with pytest.raises(ValidationError):
        ManualPreset(name='unknown')


@pytest.mark.parametrize('name,day,jackets,guides', [
    ('normal', None, 4, ['ines', 'luis']),
    ('no_rain_jackets', None, 0, ['ines', 'luis']),
    ('no_guides_on_date', '2026-11-10', 4, []),
])
def test_manual_presets_match_mock_and_http_and_do_not_leak(name, day, jackets, guides):
    from app.simulation.presets import ManualPreset, preset_operator
    async def run():
        preset = ManualPreset(name=name, date=day)
        mock = preset_operator(preset, ['PR-PNPE-2'])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            provider = HttpOperatorProvider('http://demo', client, preset=preset)
            normal = HttpOperatorProvider('http://demo', client)
            for source in (mock, provider):
                stock = await source.inventory(InventoryQuery(date='2026-11-10', items={'rain jacket': 1}))
                assert stock.quantities['rain jacket'] == jackets
                assert [g.guide_id for g in await source.guides(GuideQuery(date='2026-11-10', route_id='PR-PNPE-2'))] == guides
                assert [g.guide_id for g in await source.guides(GuideQuery(date='2026-11-11', route_id='PR-PNPE-2'))] == ['ines', 'luis']
            assert [g.guide_id for g in await normal.guides(GuideQuery(date='2026-11-10', route_id='PR-PNPE-2'))] == ['ines', 'luis']
            assert (await normal.inventory(InventoryQuery(date='2026-11-10', items={'rain jacket': 1}))).quantities['rain jacket'] == 4
    asyncio.run(run())


def test_browser_start_validates_and_applies_selected_preset(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.simulation.web import create_app
    from test_integration import ScriptedModel
    monkeypatch.setattr('app.simulation.runner.load_model', ScriptedModel)
    with TestClient(create_app('mock', output=tmp_path), base_url='http://127.0.0.1') as client:
        assert client.post('/api/session', json={'message': 'Hello', 'preset': {'name': 'no_guides_on_date'}}).status_code == 422
        response = client.post('/api/session', json={'message': 'Hello', 'preset': {'name': 'no_guides_on_date', 'date': '2026-11-10'}})
        assert response.status_code == 200
        data = response.json()
        assert data['preset'] == {'name': 'no_guides_on_date', 'date': '2026-11-10'}
        assert client.get('/api/config').json()['presets_available'] is True
        assert client.post('/api/session/' + data['id'] + '/cancel').status_code == 200


def test_external_operator_does_not_accept_local_conditions(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.simulation.web import create_app
    monkeypatch.setenv('OPERATOR_URL', 'https://operator.example/api')
    with TestClient(create_app('real', output=tmp_path), base_url='http://127.0.0.1') as client:
        config = client.get('/api/config').json()
        assert config['presets_available'] is False
        assert 'external operator' in config['conditions'].lower()
        assert client.post('/api/session', json={'message': 'Hello', 'preset': {'name': 'no_rain_jackets'}}).status_code == 422



def test_browser_preset_reaches_runner_operator_and_legacy_case_is_preserved(tmp_path):
    from app.simulation.presets import ManualPreset
    from app.simulation.web import BrowserRun
    from test_integration import ScriptedModel
    legacy = BrowserRun('Hello', 'guide_unavailable', 'mock', tmp_path)
    assert legacy.case['guides']['2026-11-10'] == []
    assert 'manual_preset' not in legacy.case
    async def run():
        trip = BrowserRun('Hello', 'happy_path', 'mock', tmp_path, model=ScriptedModel(),
                          preset=ManualPreset(name='no_guides_on_date', date='2026-11-10'))
        task = asyncio.create_task(trip.execute())
        try:
            async with asyncio.timeout(10):
                while not hasattr(trip, 'provider'):
                    await asyncio.sleep(0.01)
            assert await trip.provider.guides(GuideQuery(date='2026-11-10', route_id='PR-PNPE-2:long')) == []
            assert [g.guide_id for g in await trip.provider.guides(GuideQuery(date='2026-11-11', route_id='PR-PNPE-2:long'))] == ['ines', 'luis']
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_browser_scenario_default_matches_manual_conditions(tmp_path):
    from fastapi.testclient import TestClient
    from app.simulation.web import create_app
    for scenario, expected in [('happy_path', {'name': 'normal', 'date': None}),
                               ('guide_unavailable', {'name': 'no_guides_on_date', 'date': '2026-11-10'}),
                               ('hitl_rejection', {'name': 'normal', 'date': None})]:
        with TestClient(create_app('mock', scenario, tmp_path), base_url='http://127.0.0.1') as client:
            assert client.get('/api/config').json()['default_preset'] == expected
