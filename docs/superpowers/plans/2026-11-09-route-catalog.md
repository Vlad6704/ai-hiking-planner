# Persistent Route Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Import the full official route catalog into SQLite and expose optional-filter, read-only SQL/FTS5 search and variant-specific details.

**Architecture:** A source parser produces validated route/variant records. A repository owns transactional storage and lexical indexing, a service owns bounded HTTP refresh and cross-process ownership, and existing tools consume a read-only query API. Mock fixtures remain offline.

**Tech Stack:** Python 3.11+, standard-library HTMLParser/sqlite3/zoneinfo, httpx, Pydantic v2, SQLite FTS5, pytest; tzdata supplies portable timezone data on Windows.

**Spec:** [Feature design](../../route-catalog-design.md), [system design](../../technical-design.md) and repository AGENTS.md.

## Global Constraints

- The technical design remains authoritative; completed plans are historical records.
- Preserve the seven domain tool names and exactly two operational agents.
- All search arguments are optional; default limit 20, maximum 100, offset 0.
- Store metric values in metres/minutes; retain unknown values as NULL.
- Hash normalized business content including all variants; exclude retrieval timestamps.
- Automatic refresh occurs once per Europe/Warsaw calendar day; explicit refresh can run again.
- Query connections are read-only; network refresh does not hold a write transaction.
- Preserve source text as external data; authored content is English.
- Existing uncommitted work is preserved in the current feature checkout. No automatic commits are required by this plan; any later commit requires the AGENTS.md staged review.

## Review Focus

1. Mixed one-way/return measurements must not be paired incorrectly: parser tests include conflicting labels and missing measurements.
2. Partial or empty source discovery must not erase valid records: refresh tests check retained and inactive records separately.
3. Concurrent first requests must publish at most one refresh: service tests exercise overlapping owners and lease expiry.
4. Literal keyword punctuation must neither execute SQL nor break FTS syntax: repository tests cover quotes, operators and empty keywords.
5. A route variant selected by search must remain the same at details and booking: integration tests retain the variant ID through the HTTP demo.

## File structure

- `app/route_catalog/models.py`: normalized source records and content identity.
- `app/route_catalog/parser.py`: HTML discovery, labelled sections and conservative variant extraction.
- `app/route_catalog/schema.sql`: versioned relational schema and FTS index.
- `app/route_catalog/store.py`: transactions, ownership, publication and read-only search/details.
- `app/route_catalog/service.py`: HTTP refresh, daily freshness and diagnostics.
- `app/route_catalog/__main__.py`: refresh/search/details commands without an LLM.
- Existing contracts, planning tools, runner, operator demo and documentation integrate these components.

### Task 1: Parse the complete source catalog

**Files:** Create `app/route_catalog/models.py`, `app/route_catalog/parser.py`, `tests/test_route_parser.py`.

**Interfaces:** `discover_routes(html: str, index_url: str) -> list[dict]` yields stable source IDs, names and allowed source URLs. `parse_route(html: str, entry: dict) -> CatalogRoute` yields full source text, structured sections, variants, raw measurements and warnings. `content_hash(route: CatalogRoute) -> str` excludes timestamps.

- [x] Write tests for PR/GR discovery with duplicates/navigation links; long/short and one-way/return matching; decimal comma/apostrophe/thousands separators; full description/cautions; missing/ambiguous durations. Assert long loop 5,000 m / 150 minutes and short loop 3,000 m / 60 minutes remain distinct.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_route_parser.py -q`; expect missing parser failures.
- [x] Implement source parsing with bounded, origin-checked links and conservative label matching. Keep every discovered source entry even when some metrics cannot be normalized.
- [x] Repeat parser tests; expect all passing. Compare the downloaded official index/pages against parser output and record any source ambiguities.

### Task 2: Persist routes and expose optional-filter SQL/FTS search

**Files:** Create `app/route_catalog/schema.sql`, `app/route_catalog/store.py`, `tests/test_route_store.py`. Extend `app/models/contracts.py`, `.gitignore`.

**Interfaces:** `CatalogStore(path: Path)`; `publish(routes, entries, *, complete, checked_at, run_id, errors)`; `search(query: RouteQuery) -> list[dict]`; `details(route_id: str) -> dict`; `state() -> dict`. Store source IDs separately from public variant IDs.

- [x] Write real temporary-database tests for hash-driven updates, unchanged `updated_at`, FTS replacement, SQL numeric filters, all-optional arguments, null/empty defaults, pagination and literal keyword handling. Assert a waterfall record matches `keywords=['waterfall']` plus `max_hours=4`, while a five-hour record does not.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_route_store.py -q`; expect missing store/query behavior failures.
- [x] Implement migrations, foreign keys, indexes, canonical hashing and atomic publication. Query via URI `mode=ro` plus query-only. Parameterize values and allowlist sort clauses; bound keywords and page size. Return source metadata, excerpts, content hash and variant identity.
- [x] Repeat tests, including a failed INSERT through the read connection and a renamed/removed variant disappearing from FTS while historical records remain stored.

