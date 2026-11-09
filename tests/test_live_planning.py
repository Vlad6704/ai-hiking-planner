import asyncio

import httpx

from app.agents.tools import bind_tools
from app.models.contracts import GuideQuery, RouteQuery
from app.operator_demo import app
from app.route_catalog.parser import parse_route
from app.route_catalog.service import CatalogService
from app.route_catalog.store import CatalogStore, utcnow
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario
from app.tools.adapters.operator_http import HttpOperatorProvider
from app.tools.planning import search
from test_route_parser import entry, page


def test_real_tools_search_database_and_preserve_variant_identity(tmp_path):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, text='<a href="/route.html">PR-PNPE 2: Lake</a>' if request.url.path == '/index.html' else page())
    async def run():
        runner = SimulationRunner(load_scenario('happy_path'), Settings(mode='real'), 42)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            runner.client = client
            runner.catalog = CatalogService(CatalogStore(tmp_path / 'routes.db'), client,
                index_url='https://www.miteco.gob.es/index.html')
            tools = {tool.name: tool for tool in bind_tools(runner, 'agent_a')}
            result = await tools['search_hiking_routes'].ainvoke({'keywords': ['waterfall'], 'max_hours': 2})
            assert result['status'] == 'success'
            assert len(result['data']) == 1
            assert result['data'][0]['route_id'] == 'PR-PNPE-2:short'
            details = await tools['get_route_details'].ainvoke({'route_id': 'PR-PNPE-2:short'})
            assert details['data']['variant_id'] == 'PR-PNPE-2:short'
            assert 'waterfall' in details['data']['full_text']
            assert len(calls) == 2
            assert result['metadata']['catalog']['run_id']
            assert any(event['type'] == 'catalog.refreshed' for event in runner.trace.events)
    asyncio.run(run())


def test_mock_search_accepts_optional_fields_and_keywords():
    assert search(RouteQuery())[0].route_id == 'PR-PNPE-2'
    assert search(RouteQuery(keywords=['lakes']))
    assert search(RouteQuery(keywords=['volcano'])) == []
    assert search(RouteQuery(max_hours=1)) == []


def test_operator_demo_accepts_catalog_variant(tmp_path, monkeypatch):
    store = CatalogStore(tmp_path / 'routes.db')
    route = parse_route(page(), entry())
    store.publish([route], [entry()], complete=True, checked_at=utcnow(), run_id='seed', errors=[])
    monkeypatch.setenv('ROUTE_CATALOG_DB', str(store.path))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            provider = HttpOperatorProvider('http://demo', client)
            guides = await provider.guides(GuideQuery(route_id='PR-PNPE-2:short', date='2026-11-10'))
            assert [guide.guide_id for guide in guides] == ['ines', 'luis']
            assert all('PR-PNPE-2:short' in guide.qualifications for guide in guides)
            assert await provider.guides(GuideQuery(route_id='invented', date='2026-11-10')) == []
    asyncio.run(run())


def test_catalog_variant_survives_approved_http_booking_and_evaluation(tmp_path, monkeypatch):
    from app.evaluation.checks import evaluate
    from app.models.contracts import TripResult
    from app.tools.operator import OperatorTools
    store = CatalogStore(tmp_path / 'routes.db')
    route = parse_route(page(), entry())
    store.publish([route], [entry()], complete=True, checked_at=utcnow(), run_id='seed', errors=[])
    monkeypatch.setenv('ROUTE_CATALOG_DB', str(store.path))
    async def run():
        runner = SimulationRunner(load_scenario('happy_path'), Settings(mode='real'), 42)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            runner.client = client
            runner.catalog = CatalogService(store, client)
            runner.provider = HttpOperatorProvider('http://demo', client)
            runner.operator = OperatorTools(runner.rid, runner.approvals, runner.provider)
            planner = {tool.name: tool for tool in bind_tools(runner, 'agent_a')}
            operator = {tool.name: tool for tool in bind_tools(runner, 'agent_b')}
            found = await planner['search_hiking_routes'].ainvoke({'max_hours': 2})
            identity = found['data'][0]['route_id']
            assert identity == 'PR-PNPE-2:short'
            terms = dict(route_id=identity, date='2026-11-10', guide_id='luis', equipment={'rain jacket': 1})
            runner.observed['get_weather_forecast'] = [{'days': [{'date': '2026-11-10', 'wind_kmh': 10, 'precipitation_probability': 0}]}]
            runner.approvals.record(runner.rid, terms, 'approved')
            receipt = await operator['create_tour_reservation'].ainvoke(terms)
            assert receipt['status'] == 'success'
            assert receipt['data']['route_id'] == identity
            runner.result = TripResult(request_id=runner.rid, status='confirmed', **{k: receipt['data'][k] for k in ('route_id', 'date', 'guide_id', 'reservation_id')}, equipment_items=['rain jacket'])
            assert evaluate(runner)['checks']['route']
    asyncio.run(run())
