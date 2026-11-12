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
from app.route_catalog.seed import seed_store
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
            from private_agent_helpers import make_context, scoped
            context=make_context(client=client,catalog=runner.catalog)
            context.settings=Settings(mode='real')
            context.trace=runner.trace
            state={}
            tools = {tool.name: tool for tool in bind_tools('agent_a',context)}
            with scoped(context,state):
                result = await tools['search_hiking_routes'].ainvoke({'keywords':['waterfall'],'max_hours':2})
            assert result['status'] == 'success'
            assert len(result['data']) == 1
            assert result['data'][0]['route_id'] == 'PR-PNPE-2:short'
            with scoped(context,state):
                details = await tools['get_route_details'].ainvoke({'route_id':'PR-PNPE-2:short'})
            assert details['data']['route_id'] == 'PR-PNPE-2:short'
            assert 'waterfall' in details['data']['description']
            assert len(calls) == 2
            recorded = next(event['data']['output'] for event in runner.trace.events
                            if event['type'] == 'tool.completed')
            assert recorded['metadata']['catalog']['run_id']
            assert next(r['result']['data'] for r in state['observations'].values() if r['tool']=='get_route_details')['full_text']
            assert any(event['type'] == 'catalog.refreshed' for event in runner.trace.events)
    asyncio.run(run())


def test_seeded_search_accepts_optional_fields_and_keywords(tmp_path):
    store = CatalogStore(tmp_path / 'routes.sqlite3')
    seed_store(store, checked_at='2026-11-08T12:00:00+00:00')
    assert store.search(RouteQuery())
    assert store.search(RouteQuery(keywords=['Enol']))
    assert store.search(RouteQuery(keywords=['inventedvolcanoword'])) == []
    assert all(row['duration_hours'] <= 1 for row in store.search(RouteQuery(max_hours=1)))


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


def test_catalog_variant_survives_approved_http_booking_and_received_confirmation(tmp_path, monkeypatch):
    from app.evaluation.checks import evaluate
    from app.models.contracts import TripResult
    store = CatalogStore(tmp_path / 'routes.db')
    route = parse_route(page(), entry())
    store.publish([route], [entry()], complete=True, checked_at=utcnow(), run_id='seed', errors=[])
    monkeypatch.setenv('ROUTE_CATALOG_DB', str(store.path))
    from private_agent_helpers import make_context, scoped
    from app.models.contracts import GuideQuery
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            catalog=CatalogService(store,client)
            planner=make_context(catalog=catalog,client=client)
            state_a={}
            tools={t.name:t for t in bind_tools('agent_a',planner)}
            with scoped(planner,state_a):
                found=await tools['search_hiking_routes'].ainvoke({'max_hours':2})
            identity=found['data'][0]['route_id']
            assert identity=='PR-PNPE-2:short'
            terms=dict(route_id=identity,date='2026-11-10',guide_id='luis',equipment={'rain jacket':1})
            provider=HttpOperatorProvider('http://demo',client)
            operator=make_context('agent_b',provider=provider,client=client)
            state_b=dict(original_proposal={k:terms[k] for k in ('route_id','date','equipment')},selected_guide='luis',
                         approval={'reference':'approved','proposal':terms})
            with scoped(operator,state_b) as working:
                working['planning_facts']={**state_a['observations'],
                    'weather':dict(tool='get_weather_forecast',query={},result=dict(status='success',data=load_scenario('happy_path')['weather']))}
                guides=await provider.guides(GuideQuery(route_id=identity,date=terms['date']))
                operator.record_observation('check_guide_availability',{'route_id':identity,'date':terms['date']},
                    dict(status='success',data=[g.model_dump(mode='json') for g in guides]),'guides')
                operator.record_observation('check_equipment_inventory',{'date':terms['date'],'items':terms['equipment']},
                    dict(status='success',data={'quantities':{'rain jacket':3},'unavailable':[]}),'stock')
                attempt=operator.prepare_booking(terms)
                working.setdefault('dispatch_ack',{})[attempt['progress_message_id']]='sent'
                receipt=await operator.reserve(terms)
                outcome=operator.reservation_outcome()
            with scoped(planner,state_a) as working:
                working['received_outcome']=outcome.model_dump(mode='json')
                from app.models.contracts import TripSubmission
                final=planner.make_result(TripSubmission(status='confirmed',route_id=identity,date=terms['date'],guide_id='luis',equipment_items=['rain jacket']))
            assert receipt.route_id==final.route_id==identity
            assert final.reservation_id==receipt.reservation_id
    asyncio.run(run())
