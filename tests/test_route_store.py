import importlib
import sqlite3
from contextlib import closing

import pytest
from pydantic import ValidationError

from app.models.contracts import RouteQuery
from app.route_catalog.parser import parse_route
from test_route_parser import entry, page


def store_at(tmp_path):
    return importlib.import_module("app.route_catalog.store").CatalogStore(tmp_path / "routes.sqlite3")


def publish(store, routes, when="2026-11-09T10:00:00+00:00", complete=True):
    return store.publish(routes, [dict(route_id=r.route_id, name=r.name, url=r.url, category=r.category) for r in routes],
                         complete=complete, checked_at=when, run_id=when, errors=[])


def test_optional_filters_content_search_and_read_only_connection(tmp_path):
    store = store_at(tmp_path)
    publish(store, [parse_route(page(), entry())])
    assert len(store.search(RouteQuery())) == 2
    assert len(store.search(RouteQuery(keywords=["waterfall"], max_hours=2))) == 1
    result = store.search(RouteQuery(keywords=["waterfall"], max_hours=4, max_km=6))[0]
    assert result["source_route_id"] == "PR-PNPE-2"
    assert result["route_id"] == result["variant_id"]
    assert "waterfall" in result["snippet"]
    assert store.search(RouteQuery(keywords=["volcano"])) == []
    assert len(store.search(RouteQuery(keywords=[" ", ""], limit=None, offset=None))) == 2
    with closing(store.connect_readonly()) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM routes")


def test_hash_updates_content_and_index_but_unchanged_preserves_timestamp(tmp_path):
    store = store_at(tmp_path)
    route = parse_route(page(), entry())
    publish(store, [route])
    first = store.details("PR-PNPE-2:long")
    publish(store, [route], "2026-11-09T11:00:00+00:00")
    same = store.details("PR-PNPE-2:long")
    assert first["updated_at"] == same["updated_at"]
    assert first["last_checked_at"] != same["last_checked_at"]
    changed = parse_route(page().replace("waterfall", "cave"), entry())
    publish(store, [changed], "2026-11-09T12:00:00+00:00")
    assert store.search(RouteQuery(keywords=["waterfall"])) == []
    assert len(store.search(RouteQuery(keywords=["cave"]))) == 2
    assert store.details("PR-PNPE-2:long")["updated_at"] != first["updated_at"]


def test_partial_refresh_keeps_missing_routes_and_complete_refresh_deactivates(tmp_path):
    store = store_at(tmp_path)
    first = parse_route(page(), entry())
    second = parse_route(page(), dict(entry(), route_id="PR-PNPE-9", name="Other route"))
    publish(store, [first, second])
    publish(store, [first], "2026-11-09T11:00:00+00:00", complete=False)
    assert len(store.search(RouteQuery())) == 4
    publish(store, [first], "2026-11-09T12:00:00+00:00")
    assert len(store.search(RouteQuery())) == 2
    with closing(store.connect_readonly()) as connection:
        assert connection.execute("SELECT count(*) FROM routes").fetchone()[0] == 2
    with pytest.raises(ValueError, match="empty_catalog"):
        publish(store, [])
    assert len(store.search(RouteQuery())) == 2


def test_literal_keyword_operators_do_not_expand_or_break_query(tmp_path):
    store = store_at(tmp_path)
    publish(store, [parse_route(page(), entry())])
    for text in ['waterfall" OR lake', "waterfall' OR 1=1 --", "*", "NEAR("]:
        assert store.search(RouteQuery(keywords=[text])) == []
    assert len(store.search(RouteQuery(keywords=["water"], prefix=True))) == 2


def test_unknown_measurements_and_parent_identity_are_explicit(tmp_path):
    store = store_at(tmp_path)
    route = parse_route(page(duration="unknown"), entry())
    publish(store, [route])
    assert len(store.search(RouteQuery())) == 2
    assert store.search(RouteQuery(max_hours=4)) == []
    with pytest.raises(ValueError, match="variant_required"):
        store.details("PR-PNPE-2")


def test_optional_query_rejects_invalid_bounds():
    assert RouteQuery(location=None, max_hours=None).location is None
    with pytest.raises(ValidationError):
        RouteQuery(min_km=10, max_km=5)
    with pytest.raises(ValidationError):
        RouteQuery(limit=101)
    with pytest.raises(ValidationError):
        RouteQuery(max_hours=float('inf'))


def test_any_all_accent_matching_numeric_sort_and_pagination(tmp_path):
    store = store_at(tmp_path)
    first = parse_route(page().replace('waterfall', 'cascáda'), entry())
    second = parse_route(page('10 km', '5 h').replace('waterfall', 'cave'), dict(entry(), route_id='PR-PNPE-9', name='Cave'))
    publish(store, [first, second])
    assert len(store.search(RouteQuery(keywords=['cascada', 'cave'], keyword_match='any'))) == 3
    assert store.search(RouteQuery(keywords=['cascada', 'cave'])) == []
    rows = store.search(RouteQuery(sort='distance', limit=1, offset=1))
    assert rows[0]['distance_km'] == 5
    assert len(store.search(RouteQuery(keywords=['cave'], max_hours=4))) == 0
    assert len(store.search(RouteQuery(min_km=9, min_hours=4))) == 1


def test_removed_variant_is_inactive_and_index_publication_rolls_back(tmp_path):
    store = store_at(tmp_path)
    route = parse_route(page(), entry())
    publish(store, [route])
    route.variants = route.variants[:1]
    publish(store, [route], '2026-11-09T11:00:00+00:00')
    assert len(store.search(RouteQuery(keywords=['waterfall']))) == 1
    with pytest.raises(ValueError, match='route_not_found'):
        store.details('PR-PNPE-2:short')
    route.description = 'Changed waterfall to cave'
    route.variants[0].distance_m = -1
    with pytest.raises(sqlite3.IntegrityError):
        publish(store, [route], '2026-11-09T12:00:00+00:00')
    assert store.search(RouteQuery(keywords=['cave'])) == []
    assert len(store.search(RouteQuery(keywords=['waterfall']))) == 1
