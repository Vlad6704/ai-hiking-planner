# Runtime Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Persist operational and asyncio socket diagnostics independently of tracing, including the two-console manual session and its background HTTP demo.

**Architecture:** A standard-library process logger owns JSON formatting, redaction, rotation and correlation. A scoped asyncio handler extracts best-effort transport context. Entrypoints and existing runtime/tool/HTTP boundaries emit operational records without storing conversation payloads or changing outcomes.

**Tech Stack:** Python 3.11+, logging/RotatingFileHandler/contextvars/asyncio, existing httpx/Uvicorn, pytest. No new dependencies.

**Spec:** [System design Section 12.0](../../technical-design.md), repository AGENTS.md.

## Global Constraints

- Logs are independent of LangSmith and trajectory JSON.
- Default repository-root logs/, LOG_DIR override, LOG_LEVEL=INFO.
- Each process owns a role/PID/start-time JSONL file; rotate at 5 MiB with three backups.
- Preserve loop type, network errors, retries, booking checks and outcomes.
- Never log bodies, human messages, prompts, credentials or authentication headers.
- Correlation and loop handlers must be scoped and restored.
- The user authorized planning followed by execution and commit; the previous approved work was separately committed first as 3ff4443.
- Execute inline in the existing feature checkout. Commit only after a fresh independent review of `git diff --cached HEAD`.

## Review Focus

1. Callback-only errors and closed sockets must log safely when no transport appears directly in the asyncio context.
2. Secrets in exception text, URL userinfo/query and nested fields must be redacted, including at DEBUG level.
3. Customer/background threads and sequential runs must keep component/correlation identities distinct.
4. Repeated setup and scoped handler restoration must not duplicate records or suppress an existing handler.
5. An error before readiness or after a successful booking must remain diagnosable without changing the business outcome.

## Files and ownership

- `app/observability/runtime_logging.py`: process setup, JSON formatter/redaction, context, uncaught exceptions.
- `app/observability/asyncio_logging.py`: scoped callback diagnostics and safe transport metadata.
- `app/observability/http_logging.py`: payload-free HTTP request/response hooks.
- Existing entrypoints, runner, tool wrapper and demo: configure/emit records at their existing boundaries.
- `tests/test_runtime_logging.py`, `tests/test_asyncio_logging.py`, `tests/test_logging_integration.py`: behavior and subprocess verification.

### Task 1: Persist safe process logs

**Interfaces:** `configure_logging(role: str, directory: Path | None = None) -> Path`; `shutdown_logging()`; `log_context(**fields)`; `log_path() -> Path | None`. Logging uses standard named loggers with `extra={'fields': {...}}`.

**Files:** Create runtime_logging.py and test_runtime_logging.py; update .gitignore and .env.example.

- [x] Write tests for parseable JSON, UTC/process/thread/component fields, uncaught exception tracebacks, repeated setup without duplicate lines, context restoration, per-process filenames, configured-secret/URL/header redaction and bounded rotating backups.
- [x] Run `uv run pytest tests/test_runtime_logging.py -q`; expect missing logger behavior failures.
- [x] Implement the process-owned handlers, safe formatter, context manager and exception hooks. Preserve unrelated handlers; restore owned hooks/handlers in shutdown used by tests.
- [x] Repeat the same tests; expect all passing. Verify an invalid LOG_LEVEL or unusable directory fails explicitly.

### Task 2: Capture asyncio callback and socket diagnostics

**Interfaces:** `capture_asyncio_errors(component: str, loop=None)` context manager; `connection_fields(transport) -> dict` returns best-effort local/peer addresses and transport identity.

**Files:** Create asyncio_logging.py and test_asyncio_logging.py.

- [x] Write tests that schedule a failing callback on a real loop, including a bound callback exposing socket metadata and a transport whose metadata access fails. Assert exception/stack/errno/callback/component are persisted; a previous custom handler is called and restored.
- [x] Run `uv run pytest tests/test_asyncio_logging.py -q`; expect missing handler failures.
- [x] Implement safe context extraction, ERROR records and custom-handler chaining. Do not change loop factories or blanket-ignore resets.
- [x] Repeat tests, including background-thread loop capture and an awaited ConnectionResetError that still reaches its caller; expect passing.

### Task 3: Integrate runtime and HTTP boundaries

**Interfaces:** HTTP hooks attach to existing `httpx.AsyncClient` instances; request/response records contain method, sanitized URL, status and elapsed duration only. Entrypoints call configure_logging once; runner uses log_context and scoped loop diagnostics.

**Files:** Create http_logging.py and test_logging_integration.py. Update simulation entrypoints/bootstrap/launcher/manual/services/runner, operator_demo.py, route_catalog/__main__.py/service.py and tools/execution.py.

- [x] Write tests for failed-tool correlation, HTTP metadata without body/query secrets, run metadata log path, runner context isolation and subprocess startup errors. Assert an actual callback inside the background HTTP server loop reaches the customer-process file.
- [x] Run `uv run pytest tests/test_logging_integration.py -q`; expect missing boundary records.
- [x] Configure all documented entrypoints, log lifecycle/connectivity/failure boundaries and HTTP hooks, and enable diagnostics on both loops. Retain the existing CLI and human-console flow.
- [x] Run integration tests plus manual/operator/CLI regressions; expect passing with unchanged domain results.

### Task 4: Document, review and commit

**Files:** Update README, design verification and this completed-plan checklist.

- [x] Document log locations, LOG_DIR/LOG_LEVEL, rotation, per-process roles, trajectory correlation and the distinction between logs/traces. Explain best-effort socket addresses and that logging does not fix remote resets.
- [x] Run `uv run pytest -q` and `git diff --check`; expect no failures or whitespace errors. Inspect actual emitted JSONL from a subprocess callback/startup smoke.
- [x] Stage only logging changes. Dispatch a fresh independent design reviewer with `git diff --cached HEAD`, current design and verification results using the repository-local review skill/template.
- [x] Verify/fix blocking findings with regression tests, repeat relevant tests and independent staged review as required by AGENTS.md.
- [x] Commit the reviewed logging implementation separately from 3ff4443 and verify final Git status.
