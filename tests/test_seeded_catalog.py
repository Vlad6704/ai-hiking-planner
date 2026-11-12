import asyncio
from datetime import datetime

import httpx
import pytest

from app.agents.tools import bind_tools
from app.models.contracts import GuideQuery, RouteDetails, RouteQuery
from app.route_catalog.service import CatalogService
from app.route_catalog.store import CatalogStore
from app.simulation.config import Settings
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario
from app.tools.operator import MockOperator


@pytest.mark.parametrize('mode', ['mock', 'real'])
def test_booking_does_not_require_scenario_rentals_when_customer_owns_gear(mode):
    from private_agent_helpers import make_context, scoped
    async def run():
        terms = dict(route_id='PR-PNPE-2:long', date='2026-11-10', guide_id='luis', equipment={})
        provider = MockOperator({'2026-11-10':['luis']}, {}, [terms['route_id']])
        context = make_context('agent_b',provider=provider)
        context.settings = Settings(mode=mode)
        state = dict(original_proposal={k:terms[k] for k in ('route_id','date','equipment')},
                     selected_guide='luis',approval={'reference':'approved','proposal':terms})
        with scoped(context,state) as working:
            context.record_observation('check_guide_availability',{'route_id':terms['route_id'],'date':terms['date']},
                {'status':'success','data':[g.model_dump(mode='json') for g in await provider.guides(GuideQuery(route_id=terms['route_id'],date=terms['date']))]},'guides')
            working['planning_facts'] = {
                'routes':dict(tool='search_hiking_routes',query={},result=dict(status='success',data=[{'route_id':terms['route_id']}])),
                'weather':dict(tool='get_weather_forecast',query={},result=dict(status='success',data=load_scenario('happy_path')['weather']))}
            attempt=context.prepare_booking(terms)
            working.setdefault('dispatch_ack',{})[attempt['progress_message_id']]='sent'
            result=await context.reserve(terms)
            assert result.equipment == {}
    asyncio.run(run())


def test_seed_uses_full_catalog_schema_and_shared_retrieval(tmp_path):
    from app.route_catalog.seed import seed_store

    clock = datetime.fromisoformat('2026-11-08T12:00:00+00:00')
    store = CatalogStore(tmp_path / 'routes.sqlite3', clock=lambda: clock.isoformat())
    identity = seed_store(store, checked_at=clock.isoformat())
    assert len(store.records()) == 31
    assert len(store.search(RouteQuery(limit=100))) == 50
    details = RouteDetails.model_validate(store.details('PR-PNPE-2:long'))
    assert details.source_route_id == 'PR-PNPE-2'
    assert details.variant_id == details.route_id == 'PR-PNPE-2:long'
    assert details.full_text and details.instructions
    assert details.catalog_run_id == identity
    assert not details.catalog_stale
    with pytest.raises(ValueError, match='seed_requires_empty_catalog'):
        seed_store(store, checked_at=clock.isoformat())
    with pytest.raises(ValueError, match='variant_required'):
        store.details('PR-PNPE-2')

    async def run():
        def no_http(request):
            pytest.fail(f'Seeded retrieval attempted HTTP: {request.url}')
        async with httpx.AsyncClient(transport=httpx.MockTransport(no_http)) as client:
            for mode in ['mock', 'real']:
                from private_agent_helpers import make_context, scoped
                context=make_context(catalog=CatalogService(store,client,clock=lambda:clock,refresh_enabled=mode=='real'),client=client)
                context.settings=Settings(mode=mode)
                state={}
                tools = {tool.name: tool for tool in bind_tools('agent_a',context)}
                query = {'keywords': ['Enol'], 'max_hours': 4, 'sort': 'duration'}
                with scoped(context,state):
                    found = await tools['search_hiking_routes'].ainvoke(query)
                assert found['status'] == 'success'
                original = store.search(RouteQuery(**query))
                assert next(r['result']['data'] for r in state['observations'].values() if r['tool']=='search_hiking_routes') == original
                assert len(found['data']) == len(original)
                assert all(all(row[key] == source[key] for key in row)
                           for row, source in zip(found['data'], original))
                with scoped(context,state):
                    result = await tools['get_route_details'].ainvoke({'route_id':details.route_id})
                assert result['data']['description'] == details.description
                assert next(r['result']['data'] for r in state['observations'].values() if r['tool']=='get_route_details') == details.model_dump(mode='json')
            context.catalog.refresh_enabled = False
            with pytest.raises(ValueError, match='catalog_refresh_disabled'):
                await context.catalog.refresh(force=True)
    asyncio.run(run())


def test_mock_runner_isolates_seed_database_and_never_refreshes(tmp_path, monkeypatch):
    from test_integration import ScriptedModel
    live = tmp_path / 'live.sqlite3'
    live.write_bytes(b'Untouched live database')
    monkeypatch.setenv('ROUTE_CATALOG_DB', str(live))
    async def forbidden_refresh(*args, **kwargs):
        pytest.fail('Mock runner attempted source refresh')
    monkeypatch.setattr(CatalogService, 'refresh', forbidden_refresh)
    paths = []
    for _ in range(2):
        trip = SimulationRunner(load_scenario('happy_path'), Settings(timeout=15), 42, ScriptedModel())
        asyncio.run(trip.run())
        assert trip.error is None, trip.error
        paths.append(trip.catalog.store.path)
        assert not paths[-1].exists()
        assert trip.result.route_id == 'PR-PNPE-2:long'
        assert trip.trace.metadata['catalog_seed_id'] == 'official-catalog-2026-11-09'
        records = next(e['data']['output']['data'] for e in trip.trace.events if e['type']=='tool.completed' and e['data']['tool']=='search_hiking_routes')
        assert all(row['variant_id'] == row['route_id'] for row in records)
    assert paths[0] != paths[1]
    assert live.read_bytes() == b'Untouched live database'
