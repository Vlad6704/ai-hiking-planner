import asyncio
import importlib
from datetime import UTC, datetime

import httpx

from app.models.contracts import RouteQuery
from app.route_catalog.models import PARSER_VERSION
from app.route_catalog.store import CatalogStore
from test_route_parser import page

INDEX = 'https://www.miteco.gob.es/index.html'


def test_daily_refresh_force_conditional_get_and_parser_invalidation(tmp_path):
    module = importlib.import_module('app.route_catalog.service')
    store = CatalogStore(tmp_path / 'routes.db')
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path == '/index.html':
            return httpx.Response(200, text='<a href="/route.html">PR-PNPE 2: Lake route</a>')
        if request.headers.get('if-none-match') == 'v1':
            return httpx.Response(304)
        return httpx.Response(200, text=page(), headers={'ETag': 'v1'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = module.CatalogService(store, client, index_url=INDEX,
                clock=lambda: datetime(2026, 11, 9, 10, tzinfo=UTC))
            await service.ensure_fresh()
            first = store.details('PR-PNPE-2:long')
            await service.ensure_fresh()
            assert len(calls) == 2
            report = await service.refresh(force=True)
            assert report['unchanged'] == 1
            assert calls[-1].headers['if-none-match'] == 'v1'
            assert store.details('PR-PNPE-2:long')['updated_at'] == first['updated_at']
            old = store.records()['PR-PNPE-2']
            old.parser_version = 'older'
            store.publish([old], [dict(route_id=old.route_id, name=old.name, url=old.url)],
                          complete=True, checked_at='2026-11-09T10:00:00+00:00', run_id='old', errors=[])
            await service.refresh(force=True)
            assert 'if-none-match' not in calls[-1].headers
    asyncio.run(run())


def test_partial_and_failed_refresh_preserve_previous_data(tmp_path):
    module = importlib.import_module('app.route_catalog.service')
    store = CatalogStore(tmp_path / 'routes.db')
    state = {'stage': 0}
    def respond(request):
        if request.url.path == '/index.html':
            if state['stage'] == 2:
                return httpx.Response(200, text='<html>Changed layout, no routes</html>')
            return httpx.Response(200, text='<a href="/one.html">PR-PNPE 2: One</a><a href="/two.html">PR-PNPE 9: Two</a>')
        if state['stage'] == 1 and request.url.path == '/two.html':
            return httpx.Response(200, text='Unparseable page')
        return httpx.Response(200, text=page())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = module.CatalogService(store, client, index_url=INDEX)
            assert (await service.refresh(force=True))['parsed'] == 2
            state['stage'] = 1
            assert (await service.refresh(force=True))['outcome'] == 'partial'
            assert len(store.search(RouteQuery())) == 4
            state['stage'] = 2
            assert (await service.refresh(force=True))['outcome'] == 'failed'
            assert len(store.search(RouteQuery())) == 4
            assert store.state()['stale']
    asyncio.run(run())


def test_concurrent_services_only_fetch_once(tmp_path):
    module = importlib.import_module('app.route_catalog.service')
    store = CatalogStore(tmp_path / 'routes.db')
    calls = []
    async def respond(request):
        calls.append(request)
        await asyncio.sleep(0.03)
        return httpx.Response(200, text='<a href="/route.html">PR-PNPE 2: Lake</a>' if request.url.path == '/index.html' else page())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            one = module.CatalogService(store, client, index_url=INDEX)
            two = module.CatalogService(CatalogStore(store.path), client, index_url=INDEX)
            await asyncio.gather(one.ensure_fresh(), two.ensure_fresh())
            assert len(calls) == 2
            assert store.state()['owner'] is None
    asyncio.run(run())


def test_expired_owner_cannot_publish_over_new_owner(tmp_path):
    store = CatalogStore(tmp_path / 'routes.db')
    assert store.claim_refresh('2026-11-09', 'old', '2026-11-09T10:01:00+00:00', now='2026-11-09T10:00:00+00:00')
    assert store.claim_refresh('2026-11-09', 'new', '2026-11-09T10:03:00+00:00', now='2026-11-09T10:02:00+00:00')
    import pytest
    with pytest.raises(ValueError, match='ownership'):
        store.publish([], [], complete=False, checked_at='2026-11-09T10:02:30+00:00', run_id='old', errors=[], owned=True)


def test_empty_first_catalog_returns_typed_error_and_throttles(tmp_path):
    module = importlib.import_module('app.route_catalog.service')
    import pytest
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, text='No route links')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = module.CatalogService(CatalogStore(tmp_path / 'routes.db'), client, index_url=INDEX)
            for _ in range(2):
                with pytest.raises(ValueError, match='catalog_unavailable'):
                    await service.ensure_fresh()
            assert len(calls) == 1
    asyncio.run(run())


def test_later_local_calendar_day_refreshes_again(tmp_path):
    from datetime import timedelta
    from app.route_catalog.service import CatalogService
    calls = []
    current = datetime(2026, 11, 9, 22, 59, tzinfo=UTC)
    def respond(request):
        calls.append(request)
        return httpx.Response(200, text='<a href="/route.html">PR-PNPE 2: Lake</a>' if request.url.path == '/index.html' else page())
    async def run():
        nonlocal current
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = CatalogService(CatalogStore(tmp_path / 'routes.db'), client, index_url=INDEX, clock=lambda: current)
            await service.ensure_fresh()
            current += timedelta(minutes=2)
            await service.ensure_fresh()
            assert len(calls) == 4
    asyncio.run(run())


def test_cancellation_releases_refresh_ownership(tmp_path):
    from app.route_catalog.service import CatalogService
    import pytest
    started = asyncio.Event()
    async def respond(request):
        started.set()
        await asyncio.Future()
    async def run():
        store = CatalogStore(tmp_path / 'routes.db')
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = CatalogService(store, client, index_url=INDEX)
            task = asyncio.create_task(service.refresh())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert store.state()['owner'] is None
            assert store.state()['last_outcome'] == 'failed'
    asyncio.run(run())


def test_nonempty_incomplete_index_does_not_deactivate_previous_routes(tmp_path):
    from app.route_catalog.service import CatalogService
    stage = 0
    def respond(request):
        if request.url.path == '/index.html':
            body = '<a href="/one.html">PR-PNPE 2: One</a><a href="/two.html">PR-PNPE 9: Two</a>'
            if stage:
                body = '<a href="/one.html">PR-PNPE 2: One</a>'
            return httpx.Response(200, text=body)
        return httpx.Response(200, text=page())
    async def run():
        nonlocal stage
        store = CatalogStore(tmp_path / 'routes.db')
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = CatalogService(store, client, index_url=INDEX)
            await service.refresh(force=True)
            stage = 1
            report = await service.refresh(force=True)
            assert report['outcome'] != 'complete'
            assert len(store.search(RouteQuery())) == 4
            assert store.state()['stale']
    asyncio.run(run())
