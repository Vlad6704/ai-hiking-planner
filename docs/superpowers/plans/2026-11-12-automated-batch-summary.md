# Automated Batch Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Perform implementation yourself; delegate only an explicitly authorized independent review. Steps use checkbox syntax for tracking.

**Goal:** Automatically summarize every automated CLI invocation, including failed and incomplete runs, with the primary metrics presented first.

**Architecture:** Register the requested runs before executing them, collect each run's evaluation and measured usage in memory, and aggregate only that invocation. A pure aggregation module produces a shared summary document; a presentation module writes JSON, Markdown and console output. The existing runner, per-run evaluator and trajectory format remain authoritative for individual runs.

**Tech Stack:** Python 3.11+, asyncio, standard-library dataclasses/statistics/json/pathlib/hashlib, existing pytest tooling; no new dependencies.

**Spec:** `docs/technical-design.md`, Section 11.3.2. Read Section 11.3.1 for the existing per-run fields. The design takes precedence over this plan.

## Global Constraints

- "The same contract applies to sequential and parallel execution. Manual sessions remain outside this automated scenario summary."
- "Each row below defines one metric."
- "Show this block first in both the console and Markdown batch summaries."
- "Preserve missing measurements as null, never zero."
- "Use portable relative artifact references, not local absolute paths."
- "Generated reports stay ignored by Git unless explicitly selected for publication, following the trajectory policy."
- Preserve existing CLI arguments, per-run console JSON and trajectory locations. Do not rename existing metric fields or change scenario assertions, agent prompts, manual sessions or business behavior.
- No p95/p99, monetary estimates, new failure scenarios or automatic paid LLM runs.
- No commits without a new explicit user request. Do not create implementation subagents.

## Review Focus

1. Partial token/cache usage must not become a complete-looking total; test zero, missing and mixed coverage in Tasks 1 and 2.
2. A constructor, evaluation or trajectory-write exception must not discard sibling results; test each stage in Task 4.
3. Cancellation must preserve completed records and identify unfinished/not-started runs without manufacturing trajectories; test parallel and sequential cancellation in Task 4.
4. A confirmed receipt followed by a runtime error must retain its business evidence while counting as a runtime error; test classification in Task 2.
5. Different fixture/configuration groups and unavailable Git/path metadata must not produce misleading comparisons or expose machine-local information; test grouping in Task 2 and artifacts in Task 3.

## File Map

| File | Responsibility |
|---|---|
| `app/evaluation/batch.py` (new) | Batch/run record types, comparison fingerprints and pure aggregation. |
| `app/evaluation/batch_output.py` (new) | Safe artifact serialization, Markdown/console rendering and best-effort Git context. |
| `app/evaluation/checks.py` | Additive export of token reporting coverage from existing usage callbacks. |
| `app/simulation/__main__.py` | Register cases, collect outcomes, persist progress and finalize summaries for both scheduling modes. |
| `tests/test_batch_summary.py` (new) | Deterministic aggregation and completeness tests. |
| `tests/test_batch_output.py` (new) | Artifact formatting, portability and redaction tests. |
| `tests/test_cli.py`, `tests/test_evaluation.py` | Offline CLI lifecycle tests and usage-export regression tests. |
| `.gitignore`, `README.md`, `docs/technical-design.md` | Ignore generated reports, document output and update implementation status only after verification. |

### Task 1: Expose reliable token-usage coverage

**Files:** Modify `app/evaluation/checks.py`; test `tests/test_evaluation.py`.

**Interfaces:** Keep `evaluate(run) -> dict`. Add `token_usage_reported_calls` overall and per agent, sourced from `Usage.reported`; existing `llm_call_count` supplies the denominator. Retain current input/output fields as observed values for compatibility. The batch layer determines completeness instead of assuming a non-null token count is complete.

