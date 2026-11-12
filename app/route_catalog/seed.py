"""Initialize an empty simulation catalog from a fixed normalized snapshot."""

import json
from pathlib import Path

from app.route_catalog.models import CatalogRoute, CatalogVariant
from app.route_catalog.store import CatalogStore


SEED_PATH = Path(__file__).resolve().parents[2] / 'snapshots/routes.json'


def seed_store(store: CatalogStore, *, checked_at: str) -> str:
    if store.records():
        raise ValueError('seed_requires_empty_catalog')
    document = json.loads(SEED_PATH.read_text(encoding='utf-8'))
    if document['schema_version'] != 1:
        raise ValueError('unsupported_route_seed')
    routes = [CatalogRoute(**{
        **row, 'variants': [CatalogVariant(**variant) for variant in row['variants']]
    }) for row in document['routes']]
    entries = [dict(route_id=route.route_id, url=route.url) for route in routes]
    store.publish(routes, entries, complete=True, checked_at=checked_at,
                  run_id=document['seed_id'], errors=[], trigger='seed')
    return document['seed_id']
