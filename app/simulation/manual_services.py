"""Manage the loopback HTTP demo for a one-command real manual session."""

import os
import socket
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx
import uvicorn

DEFAULT_OPERATOR_URL = 'http://127.0.0.1:8765'


def is_demo(url):
    try:
        response = httpx.get(url.rstrip('/') + '/health', timeout=0.5, trust_env=False)
        return response.status_code == 200 and response.json() == {'service': 'picos-operator-demo'}
    except (httpx.HTTPError, ValueError):
        return False


@contextmanager
def start_demo(url, port):
    try:
        listener = socket.create_server(('127.0.0.1', port))
    except OSError as exc:
        raise RuntimeError(f'Operator demo port {port} is occupied or unavailable. Set OPERATOR_URL to an available loopback port.') from exc
    with listener:
        server = uvicorn.Server(uvicorn.Config(
            'app.operator_demo:app', log_level='error', access_log=False,
            timeout_graceful_shutdown=2,
        ))
        errors = []

        def serve():
            try:
                server.run(sockets=[listener])
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=serve, name='manual-operator-demo', daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    detail = str(errors[0]) if errors else 'startup timed out'
                    raise RuntimeError(f'Operator demo startup failed: {detail}')
                time.sleep(0.02)
            print(f'Started local HTTP operator demo at {url}.', flush=True)
            yield
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=1)


@contextmanager
def operator_backend(mode):
    if mode != 'real':
        yield
        return
    url = os.environ.setdefault('OPERATOR_URL', DEFAULT_OPERATOR_URL)
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        yield
        return
    if is_demo(url):
        print(f'Using existing HTTP operator demo at {url}.', flush=True)
        yield
        return
    with start_demo(url, parsed.port or 80):
        yield