- [ ] Write `test_evaluation_exports_token_reporting_coverage`: construct usage for two model calls with only one usage report; assert calls = 2, reported calls = 1, and existing token values are preserved. Include complete zero-token usage and no-usage cases.
- [ ] Run `uv run pytest tests/test_evaluation.py -q`; confirm the new coverage assertions fail before implementation.
- [ ] Export coverage from `evaluate` without changing the callbacks, model configuration, legacy rate flags or existing cache behavior. Count coverage overall by summing agent counters.
- [ ] Run `uv run pytest tests/test_evaluation.py tests/test_observability.py -q`; require all tests to pass.

### Task 2: Define records and aggregate one batch

**Files:** Create `app/evaluation/batch.py`, `tests/test_batch_summary.py`.

**Interfaces:** Define the following standard-library dataclasses and functions in `batch.py`:

- `RunRecord(case_id: str, scenario: str, repetition: int, context: dict, started: bool = False, run_id: str | None = None, request_id: str | None = None, report: dict | None = None, trajectory_path: Path | None = None, error: dict | None = None, events: list[dict] | None = None)`.
- `BatchRecord(batch_id: str, started_at: str, context: dict, runs: list[RunRecord], finished_at: str | None = None, wall_time_ms: int = 0, interrupted: bool = False)`.
- `fingerprint(value: object) -> str`: SHA-256 of canonical JSON, independent of dictionary order.
- `summarize_batch(batch: BatchRecord) -> dict`: JSON-compatible summary without filesystem reads or model calls.

`case_id` identifies the planned slot even if runner construction fails; it is separate from run/request IDs. Event lists are aggregation inputs only and are not copied into report artifacts.

- [ ] Write failing tests for a four-slot batch: a passed booking, an expected controlled refusal that passes, a runtime error with a confirmed receipt, and a not-started run. Assert pass rate = 2/4, booking confirmation rate = 2/4, execution counts = 1 confirmed + 1 controlled failure + 1 runtime error + 1 incomplete. Missing reports do not pass.
- [ ] Add weighted-rate tests: failed attempts 1/1 and 0/9 yield 0.1, not 0.5; cache reads 80/100 and 0/900 yield 0.08. Verify `tool.retry` counts separately from `recovery.started`/`recovery.applied`, including per-tool breakdowns.
- [ ] Add completeness tests: zero is measured, absent is null, partial usage exposes an observed subtotal and coverage while complete totals remain null. Exclude incomplete token measurements from per-run means; explicitly report the measured-run denominator. An unstarted run does not silently contribute zero usage.
- [ ] Add latency tests for values 10, 20 and 90 ms: mean = 40, median = 20, maximum = 90, sample count = 3; test passed/non-passed subsets and empty groups.
- [ ] Add repeatability tests: ignore request/reservation IDs, timestamps, wording and equipment ordering; preserve route/date/guide differences. Group only matching effective fixture/model/runtime configurations. Repeated failed trips must not count as repeated successful bookings. For this metric, require a confirmed result and a passing scenario verdict.
- [ ] Add check/error tests: absent checks are not failed checks; each check records its reporting denominator. Errors retain stable codes. Missing result and missing error classify as incomplete, not controlled refusal.
- [ ] Run `uv run pytest tests/test_batch_summary.py -q`; confirm failures before implementing the module.
- [ ] Implement the records and reducer. Return `schema_version`, identity/times/context, `incomplete`, per-slot `runs`, `overall`, `per_scenario` and `comparison_groups`. Metric entries use `value` plus `numerator`/`denominator` for rates, and reporting counts/observed subtotals where applicable. Represent business-result distributions as readable fields with counts, not opaque hash keys.
- [ ] Implement every primary, coverage and diagnostic metric in Section 11.3.2, including per-agent usage, per-tool counters and batch wall time supplied by the caller. Do not sum run latencies to obtain wall time. Keep legacy per-run metric names inside preserved evaluations only.
- [ ] Run `uv run pytest tests/test_batch_summary.py tests/test_evaluation.py -q`; require all tests to pass.

