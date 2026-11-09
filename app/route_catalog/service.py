"""Bounded source refresh with daily throttling and fenced writer ownership."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin
from uuid import uuid4

import httpx

from app.route_catalog.models import PARSER_VERSION
from app.route_catalog.parser import Document, INDEX_URL, allowed_url, discover_routes, parse_route
from app.route_catalog.store import CatalogStore, local_day


class CatalogService:
    def __init__(self, store: CatalogStore, client: httpx.AsyncClient, *, clock=None, index_url=INDEX_URL):
        self.store, self.client = store, client
        self.clock = clock or (lambda: datetime.now(UTC))
        self.index_url = index_url
        self.last_report = None

    async def fetch(self, url, headers=None):
        if not allowed_url(url, self.index_url):
            raise ValueError("unsupported_route_origin")
        for attempt in range(3):
            try:
                target = url
                for _ in range(4):
                    response = await self.client.get(target, headers=headers or {}, timeout=10, follow_redirects=False)
                    if response.status_code in (301, 302, 303, 307, 308):
                        target = urljoin(target, response.headers.get("location", ""))
                        if not allowed_url(target, self.index_url):
                            raise ValueError("unsupported_route_redirect")
                        continue
                    if response.status_code != 304:
                        response.raise_for_status()
                    if len(response.content) > 2_000_000:
                        raise ValueError("route_page_too_large")
                    return response
                raise ValueError("too_many_route_redirects")
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.TransportError) or exc.response.status_code in (429, 503, 502, 504)
                if not retryable or attempt == 2:
                    raise
                await asyncio.sleep(0.2 * 2 ** attempt)

    async def refresh(self, force=False):
        start = self.clock()
        owner = str(uuid4())
        acquired = self.store.claim_refresh(local_day(start.isoformat()), owner,
            (start + timedelta(seconds=180)).isoformat(), force, now=start.isoformat())
        if not acquired:
            deadline = time.monotonic() + 125
            while self.store.state()["owner"] and time.monotonic() < deadline:
                state = self.store.state()
                if not state["lease_until"] or datetime.fromisoformat(state["lease_until"]) <= self.clock():
                    return await self.refresh(force=force)
                await asyncio.sleep(0.05)
            return dict(outcome="cached", **self.store.state())
        try:
            async with asyncio.timeout(120):
                response = await self.fetch(self.index_url)
                entries = discover_routes(response.text, self.index_url)
                if not entries:
                    raise ValueError("empty_catalog")
                previous = self.store.records()
                active = self.store.active_ids()
                missing = active - {entry['route_id'] for entry in entries}
                if missing:
                    links = {urljoin(self.index_url, href).split('#', 1)[0] for href, _ in Document(response.text).links}
                    if (len(entries) < len(active) * 0.8 or '</html>' not in response.text.casefold()
                            or any(previous[route_id].url in links for route_id in missing)):
                        raise ValueError('catalog_discovery_incomplete')
                semaphore = asyncio.Semaphore(3)

                async def load(entry):
                    async with semaphore:
                        try:
                            old = previous.get(entry["route_id"])
                            reusable = old and old.parser_version == PARSER_VERSION and old.url == entry["url"] and bool(old.variants)
                            headers = {}
                            if reusable and old.etag: headers["If-None-Match"] = old.etag
                            if reusable and old.last_modified: headers["If-Modified-Since"] = old.last_modified
                            page = await self.fetch(entry["url"], headers)
                            if page.status_code == 304:
                                if not reusable:
                                    raise ValueError("unexpected_not_modified")
                                route = old
                            else:
                                route = parse_route(page.text, entry)
                            route.etag = page.headers.get("etag", route.etag)
                            route.last_modified = page.headers.get("last-modified", route.last_modified)
                            return route, None
                        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                            return None, dict(route_id=entry["route_id"], url=entry["url"], error=str(exc))

                results = await asyncio.gather(*(load(entry) for entry in entries))
                routes = [route for route, _ in results if route is not None]
                errors = [error for _, error in results if error is not None]
                self.last_report = self.store.publish(routes, entries, complete=not errors,
                    checked_at=self.clock().isoformat(), run_id=owner, errors=errors,
                    trigger="manual" if force else "automatic", owned=True)
                return self.last_report
        except asyncio.CancelledError:
            self.store.fail_refresh(owner, "refresh_cancelled", self.clock().isoformat())
            raise
        except (httpx.HTTPError, ValueError, TimeoutError, KeyError, TypeError) as exc:
            self.last_report = self.store.fail_refresh(owner, str(exc), self.clock().isoformat())
            return self.last_report

    async def ensure_fresh(self):
        await self.refresh()
        if not self.store.has_usable():
            raise ValueError("catalog_unavailable: run the route catalog refresh command and inspect its errors")
        state = self.store.state()
        # A supplied clock also controls freshness diagnostics in deterministic tests.
        state["stale"] = (state["last_outcome"] != "complete" or not state["last_success_at"]
                          or local_day(state["last_success_at"]) != local_day(self.clock().isoformat()))
        return state
