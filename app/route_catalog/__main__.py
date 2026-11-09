"""Refresh the official route catalog or query its local SQLite dataset."""

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

import httpx

from app.models.contracts import RouteQuery
from app.route_catalog.service import CatalogService
from app.route_catalog.store import CatalogStore, database_path


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    refresh = commands.add_parser('refresh', help='Force a source refresh, including after today\'s automatic attempt.')
    search = commands.add_parser('search', help='Search with optional SQL filters and literal full-text keywords.')
    details = commands.add_parser('details', help='Read full details using a public variant ID.')
    for command in (refresh, search, details):
        command.add_argument('--database', type=Path, default=argparse.SUPPRESS)
    details.add_argument('route_id')
    search.add_argument('--location')
    search.add_argument('--difficulty')
    for name in ('min_hours', 'max_hours', 'min_km', 'max_km'):
        search.add_argument('--' + name.replace('_', '-'), type=float)
    for name in ('min_gain_m', 'max_gain_m', 'min_loss_m', 'max_loss_m', 'limit', 'offset'):
        search.add_argument('--' + name.replace('_', '-'), type=int)
    search.add_argument('--keywords', nargs='+')
    search.add_argument('--keyword-match', choices=['all', 'any'])
    search.add_argument('--prefix', action='store_true')
    search.add_argument('--sort', choices=['relevance', 'name', 'distance', 'duration', 'ascent', 'descent'])
    args = parser.parse_args(argv)
    try:
        query = RouteQuery(**{key: value for key, value in vars(args).items() if key not in ('command', 'database')}) if args.command == 'search' else None
        store = CatalogStore(args.database or database_path())
        async with httpx.AsyncClient() as client:
            service = CatalogService(store, client)
            if args.command == 'refresh':
                report = await service.refresh(force=True)
                print(json.dumps(report, ensure_ascii=False))
                return int(report['outcome'] != 'complete')
            state = await service.ensure_fresh()
            result = {'items': store.search(query)} if query is not None else {'item': store.details(args.route_id)}
            print(json.dumps(dict(**result, catalog=state), ensure_ascii=False))
            return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
