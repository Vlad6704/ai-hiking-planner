"""Process-owned operational logs, separate from trajectories and LLM traces."""

import json
import logging
import os
import re
import sys
import threading
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

MAX_BYTES = 5 * 1024 * 1024
_context = ContextVar('runtime_log_context', default={})
_handlers = []
_path = None
_previous = None
_levels = {}
_lock = threading.RLock()
_sensitive = re.compile(r'authorization|password|api[_-]?key|access[_-]?token|secret', re.I)
_quiet_libraries = ('httpx', 'httpcore', 'openai', 'langsmith')


def operational_records_only(record):
    return record.levelno >= logging.WARNING or not any(
        record.name == name or record.name.startswith(name + '.') for name in _quiet_libraries
    )


def safe_url(value):
    try:
        parsed = urlsplit(str(value))
        host = parsed.hostname or ''
        if ':' in host:
            host = '[' + host + ']'
        authority = host + (f':{parsed.port}' if parsed.port else '')
        return urlunsplit((parsed.scheme, authority, parsed.path, '', ''))
    except ValueError:
        return '[invalid URL]'


def sanitize(value, secrets=()):
    if isinstance(value, dict):
        return {str(key): '[redacted]' if _sensitive.search(str(key)) else sanitize(item, secrets)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item, secrets) for item in value]
    if not isinstance(value, str):
        return value if value is None or isinstance(value, (int, float, bool)) else sanitize(str(value), secrets)
    for secret in secrets:
        value = value.replace(secret, '[redacted]')
    value = re.sub(r'''(?i)(authorization["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\r\n,;}"']+)''',
                   r'\1[redacted]', value)
    value = re.sub(r'https?://[^\s<>"\']+', lambda match: safe_url(match[0]), value)
    value = re.sub(r'Bearer\s+[^\s"\',;]+', 'Bearer [redacted]', value, flags=re.I)
    value = re.sub(r'(?i)(authorization|password|api[_-]?key|access[_-]?token|secret)(["\']?\s*[:=]\s*["\']?)([^\s"\',;}]+)',
                   r'\1\2[redacted]', value)
    return re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[redacted-email]', value)


def exception_message(error):
    # Validation/provider exceptions can embed entire untrusted response bodies.
    if callable(getattr(error, 'error_count', None)) and callable(getattr(error, 'errors', None)):
        return f'Validation failed ({error.error_count()} errors); input values omitted'
    if hasattr(error, 'body'):
        return f'Provider request failed; status={getattr(error, "status_code", None)}; body omitted'
    if isinstance(error, (ValueError, TypeError, KeyError, IndexError)):
        return 'Input validation or conversion failed; input details omitted'
    return str(error)


def exception_trace(error, tb, seen=None, *, chained=False):
    """Keep every stack frame and cause without source lines or input values."""
    seen = seen if seen is not None else set()
    if id(error) in seen:
        return ''
    seen.add(id(error))
    parts = []
    cause = error.__cause__ or (error.__context__ if not error.__suppress_context__ else None)
    if cause is not None:
        parts += [exception_trace(cause, cause.__traceback__, seen, chained=True), 'During handling of the preceding exception:\n']
    parts.append('Traceback (most recent call last):\n')
    for frame, line in traceback.walk_tb(tb):
        parts.append(f'  File "{frame.f_code.co_filename}", line {line}, in {frame.f_code.co_name}\n')
    message = (f'details omitted; errno={getattr(error, "errno", None)}; winerror={getattr(error, "winerror", None)}'
               if chained else exception_message(error))
    parts.append(f'{type(error).__name__}: {message}\n')
    for child in getattr(error, 'exceptions', ()):
        parts.append(exception_trace(child, child.__traceback__, seen, chained=True))
    return ''.join(parts)


class JsonFormatter(logging.Formatter):
    def __init__(self, role):
        super().__init__()
        self.role = role
        self.secrets = tuple(value for key, value in os.environ.items()
                             if _sensitive.search(key) and len(value) >= 4)

    def format(self, record):
        context = _context.get()
        document = dict(timestamp=datetime.fromtimestamp(record.created, UTC).isoformat(),
                        level=record.levelname, logger=record.name, event=record.getMessage(),
                        process_id=record.process, thread_name=record.threadName, role=self.role,
                        component=context.get('component', self.role),
                        **{key: context.get(key) for key in ('run_id', 'request_id', 'actor', 'operation_id', 'attempt')},
                        fields=getattr(record, 'fields', {}))
        if record.exc_info:
            kind, error, _ = record.exc_info
            document['exception'] = dict(type=kind.__name__, message=exception_message(error),
                errno=getattr(error, 'errno', None), winerror=getattr(error, 'winerror', None),
                traceback=exception_trace(error, record.exc_info[2]))
        return json.dumps(sanitize(document, self.secrets), ensure_ascii=False, default=str)


@contextmanager
def log_context(**fields):
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def log_path():
    return _path


def configure_logging(role, directory=None):
    global _path, _previous
    with _lock:
        if _path is not None:
            return _path
        level = os.getenv('LOG_LEVEL', 'INFO').upper()
        if level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            raise ValueError('LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL')
        default = Path(__file__).resolve().parents[2] / 'logs'
        folder = Path(directory or os.getenv('LOG_DIR') or default).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[^a-zA-Z0-9_-]', '-', role)
        path = folder / f'{name}-{os.getpid()}-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.jsonl'
        file_handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=3, encoding='utf-8')
        formatter = JsonFormatter(role)
        file_handler.setFormatter(formatter)
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.ERROR)
        console.setFormatter(formatter)
        root = logging.getLogger()
        _levels[''] = root.level
        root.setLevel(level)
        for handler in (file_handler, console):
            handler.addFilter(operational_records_only)
            root.addHandler(handler)
            _handlers.append(handler)
        for name in _quiet_libraries:
            logger = logging.getLogger(name)
            _levels[name] = logger.level
            logger.setLevel(logging.WARNING)
        _path = path
        _previous = sys.excepthook, threading.excepthook

        def uncaught(kind, error, traceback):
            logging.getLogger('app.runtime').critical('uncaught.exception', exc_info=(kind, error, traceback))
            if _previous[0] is not sys.__excepthook__:
                _previous[0](kind, error, traceback)

        def thread_error(args):
            logging.getLogger('app.runtime').critical('thread.exception',
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                extra={'fields': {'failed_thread': args.thread.name if args.thread else None}})
            if _previous[1] is not threading.__excepthook__:
                _previous[1](args)

        sys.excepthook, threading.excepthook = uncaught, thread_error
        return path


def shutdown_logging():
    """Release only this module's handlers/hooks; useful for embedded callers/tests."""
    global _path, _previous
    with _lock:
        root = logging.getLogger()
        for handler in _handlers:
            root.removeHandler(handler)
            handler.close()
        _handlers.clear()
        if _previous is not None:
            sys.excepthook, threading.excepthook = _previous
        for name, level in _levels.items():
            logging.getLogger(name).setLevel(level)
        _levels.clear()
        _previous = None
        _path = None
