"""Payload-free diagnostics for the application's existing HTTP clients."""

import logging
import time

from app.observability.runtime_logging import safe_url

logger = logging.getLogger('app.http')


async def request_started(request):
    request.extensions['hiking_log_start'] = time.monotonic()
    logger.info('http.request', extra={'fields': {'method': request.method, 'url': safe_url(request.url)}})


async def response_received(response):
    started = response.request.extensions.get('hiking_log_start', time.monotonic())
    fields = dict(method=response.request.method, url=safe_url(response.request.url), status=response.status_code,
                  duration_ms=round((time.monotonic() - started) * 1000), local_address=None, peer_address=None)
    stream = response.extensions.get('network_stream')
    if stream is not None:
        for name, key in (('client_addr', 'local_address'), ('server_addr', 'peer_address')):
            try:
                fields[key] = stream.get_extra_info(name)
            except (AttributeError, OSError, RuntimeError):
                pass
    logger.info('http.response', extra={'fields': fields})


def attach_http_logging(client):
    for kind, hook in (('request', request_started), ('response', response_received)):
        if hook not in client.event_hooks[kind]:
            client.event_hooks[kind].append(hook)
