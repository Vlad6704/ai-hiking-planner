import importlib
import socket

import httpx
import pytest


def available_url():
    with socket.create_server(('127.0.0.1', 0)) as listener:
        return f'http://127.0.0.1:{listener.getsockname()[1]}'


def test_real_manual_backend_is_ready_reused_and_stopped(monkeypatch):
    services = importlib.import_module('app.simulation.manual_services')
    url = available_url()
    monkeypatch.setenv('OPERATOR_URL', url)
    with services.operator_backend('real'):
        assert httpx.get(url + '/health', trust_env=False).json() == {'service': 'picos-operator-demo'}
        with services.operator_backend('real'):
            assert httpx.get(url + '/health', trust_env=False).status_code == 200
        assert httpx.get(url + '/health', trust_env=False).status_code == 200
    with pytest.raises(httpx.TransportError):
        httpx.get(url + '/health', timeout=0.2, trust_env=False)


def test_mock_and_remote_manual_endpoints_do_not_start_demo(monkeypatch):
    services = importlib.import_module('app.simulation.manual_services')
    monkeypatch.setattr(services, 'start_demo', lambda *args: pytest.fail('Unexpected local demo startup'))
    monkeypatch.setenv('OPERATOR_URL', 'http://127.0.0.1:8765')
    with services.operator_backend('mock'):
        pass
    monkeypatch.setenv('OPERATOR_URL', 'https://operator.example/api')
    with services.operator_backend('real'):
        pass


def test_unrelated_occupied_port_is_an_explicit_error(monkeypatch):
    services = importlib.import_module('app.simulation.manual_services')
    with socket.create_server(('127.0.0.1', 0)) as listener:
        monkeypatch.setenv('OPERATOR_URL', f'http://127.0.0.1:{listener.getsockname()[1]}')
        with pytest.raises(RuntimeError, match='occupied'):
            with services.operator_backend('real'):
                pytest.fail('An unrelated service must not be reused')