### Task 3: Refresh with daily freshness and cross-process ownership

**Files:** Create `app/route_catalog/service.py`, `tests/test_route_refresh.py`. Extend store ownership/state methods. Add portable timezone data dependency.

**Interfaces:** `CatalogService(store, client, *, clock=None)`; `async refresh(force: bool = False) -> dict`; `async ensure_fresh() -> dict`. `CatalogStore.claim_refresh(day, owner, lease_until, force=False) -> bool` obtains ownership in a short transaction.

- [x] Write HTTP-transport and real-database tests for complete import, conditional HTTP 304, parser-version invalidation, unchanged pages, partial/empty index failure, stale reads, first-run failure, daily throttling, explicit refresh and overlapping owners.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_route_refresh.py -q`; expect missing service failures.
- [x] Implement concurrency limit 3, bounded retries/deadlines, an expiring lease with ownership checks, refresh history and short atomic publication. Do not deactivate missing routes after partial refresh. Preserve old content on page failures and expose stale/partial status.
- [x] Repeat tests; assert two same-day requests do not duplicate HTTP refresh, while a forced request and a later calendar day do.

### Task 4: Provide catalog commands

**Files:** Create `app/route_catalog/__main__.py`, `tests/test_route_catalog_cli.py`.

**Interfaces:** `python -m app.route_catalog refresh|search|details`; optional `--database`, search flags matching RouteQuery, details requires public route ID. Use `ROUTE_CATALOG_DB` or `data/routes.sqlite3` by default.

- [x] Write CLI tests on a real temporary catalog: empty-filter search returns its first page, keyword/numeric flags filter it, details returns full source text, invalid arguments fail, refresh reports counts and failures as JSON.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_route_catalog_cli.py -q`; expect missing entrypoint failures.
- [x] Implement command parsing and useful exit codes. Keep these commands independent of model credentials and agent construction.
- [x] Repeat tests and run each command's `--help`; expect documented flags and no model construction.

### Task 5: Integrate real route tools and demo booking

**Files:** Modify `app/agents/tools.py`, `app/agents/factory.py`, `app/simulation/runner.py`, `app/operator_demo.py`, `app/evaluation/checks.py`; create `tests/test_live_planning.py`.

**Interfaces:** Real search/details use `CatalogService` freshness followed by store reads. Public `route_id` is the selected variant ID, with `source_route_id` and `variant_id` also present. Existing mock IDs and scripted scenarios remain valid.

- [x] Write tool integration tests with real SQLite and HTTP transports: source refresh precedes search, metadata is traced, optional mock filters remain compatible, variant details preserve identity and demo guide qualifications accept known catalog variants. Real-mode evaluation checks an observed route rather than hard-coding PR-PNPE-2.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_live_planning.py -q`; expect missing integration failures.
- [x] Connect the existing tool names to catalog adapters; account for refresh outside the short per-tool deadline and preserve mock injection behavior. Include source-language keyword guidance and explicit variant identity in prompts.
- [x] Repeat integration tests and the existing agent/operator/evaluation suites; expect offline mocks and authorization checks unchanged.

### Task 6: Verify live sources and document operation

**Files:** Update README, feature design and `.env.example`; add live evidence under an ignored local directory.

**Interfaces:** Manual refresh, search and details work without the LLM. Automatic and manual real-mode agents consume the same catalog.

- [x] Run the full offline suite; expect no failures. Inspect optional-field schemas and malformed/partial-source tests.
- [x] Refresh from the live official index, inspect all discovered entries, run keyword and numeric searches, retrieve variant details, and repeat refresh to verify unchanged hashes preserve update timestamps. Record actual counts and any source ambiguities instead of asserting fabricated completeness.
- [x] Exercise an actual Open-Meteo request and the manual/automated CLI help. Document startup requirements, SQL/FTS behavior, daily refresh, manual recovery and the future hybrid-RAG improvement.
- [x] Request an independent review of the complete request diff and designs, fix blocking findings with regression tests and repeat review. Mark the design implemented only after actual checks pass.