### Task 3: Write portable artifacts and primary-first presentation

**Files:** Create `app/evaluation/batch_output.py`, `tests/test_batch_output.py`; modify `.gitignore`.

**Interfaces:**

- `source_context(root: Path) -> dict`: revision and dirty flag, both null when Git is unavailable; never collect remotes or environment contents.
- `render_markdown(summary: dict) -> str` and `render_console(summary: dict) -> str`: consume Task 2's document.
- `write_batch_summary(batch: BatchRecord, directory: Path) -> tuple[Path, Path]`: call `summarize_batch`, write `summary.json` and `summary.md`, and return their paths.

- [ ] Write tests asserting primary metric rows appear first in both presentations, followed by sample size/coverage and diagnostic blocks. Each row contains one metric; input, output, cached reads, cache writes and cached-input share remain separate rows. No p95/p99 fields.
- [ ] Test JSON/Markdown agreement, null displayed as unavailable rather than zero, and per-scenario plus overall values. Show repeatability only for comparable groups, not a pooled mixed-scenario percentage.
- [ ] Test all slot references: successful and failed trajectories get links relative to the summary directory; missing files get null references with an explanation. A cross-drive Windows path that cannot be made relative must not fall back to an absolute path. Escape Markdown labels/cells.
- [ ] Test redaction with synthetic API keys/email/bearer values and absolute-path-bearing exception text. Summary errors expose stage, exception type and safe code, not raw exceptions, stack traces, prompts, full scenario fixtures or machine-local paths. Raw full contexts are fingerprints only; configuration fields are allowlisted.
- [ ] Test Git missing/non-repository cases and bounded subprocess timeout. Test valid JSON survives artifact replacement failures; write via temporary files and replacement following the existing trace-writing pattern. Surface failures rather than announcing successful publication.
- [ ] Run `uv run pytest tests/test_batch_output.py -q`; confirm failures before implementation.
- [ ] Implement the three functions above. Reuse existing `redact` where applicable, but do not rely on it to remove filesystem paths. Serialize only the allowlisted context, evaluation data, metric aggregates and portable artifact references. Avoid truncating numeric lists or dropping planned slots.
- [ ] Add `reports/` to `.gitignore`; keep published examples opt-in. Run `uv run pytest tests/test_batch_output.py tests/test_batch_summary.py -q` and `git check-ignore reports/automatic/example/summary.json`; require passing tests and an ignored report path.

### Task 4: Integrate lifecycle-safe summaries into the existing CLI

**Files:** Modify `app/simulation/__main__.py`, `tests/test_cli.py`.

**Interfaces:** Keep `async main() -> int` and existing command-line flags. Add `async run_case(record: RunRecord, settings: Settings, seed: int, output: Path, override: FailureInjection | None) -> None` as the case executor. It mutates only its own record; the orchestration layer owns batch persistence. Use Task 3's writer under `Path('reports/automatic') / batch_id`.

