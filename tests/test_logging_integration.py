import asyncio
import json
import logging
import os
import subprocess
import sys

import httpx

from app.models.contracts import WeatherQuery
from app.observability.trace import TraceRecorder
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario
from app.tools.execution import execute
from test_date_context import DateContextModel
from test_manual_services import available_url
from test_runtime_logging import records, runtime


def test_runner_records_log_path_and_resets_correlation(runtime, tmp_path):
    path = runtime.configure_logging('customer', tmp_path)
    ids = []
    for _ in range(2):
        run = SimulationRunner(load_scenario('happy_path'), Settings(), 42, DateContextModel(finish=True))
        ids.append(run.trace.metadata['run_id'])
        asyncio.run(run.run())
        assert run.trace.metadata['runtime_log_path'] == str(path)
    logging.getLogger('app.test').info('outside')
    rows = records(path)
    assert [row['run_id'] for row in rows if row['event'] == 'simulation.started'] == ids
    assert rows[-1]['run_id'] is None


def test_failed_tool_has_operation_attempt_and_exception(runtime, tmp_path):
    path = runtime.configure_logging('customer', tmp_path)
    async def fail():
        raise ValueError('typed failure')
    async def run():
        with runtime.log_context(run_id='run', request_id='request'):
            result = await execute('get_weather_forecast', {}, fail, Settings(), TraceRecorder({}), 'agent_a')
            assert result['status'] == 'error'
    asyncio.run(run())
    row = next(row for row in records(path) if row['event'] == 'tool.failed')
    assert row['run_id'] == 'run' and row['actor'] == 'agent_a'
    assert row['operation_id'] and row['attempt'] == 1
    assert row['exception']['type'] == 'ValueError'


def test_http_hooks_record_destinations_without_body_or_query(runtime, tmp_path):
    from app.observability.http_logging import attach_http_logging
    path = runtime.configure_logging('test', tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'private': 'response-body'}))) as client:
            attach_http_logging(client)
            attach_http_logging(client)
            await client.post('https://example.test/path?token=query-secret', json={'private': 'request-body'})
    asyncio.run(run())
    rows = records(path)
    assert [row['event'] for row in rows] == ['http.request', 'http.response']
    assert rows[0]['fields']['url'] == 'https://example.test/path'
    assert rows[1]['fields']['status'] == 200 and rows[1]['fields']['duration_ms'] >= 0
    assert all(secret not in path.read_text(encoding='utf-8') for secret in ('query-secret', 'request-body', 'response-body'))


def test_http_records_keep_the_tool_operation_context(runtime, tmp_path):
    from app.observability.http_logging import attach_http_logging
    path = runtime.configure_logging('test', tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
            attach_http_logging(client)
            async def call():
                await client.get('https://example.test/forecast')
                raise ValueError('after request')
            await execute('get_weather_forecast', {}, call, Settings(), TraceRecorder({}), 'agent_a')
    asyncio.run(run())
    rows = records(path)
    failed = next(row for row in rows if row['event'] == 'tool.failed')
    request = next(row for row in rows if row['event'] == 'http.request')
    assert request['actor'] == 'agent_a'
    assert request['operation_id'] == failed['operation_id']


def test_invalid_http_response_values_do_not_enter_logs(runtime, tmp_path):
    from app.models.contracts import GuideQuery
    from app.tools.adapters.operator_http import HttpOperatorProvider
    path = runtime.configure_logging('test', tmp_path)
    async def run():
        bad = [{'guide_id': {'private': 'PRIVATE_CUSTOMER_RESPONSE_BODY'}}]
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=bad))) as client:
            provider = HttpOperatorProvider('https://operator.test', client)
            async def call():
                return await provider.guides(GuideQuery(route_id='route', date='2026-11-10'))
            result = await execute('check_guide_availability', {}, call, Settings(), TraceRecorder({}), 'agent_b')
            assert result['status'] == 'error'
    asyncio.run(run())
    text = path.read_text(encoding='utf-8')
    assert 'PRIVATE_CUSTOMER_RESPONSE_BODY' not in text
    assert 'input_value' not in text
    row = next(row for row in records(path) if row['event'] == 'tool.failed')
    assert row['exception']['type'] == 'ValidationError'
    assert 'operator_http.py' in row['exception']['traceback']


def test_malformed_weather_value_cannot_leak_through_chained_error(runtime, tmp_path):
    from app.tools.planning import live_weather
    from test_live_weather import payload
    path = runtime.configure_logging('test', tmp_path)
    document = payload()
    document['daily']['temperature_2m_max'] = ['PRIVATE_WEATHER_RESPONSE_VALUE']
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=document))) as client:
            async def call():
                return await live_weather(client, WeatherQuery(location='Picos de Europa', date='2026-11-10'))
            result = await execute('get_weather_forecast', {}, call, Settings(), TraceRecorder({}), 'agent_a')
            assert result['status'] == 'error'
    asyncio.run(run())
    text = path.read_text(encoding='utf-8')
    assert 'PRIVATE_WEATHER_RESPONSE_VALUE' not in text
    row = next(row for row in records(path) if row['event'] == 'tool.failed')
    assert 'planning.py' in row['exception']['traceback']
    assert row['exception']['type'] == 'ValueError'


def test_background_demo_callback_is_persisted(runtime, tmp_path, monkeypatch):
    from app.operator_demo import app
    from app.simulation.manual_services import operator_backend
    path = runtime.configure_logging('customer', tmp_path)
    url = available_url()
    monkeypatch.setenv('OPERATOR_URL', url)
    async def diagnostic():
        def fail():
            raise ConnectionResetError(10054, 'background-reset')
        asyncio.get_running_loop().call_soon(fail)
        await asyncio.sleep(0.02)
        return {'ok': True}
    app.add_api_route('/logging-test', diagnostic, methods=['GET'])
    try:
        with operator_backend('real'):
            assert httpx.get(url + '/logging-test', trust_env=False).status_code == 200
    finally:
        app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'endpoint', None) is not diagnostic]
    row = next(row for row in records(path) if row['event'] == 'asyncio.exception')
    assert row['component'] == 'operator_demo'
    assert row['exception']['type'] == 'ConnectionResetError'


def test_uncaught_subprocess_and_manual_startup_failure_are_saved(tmp_path):
    env = dict(os.environ, LOG_DIR=str(tmp_path), LOG_LEVEL='INFO')
    script = "from app.observability.runtime_logging import configure_logging; configure_logging('smoke'); raise RuntimeError('startup-smoke')"
    result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    rows = [row for path in tmp_path.glob('*.jsonl') for row in records(path)]
    assert any(row['event'] == 'uncaught.exception' and 'startup-smoke' in row['exception']['message'] for row in rows)
    import socket
    with socket.create_server(('127.0.0.1', 0)) as server:
        result = subprocess.run([sys.executable, '-m', 'app.simulation.manual', 'operator', '--port', str(server.getsockname()[1])],
            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    rows = [row for path in tmp_path.glob('manual-operator-*.jsonl') for row in records(path)]
    assert any(row['event'] == 'manual.failed' for row in rows)
