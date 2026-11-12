import asyncio
from copy import deepcopy
import sys

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize('probability', [-0.1, 1.1, float('nan'), float('inf')])
def test_failure_override_rejects_invalid_probability(probability):
    from app.simulation.failures import FailureInjection
    with pytest.raises(ValidationError):
        FailureInjection(tool='get_weather_forecast', timeout_probability=probability)


def test_override_isolated_and_replaces_selected_rule():
    from app.simulation.failures import FailureInjection, apply_failure_override
    case = {'weather_failure': True, 'failure_injection': {'get_weather_forecast': {'failures': ['timeout']}, 'check_equipment_inventory': {'latency_ms': 5}}}
    before = deepcopy(case)
    result = apply_failure_override(case, FailureInjection(tool='get_weather_forecast', timeout_probability=0))
    assert case == before
    assert result['weather_failure'] is False
    assert result['failure_injection']['get_weather_forecast'] == {'timeout_probability': 0}
    assert result['failure_injection']['check_equipment_inventory'] == {'latency_ms': 5}


@pytest.mark.parametrize('args', [
    ['--failure-tool', 'get_weather_forecast'],
    ['--timeout-probability', '0.5'],
    ['--failure-tool', 'unknown', '--timeout-probability', '0.5'],
    ['--failure-tool', 'get_weather_forecast', '--timeout-probability', 'nan'],
    ['--mode', 'real', '--failure-tool', 'get_weather_forecast', '--timeout-probability', '0'],
])
def test_cli_rejects_invalid_failure_options(monkeypatch, args):
    from app.simulation import __main__ as cli
    monkeypatch.setattr(sys, 'argv', ['hiking', '--scenario', 'happy_path', *args])
    with pytest.raises(SystemExit) as error:
        asyncio.run(cli.main())
    assert error.value.code == 2


def test_browser_failure_settings_and_real_mode_rejection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.simulation.web import create_app, BrowserRun

    async def wait(self):
        await asyncio.Event().wait()

    monkeypatch.setattr(BrowserRun, 'execute', wait)
    override = {'tool': 'check_equipment_inventory', 'timeout_probability': 0.3}
    with TestClient(create_app('mock', output=tmp_path), base_url='http://127.0.0.1') as client:
        assert len(client.get('/api/config').json()['failure_tools']) == 7
        response = client.post('/api/session', json={'message': 'Hello', 'failure_injection': override, 'seed': 7})
        assert response.status_code == 200
        assert response.json()['seed'] == 7
        assert response.json()['failure_injection'] == override
        assert client.get('/api/current').json()['failure_injection'] == override
    # No lifespan needed for rejected inputs; avoid starting a demo backend.
    client = TestClient(create_app('real'), base_url='http://127.0.0.1')
    assert client.get('/api/config').json()['failure_tools'] == []
    assert client.post('/api/session', json={'message': 'Hello', 'failure_injection': {**override, 'timeout_probability': 0}}).status_code == 422
    assert client.post('/api/session', json={'message': 'Hello', 'failure_injection': {**override, 'tool': 'unknown'}}).status_code == 422


def test_seeded_per_attempt_failures_are_reproducible_and_isolated():
    from app.tools.adapters.mock import FailureSchedule

    async def sample():
        schedule = FailureSchedule({'tool': {'timeout_probability': 0.3}}, 1)
        outcomes = []
        for _ in range(5):
            try:
                await schedule.before('tool')
                outcomes.append('success')
            except TimeoutError:
                outcomes.append('timeout')
        return outcomes

    async def check():
        first, second = await asyncio.gather(sample(), sample())
        assert first == second == ['timeout', 'success', 'success', 'timeout', 'success']

    asyncio.run(check())


def test_graph_recovers_after_probabilistic_timeout():
    from app.simulation.failures import FailureInjection, apply_failure_override
    from app.simulation.runner import SimulationRunner
    from app.simulation.scenario import load_scenario
    from app.simulation.config import Settings
    from test_integration import ScriptedModel
    case = apply_failure_override(load_scenario('happy_path'), FailureInjection(tool='get_weather_forecast', timeout_probability=0.3))
    run = SimulationRunner(case, Settings(), 1, ScriptedModel())
    asyncio.run(run.run())
    assert run.result.status == 'confirmed'
    failures = [e for e in run.trace.events if e['type'] == 'tool.failed']
    assert len(failures) == 1
    assert run.trace.metadata['failure_injection'] == case['failure_injection']


def test_graph_exhausted_timeouts_can_finish_without_booking():
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from app.simulation.failures import FailureInjection, apply_failure_override
    from app.simulation.runner import SimulationRunner
    from app.simulation.scenario import load_scenario
    from app.simulation.config import Settings
    from test_integration import ScriptedModel

    class FailureModel(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            replies = [m for m in messages if isinstance(m, ToolMessage)]
            if not replies:
                name, args = 'get_weather_forecast', {'location': 'Picos de Europa', 'date': '2026-11-10'}
            else:
                assert 'error' in replies[-1].content
                name, args = 'submit_trip_result', {'result': {'status': 'failed', 'failure_reason': 'Weather unavailable after retries.'}}
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': str(len(replies))}]))])

    case = apply_failure_override(load_scenario('happy_path'), FailureInjection(tool='get_weather_forecast', timeout_probability=1))
    run = SimulationRunner(case, Settings(), 42, FailureModel())
    asyncio.run(run.run())
    assert run.result.status == 'failed'
    assert not any(e['type'] == 'tool.completed' and e['data'].get('tool') == 'create_tour_reservation' for e in run.trace.events)
    assert len([e for e in run.trace.events if e['type'] == 'tool.failed']) == 3