- [ ] Add offline tests using scripted/fake runners: `--all --parallel --runs 2` registers all slots before work starts, preserves real overlap, yields unique run/request IDs and produces one batch summary. Sequential execution produces the same accounting and aggregates.
- [ ] Add parameterized tests for scenario-load, constructor, execution, evaluation and trajectory-write exceptions. Other selected runs must finish in both scheduling modes. Preserve any available evaluation, receipt, usage and events; never invent an evaluation or trajectory reference when none exists. A write failure remains visible even when evaluation passed.
- [ ] Add cancellation tests: cancel the orchestration after one case completes. Save its completed record, mark running cases incomplete and sequential pending cases not-started, set `incomplete`, cancel and await active tasks, then propagate cancellation. Verify durable summary JSON remains readable and completed trajectories stay linked.
- [ ] Add tests for unchanged per-run JSON output, final summary location announcements, and exit code 1 for failed checks, missing reports, runtime or publication failures. Invalid CLI arguments still exit 2 without starting a batch. Interrupts retain the normal non-successful interruption behavior.
- [ ] Run `uv run pytest tests/test_cli.py -q`; confirm new assertions fail before integration. Tests must use temporary working/output directories and no LLM/network calls.
- [ ] Register a UUID batch and all scenario/repetition slots after CLI validation. Record UTC timestamps and a separate monotonic batch timer. Capture settings, scheduling, seed and effective failure settings, effective model/temperature (including provider-default null), and Git context. Do not expose service URLs or credentials.
- [ ] Fingerprint each effective loaded scenario and its source scenario/snapshot; fingerprint the mock catalog seed and record its `seed_id` from `snapshots/routes.json`. For real mode do not label that seed as the live catalog: use available catalog freshness/version metadata, or null if unavailable. Retain effective dates in context so different real-mode dates are not treated as identical fixtures. No catalog refresh just for reporting.
- [ ] Execute cases with independent exception boundaries. Preserve existing `evaluate` and `run.trace.write` behavior, and existing per-run console JSON whenever evaluation exists. Extract coverage from Task 1 and event counters from the run; record safe stage/type codes for unexpected exceptions. Do not catch `BaseException` as a normal case failure.
- [ ] Write an initial incomplete summary, update after each completed case, and finalize in an outer cleanup path on success/error/cancellation. Serialize writes in the single event loop rather than allowing workers to replace the same files concurrently. An initial publication failure must stop before paid runs begin; a later failure must not mask the original failure or discard collected siblings. Failed publication returns nonzero.
- [ ] Print Task 3's console summary after the existing per-run outputs. Record batch elapsed time independently of run timing. Preserve the current success rule and additionally fail on incomplete/error/publication conditions.
- [ ] Run `uv run pytest tests/test_cli.py tests/test_failure_controls.py tests/test_batch_summary.py tests/test_batch_output.py -q`; require all tests to pass.

### Task 5: Document and verify the complete offline workflow

**Files:** Modify `README.md`, `docs/technical-design.md`; update tests above only if integrated verification reveals a gap.

- [ ] Document that existing automatic commands now write `reports/automatic/<batch_id>/summary.json` and `summary.md`; explain the primary block, coverage/null semantics, references to all trajectories, and continued separation from manual sessions and runtime logs.
- [ ] Verify the agreed design-to-test coverage: batch identity/grouping (Tasks 2/4), all metric rows (Task 2), primary ordering/cache (Task 3), partial data/errors/interruption (Tasks 1/4), outputs/redaction/Git policy (Task 3), CLI compatibility (Task 4). No required metric may exist only as display text without an aggregation test.
- [ ] Run `uv run pytest -q` and `git diff --check`. Require a passing offline suite and no whitespace errors. Do not run the paid CLI as an incidental smoke test.
- [ ] After verification, change Section 11.3.2 status from specified/pending to implemented and document actual output behavior. Leave Section 11.3.1 and its original table unchanged.
- [ ] Review the final diff yourself for unintended agent/model/scenario changes and generated artifacts. Report changed files and verification evidence; leave all changes uncommitted. Any paid scenario batch or commit requires a separate user request.

## Execution record

Implemented in this checkout without commits or paid LLM runs. Offline tests
cover aggregate accounting, weighted rates, incomplete token/cache reporting,
receipt evidence after runtime errors, separate comparison groups, output
portability/redaction, CLI failure isolation and cancellation. An independent
review found inconsistent verdict handling, missing batch context, lost partial
cache subtotals and receipt-evidence gaps; these were corrected and regression
tests added. This plan is now a historical implementation record; Section 11.3.2
of the technical design remains authoritative.

Ruling: use the existing virtual environment interpreter directly for offline
verification because sandboxed `uv` cache operations stalled. No dependencies
were changed. Full verification results are reported in the task response.
