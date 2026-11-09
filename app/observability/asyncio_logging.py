"""Scoped asyncio exception diagnostics with best-effort socket attribution."""

import asyncio
import logging
from contextlib import contextmanager

from app.observability.runtime_logging import log_context

logger = logging.getLogger('app.asyncio')


def connection_fields(transport):
    fields = dict(transport_type=type(transport).__name__ if transport is not None else None,
                  local_address=None, peer_address=None)
    if transport is not None:
        for name, key in (('sockname', 'local_address'), ('peername', 'peer_address')):
            try:
                fields[key] = transport.get_extra_info(name)
            except Exception:
                pass
    return fields


@contextmanager
def capture_asyncio_errors(component, loop=None):
    loop = loop or asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    if getattr(previous, '_hiking_runtime_diagnostics', False):
        yield
        return

    def handler(loop, context):
        handle = context.get('handle')
        callback = getattr(handle, '_callback', None)
        transport = context.get('transport')
        if transport is None:
            owner = getattr(callback, '__self__', None)
            if hasattr(owner, 'get_extra_info'):
                transport = owner
        task = context.get('task') or context.get('future')
        fields = connection_fields(transport)
        fields.update(callback=getattr(callback, '__qualname__', None),
                      task_name=task.get_name() if isinstance(task, asyncio.Task) else None,
                      message='Callback failed' if handle else context.get('message'))
        error = context.get('exception')
        info = (type(error), error, error.__traceback__) if isinstance(error, BaseException) else None
        with log_context(component=component):
            logger.error('asyncio.exception', exc_info=info, extra={'fields': fields})
        if previous is not None:
            previous(loop, context)

    handler._hiking_runtime_diagnostics = True
    loop.set_exception_handler(handler)
    try:
        yield
    finally:
        loop.set_exception_handler(previous)
