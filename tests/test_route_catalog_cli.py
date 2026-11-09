import asyncio
import importlib
import json

import httpx

from app.route_catalog.parser import parse_route
from app.route_catalog.store import CatalogStore, utcnow
from test_route_parser import entry, page


def test_search_and_details_cli_without_model_credentials(tmp_path, monkeypatch, capsys):
    cli = importlib.import_module('app.route_catalog.__main__')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    path = tmp_path / 'routes.db'
    store = CatalogStore(path)
    route = parse_route(page(), entry())
    store.publish([route], [entry()], complete=True, checked_at=utcnow(), run_id='seed', errors=[])
    assert asyncio.run(cli.main(['search', '--database', str(path)])) == 0
    assert len(json.loads(capsys.readouterr().out)['items']) == 2
    assert asyncio.run(cli.main(['search', '--database', str(path), '--keywords', 'waterfall', '--max-hours', '2'])) == 0
    rows = json.loads(capsys.readouterr().out)['items']
    assert len(rows) == 1 and rows[0]['variant_id'].endswith(':short')
    assert asyncio.run(cli.main(['details', 'PR-PNPE-2:short', '--database', str(path)])) == 0
    assert 'waterfall' in json.loads(capsys.readouterr().out)['item']['full_text']


def test_refresh_cli_reports_real_import_results(tmp_path, monkeypatch, capsys):
    cli = importlib.import_module('app.route_catalog.__main__')
    client_type = httpx.AsyncClient
    def respond(request):
        body = '<a href="/route.html">PR-PNPE 2: Lake</a>' if request.url.path.endswith('itinerarios.html') else page()
        return httpx.Response(200, text=body)
    monkeypatch.setattr(cli.httpx, 'AsyncClient', lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    assert asyncio.run(cli.main(['refresh', '--database', str(tmp_path / 'routes.db')])) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['outcome'] == 'complete' and report['added'] == 1


def test_cli_reports_invalid_bounds_and_unreadable_database(tmp_path, capsys):
    cli = importlib.import_module('app.route_catalog.__main__')
    assert asyncio.run(cli.main(['search', '--database', str(tmp_path / 'routes.db'), '--min-km', '8', '--max-km', '1'])) == 1
    assert 'error' in json.loads(capsys.readouterr().out)
    path = tmp_path / 'broken.db'
    path.write_text('This is not a SQLite file', encoding='utf-8')
    assert asyncio.run(cli.main(['search', '--database', str(path)])) == 1
    assert 'error' in json.loads(capsys.readouterr().out)
