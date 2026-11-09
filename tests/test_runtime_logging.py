import importlib
import json
import logging
import os
import sys
import threading
from types import SimpleNamespace

import pytest


@pytest.fixture
def runtime():
    module = importlib.import_module('app.observability.runtime_logging')
    module.shutdown_logging()
    yield module
    module.shutdown_logging()


def records(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def test_json_identity_context_and_idempotent_setup(runtime, tmp_path):
    path = runtime.configure_logging('customer', tmp_path)
    assert runtime.configure_logging('customer', tmp_path) == path
    assert str(os.getpid()) in path.name
    with runtime.log_context(run_id='run-one', request_id='trip-one', actor='agent_a'):
        logging.getLogger('app.test').info('started')
    logging.getLogger('app.test').info('outside')
    rows = records(path)
    assert len(rows) == 2
    assert rows[0]['run_id'] == 'run-one' and rows[0]['request_id'] == 'trip-one'
    assert rows[0]['process_id'] == os.getpid() and rows[0]['thread_name']
    assert rows[0]['timestamp'].endswith('+00:00')
    assert rows[0]['role'] == 'customer' and rows[0]['actor'] == 'agent_a'
    assert rows[1]['run_id'] is None


def test_redaction_covers_exception_nested_fields_and_url_secrets(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'configured-super-secret')
    path = runtime.configure_logging('test', tmp_path)
    try:
        raise ValueError('failed https://user:pass@example.test/path?token=private#fragment configured-super-secret')
    except ValueError:
        logging.getLogger('app.test').exception('Authorization: Bearer hidden-token', extra={'fields': {
            'password': 'hidden-password', 'nested': {'api_key': 'nested-secret'},
            'url': 'https://user:pass@example.test/path?api_key=query-secret',
        }})
    text = path.read_text(encoding='utf-8')
    for secret in ('configured-super-secret', 'hidden-token', 'hidden-password', 'nested-secret', 'query-secret', 'user:pass', 'token=private'):
        assert secret not in text
    row = records(path)[0]
    assert row['exception']['type'] == 'ValueError'
    assert 'Traceback' in row['exception']['traceback']
    assert row['fields']['url'] == 'https://example.test/path'


def test_rotation_keeps_three_backups(runtime, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'MAX_BYTES', 1400)
    path = runtime.configure_logging('rotate', tmp_path)
    for index in range(40):
        logging.getLogger('app.test').info('rotation %s %s', index, 'x' * 150)
    assert len(list(tmp_path.iterdir())) == 4
    assert len(list(tmp_path.glob(path.name + '.*'))) == 3
    assert records(path)[-1]['event'].startswith('rotation 39 ')


def test_invalid_configuration_fails_explicitly(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv('LOG_LEVEL', 'UNKNOWN')
    with pytest.raises(ValueError, match='LOG_LEVEL'):
        runtime.configure_logging('test', tmp_path)
    monkeypatch.setenv('LOG_LEVEL', 'INFO')
    occupied = tmp_path / 'not-a-directory'
    occupied.write_text('occupied', encoding='utf-8')
    with pytest.raises(OSError):
        runtime.configure_logging('test', occupied)


def test_uncaught_hooks_log_and_preserve_custom_handlers(runtime, tmp_path):
    old_sys, old_thread = sys.excepthook, threading.excepthook
    called = []
    try:
        sys.excepthook = lambda *args: called.append('main')
        threading.excepthook = lambda args: called.append('thread')
        path = runtime.configure_logging('test', tmp_path)
        error = RuntimeError('uncaught example')
        sys.excepthook(type(error), error, None)
        threading.excepthook(SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=None, thread=threading.current_thread()))
        assert called == ['main', 'thread']
        assert [row['event'] for row in records(path)] == ['uncaught.exception', 'thread.exception']
        runtime.shutdown_logging()
        assert sys.excepthook is not old_sys
    finally:
        runtime.shutdown_logging()
        sys.excepthook, threading.excepthook = old_sys, old_thread


def test_debug_does_not_enable_http_payload_dumps(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    path = runtime.configure_logging('test', tmp_path)
    logging.getLogger('app.test').debug('application debug')
    child = logging.getLogger('httpcore.connection')
    previous = child.level
    try:
        child.setLevel(logging.DEBUG)
        child.debug('request body secret')
    finally:
        child.setLevel(previous)
    assert [row['event'] for row in records(path)] == ['application debug']


def test_basic_authorization_is_fully_redacted_from_errors(runtime, tmp_path):
    path = runtime.configure_logging('test', tmp_path)
    try:
        raise RuntimeError('Authorization: Basic dXNlcjpwYXNz')
    except RuntimeError:
        logging.getLogger('app.test').exception('header error')
    assert 'dXNlcjpwYXNz' not in path.read_text(encoding='utf-8')
    assert records(path)[0]['exception']['type'] == 'RuntimeError'
