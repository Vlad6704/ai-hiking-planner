# Persistent Route Catalog and Content Search — Technical Design

**Status:** Implemented and independently reviewed on November 9, 2026.
**Parent design:** [System technical design](technical-design.md).

This document contains the detailed design for route discovery, storage,
refresh and retrieval. The parent design links here and remains authoritative
for shared system architecture and constraints. Maintain feature-specific
requirements here as the feature evolves; this is a design document, not an
implementation plan.

The previously agreed live Open-Meteo work remains described by the weather
tool contract in the parent design and is separate from this route feature.

## Scope

- Discover the complete set of route entries linked from the official Picos
  de Europa itinerary index, including short-distance, long-distance and
  high-mountain categories. Do not hard-code a subset of route IDs.
- Fetch route pages, extract complete route content and normalize searchable
  measurements. Report discovered entries that cannot be processed.
- Persist the catalog in SQLite and search it through structured read-only
  SQL and SQLite FTS5 full-text queries.
- Support an explicit refresh command and at most one automatic refresh
  attempt per calendar day, triggered by the first catalog request.
- Preserve deterministic mock-mode fixtures without network access. Both modes
  use the complete SQLite retrieval path; only live source refresh is disabled
  in mock mode.

Source index: [Official Picos de Europa itinerary catalog](https://www.miteco.gob.es/es/parques-nacionales-oapn/red-parques-nacionales/parques-nacionales/picos-europa/guia-visitante/itinerarios.html).

## Storage

Use Python's standard-library `sqlite3` with a configurable database path,
defaulting to `data/routes.sqlite3`. The generated database is local runtime
data, excluded from Git. Version the schema and migrations in the repository.

### `routes`

One record represents one source route page.

- Stable public `route_id`, internal primary key, `source_id` and original
  source route code. Identify a route independently of its mutable name.
- Name, region/location, category and `source_language`.
- Complete description, walking directions, points of interest and caution
  notes, with the original source wording retained as external data.
- Source URL and optional map/profile URLs.
- `created_at`: first insertion into the local database.
- `updated_at`: last change to the normalized business content.
- `last_checked_at`: last successful retrieval/validation, even if unchanged.
- `last_seen_at`: last appearance in a successfully retrieved source index.
- `content_hash`, `parser_version`, optional source ETag and Last-Modified.
- Active/inactive state, parse status and optional last error. A discovered
  but unreadable route remains represented instead of silently disappearing.

All stored timestamps use UTC. Source publication/modification dates, when
available, are separate from local creation/update timestamps.

### `route_variants`

One route may have a long loop, short loop, one-way or return variant.
Each variant has a stable `variant_id` and a foreign key to its parent route.

- Variant key/name and layout: circular, linear, out-and-back or unknown.
- `distance_m`, `duration_minutes`, `ascent_m` and `descent_m` as numeric fields.
- Normalized difficulty and original difficulty wording.
- Variant-specific description/constraints when the source distinguishes them.
- Original metric text for inspection and an active/parse state.

Unknown measurements are NULL, not zero or a guessed value. Never combine
distance from one variant with duration or difficulty from another. An
ambiguous page remains available with its source text and parse issue; only
validated variants participate in filters that require those measurements.

Search results identify both route and variant. The agreed design must carry
the selected variant identity through subsequent details and trip planning,
so a later step cannot silently switch to a different version of the route.

For compatibility with existing booking contracts, the public `route_id` in
real-mode tool results is the stable variant ID (for example,
`PR-PNPE-2:long`). `source_route_id` retains the parent source ID and
`variant_id` is returned explicitly. Details accept the variant ID; a parent
ID with multiple variants returns `variant_required` instead of choosing one.
Mock fixtures retain their existing IDs. Numeric fields that are unknown
remain nullable in tool results and cannot satisfy a supplied numeric bound.

The search API retains kilometre/hour argument names (`min_km`, `max_km`,
`min_hours`, `max_hours`) and converts them to stored metres/minutes. It adds
optional ascent/descent bounds, `keywords`, `keyword_match` (`all` by default,
or `any`), `prefix` (false by default), `sort`, `limit` and `offset`. Explicit
null pagination/matching options use the same defaults as omitted options.

### `catalog_state` and `catalog_refresh_runs`

Keep the latest automatic-attempt date, successful-refresh timestamp,
refresh ownership/lease and last outcome in catalog state.

Record each refresh separately with its ID, trigger, start/finish timestamps,
outcome (complete/partial/failed), discovered/parsed/added/changed/unchanged/
inactive/error counts and per-route error details. Distinguish index discovery
failure from individual page failures.

### `routes_fts`

Use an FTS5 index for route name, description, walking directions, points of
interest and caution notes. Keep numeric measurements in ordinary indexed
columns on variants. Update route content, variants and the search index in
the same database transaction.

## Change detection

Compute SHA-256 over canonical normalized content: identifying source fields,
name, full descriptive content, constraints and all variant measurements and
difficulty values. Sort stable collections and normalize insignificant
whitespace before hashing. Exclude retrieval timestamps and unrelated page
navigation, advertisements and cookie banners.

- New route: insert and index it.
- Same hash: preserve business content and `updated_at`; update check metadata.
- Changed hash: update content and variants, replace the corresponding search
  index entries and advance `updated_at`.
- Parser-version change: reprocess the source even if HTTP cache validators
  suggest that its HTML is unchanged.

## Refresh behavior

Manual entrypoint:

```sh
uv run python -m app.route_catalog refresh
```

An explicit command attempts a refresh regardless of today's automatic
attempt. The first real-mode catalog request each day triggers a refresh
using the calendar date in Europe/Warsaw. Record the attempt even if it fails,
so every subsequent search does not retry a broken source. Manual refresh
remains available to recover sooner.

Fetch with bounded concurrency, deadlines and retries. Acquire refresh
ownership across processes, but do not hold a SQLite write transaction while
waiting for HTTP. Publish validated changes in a short transaction so readers
observe a consistent catalog.

Preserve previous valid records when individual pages fail. Return and trace
partial/stale status explicitly. Mark missing source routes inactive only
after a complete, validated refresh; an empty/unparseable index or partial
refresh must not deactivate the catalog. Retain historical records rather
than deleting them.

Before treating a shrinking index as complete, require a closed HTML document,
check that missing records do not still have links under changed labels, and
reject a loss of more than 20 percent of the previously active route count.
Suspicious discovery produces a failed refresh and retains previous data.
This conservative guard can also retain routes after a genuine large source
reorganization until the source adapter is inspected.

If refresh fails and usable data exists, queries may use it with explicit
freshness information. If no usable catalog exists, return a typed error.

## Search tools

Retain `search_hiking_routes` as the agent-facing search tool, backed by the
database. Retain `get_route_details` for full content by stable route/variant
identity. The importer and SQL query implementation are separate components.

The catalog service checks freshness before retrieval using its own writer
connection. The query wrapper opens a separate SQLite read-only connection
(`mode=ro`, plus `PRAGMA query_only=ON`) and only builds parameterized SELECTs.
The LLM supplies structured arguments rather than arbitrary SQL.

All search arguments are optional. They cover location, difficulty,
minimum/maximum distance, duration, ascent/descent, keywords, all/any keyword
matching, allowlisted sort order, bounded limit and offset. Apply only
explicitly supplied filters; an omitted or null filter imposes no restriction.

- An empty argument object returns the first page of active, searchable
  catalog variants without user-supplied filters.
- Default pagination is `limit=20`, `offset=0`, with a maximum limit of 100.
- Without keywords, omit FTS MATCH entirely and use stable route/variant ID
  ordering unless another supported sort order is supplied.
- Empty or whitespace-only keywords are equivalent to omitted keywords.
  Keyword matching controls have no effect when no keywords are supplied.
- When keywords are supplied, default sorting is relevance followed by
  stable route/variant IDs to resolve ties.
- Validate each supplied bound and reject contradictory minimum/maximum
  pairs. Optional arguments must not silently ignore invalid supplied values.

For content search:

Agent-facing tool content uses a compact projection of the database result.
Search returns only exact variant ID, name, difficulty, distance, duration,
ascent/descent and a short match excerpt when keywords were supplied. Keep
all filters and existing pagination semantics. The selected route's details
return full description, directions, points of interest, cautions and source,
without repeating these fields in an additional full_text aggregate.
The planner must retrieve details before preparing an operational proposal.
Choose a candidate using the summaries and customer preferences first. Retrieve
another candidate's details when needed to resolve suitability or a requested
comparison, rather than expanding every search result. Equipment advice is
computed for the proposed route/date.
Retain complete normalized records in SQLite and original tool results in
trajectory events under the existing redaction/size limits. Runtime observed
results also retain their original form for validation. Errors and degraded
status remain visible to the model.

- Use FTS5 MATCH for lexical keyword/phrase matching, combined with numeric
  filters through SQL AND conditions.
- Escape keywords as literal terms/phrases and bound query size. Do not
  expose unvalidated SQL identifiers or an arbitrary FTS expression.
- Use Unicode-aware, case-insensitive tokenization with Latin accent
  normalization. Support controlled prefix queries for word endings.
- Rank matching routes using FTS5/BM25 and return short source excerpts that
  explain matches. Full details remain available through the details tool.
- Disclose that a match in a route page is evidence of a textual mention;
  shared page text does not prove that every variant contains that feature.
- Preserve freshness, source URL and content identity in the full result
  recorded in the trajectory; expose source in selected-route details and
  degraded status to the model.

For example, a waterfall preference may become the source-language keyword
`cascada`, combined with an easy-difficulty filter and a four-hour limit.
This is an illustrative query, not a claim that a particular route mentions
a waterfall.

FTS5 does not translate queries or infer unmentioned meanings. Source pages
are primarily Spanish, so the existing planning agent should form keywords
in the recorded source language and expand alternatives when appropriate.
Preserve original source content; keep authored code, prompts, logs, schema
names and documentation in English. Automatic translation is not required
for this initial importer.

## Future content-search improvement

The initial full-text search is a lightweight retrieval layer that the
existing agent can use to answer content-based preferences. A desirable
future improvement is hybrid RAG: retain lexical FTS5/BM25 retrieval, add
semantic embedding retrieval, combine their results and ground answers in
retrieved source excerpts while retaining structured SQL filters. This can
improve synonym, intent and multilingual matching beyond literal keywords.
The current work does not require an embedding service or vector database.

## Integration and verification

- Keep the normalized source snapshot in `snapshots/routes.json` (seed version
  and identity plus source records). The initial seed captures the 31 routes
  and 50 variants already imported on November 9, 2026; this is a fixed dataset,
  not a claim about today's source contents.
- Each mock run publishes the seed into its own temporary SQLite database with
  the production schema and FTS index. Use the scenario clock for check dates
  and freshness; clean up the database when the run ends, including cancellation.
  Ignore `ROUTE_CATALOG_DB` in mock mode and make no source HTTP requests.
- Use the same catalog service and store for both modes. Disable refresh for a
  seeded service, including explicit refresh attempts. Use the same validated
  `RouteDetails` fields for search and details, including instructions, points
  of interest, full text and parser warnings. Search may omit full content.
- Remove the separate hand-written JSON route-search implementation. Preserve
  exact variant IDs through mock guide qualifications, booking and evaluation;
  do not replace them with their parent source route ID.
- Align the demo operator's accepted route identities with discovered,
  validated variants so newly searchable routes can complete the demo flow.
- Add fixture-backed parser and temporary-database tests for route discovery,
  variants, unit normalization, empty/partial search arguments, keyword
  retrieval/ranking, numeric filters,
  hash-driven updates, unchanged timestamps, atomic indexing, refresh
  concurrency, partial failures, inactive records and read-only enforcement.
- Separately verify the real source index/pages and Open-Meteo over HTTP.
- Agree this feature design before changing project code. Keep its details
  here and retain the reference in the parent design. Update README commands
  alongside implementation, and prepare an implementation plan for this
  larger change after design agreement. Completed plans remain historical
  records rather than specifications for current behavior.

References:

- [SQLite FTS5](https://www.sqlite.org/fts5.html)
- [SQLite read-only URI](https://www.sqlite.org/uri.html)
- [SQLite query-only setting](https://www.sqlite.org/pragma.html#pragma_query_only)

## Verified implementation

The live official index and all 31 discovered route pages were imported into
50 variants on November 9, 2026. Seven variant durations remain NULL because
the source does not establish an unambiguous matching segment or direction.
Other unestablished measurements also remain NULL. A second full refresh
reported 31 unchanged records and preserved their update timestamps.

An actual Open-Meteo HTTPS request, catalog keyword/numeric searches, variant
details and command help were exercised. The offline suite passed 118 tests,
including approved HTTP-demo booking with the selected variant identity and
terminal-delivery scheduling regressions. A fresh independent review passed
after blocking findings were fixed and verified.
