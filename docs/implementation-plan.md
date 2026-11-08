# Multi-Agent Hiking Trip Planning System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run and evaluate a customer request for a Picos de Europa hike from the first question through manager-approved booking and delivery of the final result to the customer.

**Architecture:** Two role-bound LangChain ReAct agents share a factory and have independent checkpointed conversations. Run-local Python components own messages, approvals, reservations, limits and delivery. A scenario supplies human responses and adapter data, while a programmatic evaluator checks the outcome against evidence from that run.

**Tech Stack:** Python 3.11+, LangChain `create_agent`, LangGraph, Pydantic v2, asyncio, httpx, YAML/JSON, LangSmith and pytest.

**Spec:** [Technical Design Document v1.0](technical-design.md). Read it alongside this plan. The repository currently contains the design and project language instructions. Paths below are relative to the repository root.

## Global Constraints

- Use English for project content. Implement exactly two operational AI agents and two human participants. Allow only Human A ↔ Agent A ↔ Agent B ↔ Human B.
- Use real LLM inference for both `real` and `mock` scenario runs. Keep identical public tool schemas across modes. Deterministic test doubles belong in automated tests.
- Keep conversation state to `messages` and `request_id`. Use independent `{request_id}:agent_a` and `{request_id}:agent_b` threads. Allocate fresh infrastructure for every run.
- Expose four planning and three operator domain tools. Bind authorization, transport metadata and critical side effects in code. Let the LLM choose questions, tools, proposals and alternatives.
- Start the matcher at `0.60` minimum score and `0.15` minimum lead, with two clarification attempts. Default to 3 technical attempts including the first, with waits of 0.5 s and 1 s.
- Start with 100 recorded steps, 20 inter-agent exchanges and a 120 s global timeout. Make these limits configurable. Use `booking:{request_id}` for one final reservation per request.
- Keep the operator HTTP demo stateless. Keep runtime records in memory. Export one analysis trajectory per run and redact sensitive data before export or transmission to LangSmith.
- Use five unique baseline cases. Execute four once and one five consecutive times under identical settings. Evaluate semantic outcomes programmatically. Defer V2 architecture changes until baseline evidence is available.

## Review Focus

1. A booking times out after the provider accepts it. Reconciliation or an idempotent resend must yield at most one distinct reservation. Exercise in Tasks 4 and 6.
2. A guide list changes or a proposal is amended after approval. A numeric choice must retain its original meaning and an old approval cannot authorize new terms. Exercise in Tasks 3 and 4.
3. A duplicate, late or cross-request reply reaches a queue. It must neither resume the wrong thread nor cause another side effect. Exercise in Task 7.
4. A fallback weather snapshot looks plausible but is stale or covers the wrong date or location. A safety decision must receive a typed failure. Exercise in Task 5.
5. Agent A submits a valid result but the customer sink fails. The trace must show failed delivery and exclude successful completion. Exercise in Tasks 9 and 10.

## File map

| Files to create | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock`, `.env.example` | Python package, locked dependencies and documented environment variables |
| `app/models/contracts.py`, `app/simulation/config.py` | Validated tool, proposal and result models, runtime settings |
| `app/observability/trace.py`, `app/observability/langsmith.py` | Local events and export, remote tracing and redaction |
| `app/humans/simulator.py`, `app/humans/approval.py` | Matching, delivery sink, presented choices and approval records |
| `app/tools/operator.py`, `app/tools/adapters/mock.py` | Trusted operator operations and per-run snapshot-backed provider |
| `app/tools/execution.py`, `app/tools/planning.py`, `app/tools/adapters/planning.py` | Retries, fallback eligibility, weather, routes and equipment |
| `app/tools/adapters/operator_http.py`, `app/operator_demo.py` | Operator HTTP client and stateless demo endpoints |
| `app/messaging/bus.py` | Envelopes, queues, pending requests and correlation |
| `app/agents/factory.py`, `app/agents/prompts.py`, `app/agents/tools.py` | Two roles, tool binding and model configuration |
| `app/simulation/scenario.py`, `app/simulation/runner.py`, `app/simulation/__main__.py` | Fixture loader, lifecycle and CLI |
| `app/evaluation/checks.py`, `app/evaluation/metrics.py` | Deterministic assertions and metrics |
| `catalogs/`, `snapshots/`, `scenarios/`, `tests/` | Sourced real catalogs, recorded fixtures, baseline definitions and automated tests |
| `README.md`, `docs/evaluation-summary.md`, `trajectories/{scenario_id}/{run_id}.json` | Reproduction instructions, measured findings and run evidence |

Use `uv` for the lockfile and commands below. For each test cycle, write the named test before the implementation, observe the stated failure, then run the same command after the change. Add package initializers as needed for `python -m app.simulation`. At each commit step stage only the task's files. Initialize Git at execution time if delivering via Git and the checkout still lacks a repository.

### Task 1 — Establish the shared contracts

**Files:** Create `pyproject.toml`, `uv.lock`, `app/models/contracts.py`, `app/simulation/config.py`, `tests/test_contracts.py`.

**Interfaces:** Produce `Settings`, `TripResult`, `Proposal`, `ToolError(code, message, retryable)`, and generic `ToolResult[T](status, data, source, mode, error)`. Define these input → data models for the public tools. Field units belong in their schemas.

| Tool | Input → data | Required coverage from design §6 |
|---|---|---|
| `get_weather_forecast` | `WeatherQuery → Forecast` | Place or coordinates, date range → time, temperature, precipitation probability and amount, wind, data timestamp and provider |
| `search_hiking_routes` | `RouteQuery → list[RouteSummary]` | Location, difficulty, maximum duration, optional distance and elevation limits → ID, name, difficulty, km, hours, elevation gain |
| `get_route_details` | `RouteLookup → RouteDetails` | Route ID → summary fields, description, route restrictions and source reference |
| `get_hiking_equipment` | `GearQuery → GearAdvice` | Route, weather, duration, optional owned items → required, recommended, missing and reasons |
| `check_guide_availability` | `GuideQuery → list[Guide]` | Date, route, optional group size → stable ID, name, availability and route qualifications |
| `check_equipment_inventory` | `InventoryQuery → Inventory` | Date, items, optional quantities → per-item availability, rentable quantities and unavailable items |
| `create_tour_reservation` | `BookingRequest → Reservation` | Request ID, idempotency key, route, date, guide, equipment quantities, approval reference → reservation ID, status, confirmed terms and creation time |

- [ ] Configure Python `>=3.11`, Pydantic v2, PyYAML and the pytest development dependency. Run `uv sync`.
- [ ] Write `test_trip_result_conditions` and `test_tool_contracts`. Use `pytest.raises(ValidationError)` for a confirmed result missing each required ID/date, a failed result with a blank reason, an invalid ISO date and a quantity below one. Assert `ToolResult[list[Guide]](..., status="success", data=[]).data == []` with valid source/mode. Assert `Settings()` gives `(3, 100, 20, 120)` for attempts, steps, exchanges and seconds.
- [ ] Run `uv run pytest tests/test_contracts.py -q`. Expect collection failure on the missing project models.
- [ ] Implement the table and §11.1's eight `TripResult` fields, including `equipment_items: list[str]` and nullable `failure_reason`. Use UUID-validated request IDs serialized as strings. Define `Proposal(route_id, date, guide_id, equipment)` with positive quantities and stable normalized item ordering. Support `success|error|degraded`, require a typed error for error results, and validate environment mode and positive limits. Keep record existence checks for Task 9.
- [ ] Repeat the test command. Expect all parameterized cases to pass. Commit `feat: define validated trip and tool contracts`.

### Task 2 — Record causal, redacted trajectories

**Files:** Create `app/observability/trace.py`, `tests/test_trace.py`. Consume Task 1's serializable models.

**Interfaces:** Produce `TraceRecorder.emit(kind, actor, data, *, recipient=None, caused_by=None, operation_id=None) -> Event` and `TraceRecorder.write(directory: Path, result: RunReport) -> Path`. Define `RunReport` here with nullable trip result, execution outcome, validation status/checks, metrics and optional error summary. The runner supplies start/end metadata and the evaluator supplies checks/metrics.

- [ ] Write `test_concurrent_events_and_redaction` using two asyncio producers. Assert `seqs == list(range(1, len(events) + 1))`, `child.caused_by == parent.event_id`, `set(document) == {"metadata", "events", "result"}` and `secret not in serialized`. Include nested credential headers, sensitive human text and oversized tool output.
- [ ] Run `uv run pytest tests/test_trace.py -q` and observe the missing recorder.
- [ ] Implement an append operation without an intervening await, per-run UUIDs, timezone-aware timestamps, monotonic duration and the exact metadata/event fields in §12.2. Validate the event payloads listed there. Preserve machine-checkable IDs and outcomes when capping large values. Apply configurable sensitive-text redaction consistently to messages and exported result evidence. Write indented UTF-8 JSON atomically at `{directory}/{scenario_id}/{run_id}.json`.
- [ ] Repeat the test command. Open the generated test trajectory and verify the child references the expected parent across interleaved operations. Commit `feat: record causal simulation trajectories`.

### Task 3 — Simulate human decisions and bind approvals

**Files:** Create `app/humans/simulator.py`, `app/humans/approval.py`, `tests/test_humans.py`.

**Interfaces:** Produce `HumanSimulator.answer(agent_id, interaction: HumanInteraction) -> HumanReply` and `async deliver(agent_id, message_id, text) -> None` (returns on sink acceptance). `HumanInteraction` carries ID, kind, question and optional ordered options/proposal. `HumanReply` carries text, matched intents, scores and interaction ID. `ApprovalRegistry.record(request_id, interaction, reply)` records trusted Human B decisions. `require(request_id, approval_ref, proposal) -> None` enforces an active exact match or raises a typed denial.

- [ ] Write `test_match_intents`, `test_unmatched_limit` and `test_manager_selection_and_approval`. Assert combined experience/equipment answers occur in question order, ties clarify, two clarification replies precede `human_response_unmatched`, and option `"2"` resolves to the second presented stable ID even if the catalog reorders. Assert an out-of-range selection, a customer “approved”, an ambiguous reply, rejection and a changed proposal cannot authorize booking.
- [ ] Run `uv run pytest tests/test_humans.py -q`. Expect missing simulator and registry.
- [ ] Normalize case, punctuation and stop words, score each intent by the weighted proportion of its keyword group matched (best group wins), and apply the two thresholds per independently recognizable question clause. Keep unmatched counters per participant and reset after a match. Use separate question, choice, approval, rejection and alternative fixtures. Bind each interaction to its assigned human in runtime context. Preserve the displayed options, validate IDs against availability and bind explicit approval to the request and normalized proposal. Return the approval reference to B only after recording the decision. Invalidate superseded or rejected approvals.
- [ ] Repeat the test command. Expect matching, routing and authorization tests to pass. Commit `feat: simulate human choices and record proposal approvals`.

### Task 4 — Protect operator operations and booking retries

**Files:** Create `app/tools/operator.py`, `app/tools/adapters/mock.py`, `tests/test_booking.py`.

**Interfaces:** Define `OperatorProvider.guides(GuideQuery)`, `.inventory(InventoryQuery)`, `.reserve(BookingRequest)` as async methods returning the corresponding Task 1 data or raising a typed provider error. `OperatorTools` exposes the three §6.4 tool names as async methods returning the corresponding `ToolResult`. Inject provider, run identity, approval registry and a single-attempt executor initially. Task 5 adds the retry policy at that boundary.

- [ ] Write `test_booking_authority`, `test_concurrent_duplicate` and `test_uncertain_outcome`. Assert `provider.reserve_calls == 0` for forged request/key, missing or stale approval, unavailable guide and insufficient stock. For simultaneous identical approved calls assert `first.data == second.data` and `provider.created_count == 1`. After a lost response, assert the next identical attempt uses the same key, a changed payload yields `idempotency_conflict`, and an unconfirmed outcome never appears as confirmed.
- [ ] Run `uv run pytest tests/test_booking.py -q` and observe the missing trusted tool layer.
- [ ] Implement per-run normalized payload fingerprints, per-key serialization, prior results and uncertain status. Check the trusted request identity, key and matching approval before dispatch. Check available guide qualifications and rentable quantities for this route/date before the first creation. Return a cached identical success without rechecking stock consumed by that reservation. Reject a changed payload for an in-flight, uncertain or successful key. Perform status lookup by key where supported, otherwise retry only with the provider's idempotency guarantee. Return an explicit uncertain error if confirmation cannot be established.
- [ ] Implement deterministic in-process guide/inventory reads and stateful mock booking. Keep the provider-side effect separate from the runtime cache so the test can lose the reply after creation. Record approval reference and actual creation evidence for validation. Empty guide lists are successful business responses.
- [ ] Repeat the test command and verify exactly one created reservation under contention. Commit `feat: enforce approved idempotent reservations`.

### Task 5 — Implement planning tools and bounded recovery

**Files:** Create `app/tools/execution.py`, `app/tools/planning.py`, `app/tools/adapters/planning.py`, `catalogs/routes.json`, `catalogs/equipment.json`, `tests/test_planning.py`, `tests/test_recovery.py`. Extend `app/tools/adapters/mock.py`, `app/tools/operator.py`, `pyproject.toml` and lockfile.

**Interfaces:** `PlanningTools` exposes the four §6.3 tool names as async methods, each accepting its Task 1 input and returning its `ToolResult`. Implement `async execute(operation, call_once, *, policy, fallback=None) -> ToolResult` for both tool sets. Bind run clock, trace recorder, seeded failure script and async sleep as dependencies. Use httpx for real weather.

- [ ] Write `test_route_and_gear_rules` for location/difficulty/time/distance/elevation boundaries, unknown route, day versus multi-day kit and owned gear. Write `test_weather_contract` for provider units, dates, wind, malformed data and unsupported dates via an HTTP transport stub. Assert real and mock success/error results validate against the same models.
- [ ] Write `test_retry_schedule` and `test_fallback_eligibility`. For timeout, 503, success assert `attempts == 3` and `sleeps == [0.5, 1.0]`. For bad input assert `attempts == 1`. After exhaustion assert `result.status == "degraded"` only for a matching, approved, fresh read snapshot. Parameterize wrong place, uncovered date, future-issued, expired and absent snapshots as typed failures. Assert booking never falls back to a snapshot.
- [ ] Run `uv run pytest tests/test_planning.py tests/test_recovery.py -q` and observe missing tools/policy.
- [ ] Normalize Open-Meteo responses, compile the route catalog from official Picos de Europa material, and derive equipment rules from Australian Hiker guidance including its Multi-Day Gear List. Retain source references, retrieval dates and units. Use recorded provider-shaped snapshots in mock mode. Apply identical normalization and business rules in both modes.
- [ ] Implement per-tool timeouts, transient-only backoff (network interruption, timeout, 429, 503), failure/latency injection, trace attempt numbers and recovery events. Define weather fallback eligibility using approved provider, place, forecast coverage and a configurable maximum age (initial policy choice: 6 h). Compare against the fixture observation clock in mock runs and current UTC in real runs. Allowlist read-only fallback explicitly. Surface business outcomes to the deciding agent and leave human escalation to its role. Wrap booking retries inside Task 4's protected operation.
- [ ] Repeat the test command plus `uv run pytest tests/test_booking.py -q`. Expect passing contracts, retries and lost-response protection. Commit `feat: add planning adapters and bounded recovery`.

### Task 6 — Run the operator contract over HTTP

**Files:** Create `app/operator_demo.py`, `app/tools/adapters/operator_http.py`, `tests/test_operator_http.py`. Extend `app/simulation/config.py`, `pyproject.toml` and lockfile.

**Interfaces:** `HttpOperatorProvider(base_url, client)` implements Task 4's protocol. Expose `create_demo_app(availability) -> FastAPI` and a `python -m app.operator_demo` entrypoint using uvicorn on localhost. Use three JSON endpoints: `POST /guides`, `POST /inventory`, `POST /reservations`. Requests and responses use the Task 1 models.

- [ ] Write `test_operator_http_contract` with httpx's in-process ASGI transport. Compare normalized results from the demo and equivalent mocks, excluding generated timestamps and source/mode labels. Assert repeated identical POSTs yield one stable reservation ID derived from the request ID and inventory reads stay fixed. Assert `real` mode with no operator URL raises a configuration error. Verify timeout, 503 and malformed response mapping and that an unauthorized booking makes zero HTTP requests.
- [ ] Run `uv run pytest tests/test_operator_http.py -q` and observe the missing integration.
- [ ] Implement fixed guide/inventory responses and synthetic confirmations. Keep approval checks, idempotency bookkeeping and retries in the existing trusted layers. Have the adapter set request deadlines and normalize responses. Pass mock runs directly to in-process providers. Add explicit endpoint validation for real runs.
- [ ] Repeat the test command and run `uv run python -m app.operator_demo --help` to check startup instructions. Commit `feat: demonstrate operator integrations over HTTP`.

### Task 7 — Route asynchronous messages and close pending requests

**Files:** Create `app/messaging/bus.py`, `tests/test_bus.py`. Consume Task 2's recorder.

**Interfaces:** `async MessageBus.send(sender, content, kind, *, in_reply_to=None) -> Envelope`, `async receive(agent_id) -> Envelope`, `expire(now) -> list[PendingRequest]`. The trusted invocation context supplies the original envelope for replies. A notification creates no pending request. The bus owns the peer mapping, two asyncio queues, clock and deadlines.

- [ ] Write `test_request_reply` and `test_invalid_replies_do_not_wake_agent`. Assert enqueue succeeds before consumption, a response correlates to the request's message ID, requester/recipient match, and valid reply completion occurs once. Parameterize duplicate ID, unknown correlation, wrong sender, wrong request ID, expired and already-closed request. Assert `resumptions == 0` for each invalid envelope. Check expiry with an injected clock.
- [ ] Run `uv run pytest tests/test_bus.py -q`. Expect the bus import to fail.
- [ ] Implement the eight §4.2 envelope fields, generated UUIDs and timestamps, request/response/notification/error semantics and a run-local seen-ID set. Record pending status, deadline, identities and correlation before exposing a request to its consumer. Validate a reply before waking the requester. Keep terminal pending entries for late-message detection, trace ignored input and expose outstanding requests to the runner. Make the response timeout configurable (initial choice: 30 s).
- [ ] Repeat the test command. Expect two-way request/reply, expiry and duplicate suppression to pass. Commit `feat: correlate asynchronous agent messages`.

### Task 8 — Assemble two role-bound ReAct agents

**Files:** Create `app/agents/factory.py`, `app/agents/prompts.py`, `app/agents/tools.py`, `tests/test_agents.py`, `.env.example`. Extend `pyproject.toml` and lockfile with compatible LangChain, LangGraph, LangSmith and provider integration versions. Read the installed LangChain and LangGraph fundamentals skills when implementing framework code.

**Interfaces:** `build_agent(agent_id, instructions, tools, model, checkpointer, dependencies)` returns a compiled `create_agent` graph. Supply the framework's messages-based agent state with a `request_id` extension. Bind `ask_human(interaction)`, `send_to_agent(content, kind)`, and A-only `submit_trip_result(result: TripResult, final_message: str)`. Inject the runner's terminal callback behind the latter. A test callback suffices for this task.

- [ ] Write `test_bound_tools_and_thread_isolation` with a scripted tool-calling chat model. Assert the exact planning/operator tool sets plus each role's infrastructure tools. Assert identical public names, descriptions and JSON schemas across modes. Put a private sentinel in A's history and assert it never appears in B's messages. Assert agent input excludes scenario ID, hidden answers and expected assertions.
- [ ] Write `test_interrupt_resume_and_send`. Assert the human tool yields an actual interrupt containing its question/interaction ID, `Command(resume=answer)` continues the same thread, and replay around an interrupt creates one recorded decision. Assert the peer send returns a queue receipt without a graph interrupt. Exercise A's submission with a recording callback.
- [ ] Run `uv run pytest tests/test_agents.py -q` and observe the missing agent factory.
- [ ] Build both agents from the factory with the same configurable model and in-memory checkpointer. Select one tool-calling third-party model through explicit provider/model settings. Record its exact identifier and sampling parameters at baseline execution. Bind actor, request, approval authority, message correlation and booking key from runtime context. Use stable interaction IDs across resume. Expose only the information required to use each tool.
- [ ] Write role-specific instructions from §§3.2–3.3. A gathers missing customer facts before proposing, consults the customer on material changes, and submits a customer-facing result. B checks resources, presents stable options, asks the manager, handles rejection and sends the operational outcome to A. Use actual tool observations for decisions and escalation. Keep normal tool selection autonomous.
- [ ] Repeat the test command. Expect evidence of independent state, role authorization and genuine graph interrupt/resume. Commit `feat: assemble two role-bound ReAct agents`.

### Task 9 — Drive one request through delivery or bounded failure

**Files:** Create `app/simulation/scenario.py`, `app/simulation/runner.py`, `tests/test_runner.py`. Consume Tasks 1–8.

**Interfaces:** `load_scenario(path: Path) -> Scenario` validates §10.1 fields and resolves snapshot references. `async SimulationRunner.run(scenario: Scenario, settings: Settings) -> RunEvidence` returns the result, terminal outcome/reason, actual tool and human records, trace, counters and timing. `async finalize(result: TripResult, final_message: str) -> None` is the callback bound only to A. Task 10 evaluates this evidence before trace export.

- [ ] Write `test_customer_receives_final_result` with the real graphs, scripted model, actual queues and in-memory sink. Assert a request-sending turn ending leaves the run active. For a confirmed trip assert the sink received A's message, `delivered.data["message_kind"] == "final_result"`, `delivered.data["trip_result"] == result.model_dump(mode="json")` and `completed.caused_by == delivered.event_id`. For a business failure assert a meaningful delivered reason and a normally completed lifecycle with `TripResult.status == "failed"`.
- [ ] Write `test_reject_invalid_completion` for unknown IDs, wrong request, unconfirmed booking, missing approval, pending work, mismatched customer message and concurrent duplicate submissions. Write `test_runner_termination` for a broken sink, idle deadlock, model/tool stall, unmatched human, peer deadline, exchange and step limits. Assert a failed infrastructure run records its specific reason, delivery state and one terminal event, and leaves no live consumer tasks.
- [ ] Run `uv run pytest tests/test_runner.py -q` and observe the missing runner.
- [ ] Create fresh request/run IDs, graphs, checkpoint threads, buses, simulator, providers, registries and recorder. Send Human A's opening message to A. Start one serial consumer per agent. Track queued work, active graph turns, interrupts, deadlines and pending replies. Resume human interrupts with the assigned simulator's answer in the same thread. Keep processing other ready work. Treat quiescence without a viable wake-up as deadlock. Cancel and await tasks, close clients and release run-local state on all exits.
- [ ] Count recorded events as logical steps and each accepted peer transmission as one exchange (explicit interpretation of §9.5). Reserve space for terminal recording within the step cap. Before sending a final message reserve room for both delivery and completion. Enforce global time with a monotonic deadline covering model calls, tools and waits. A rejection or an operator alternative returns control to the agent within those limits.
- [ ] Serialize finalization. Check actual reservation/approval and proposal records, unresolved work and conditional result fields. Give A a deterministic final-message format: for confirmation include the exact route ID, date, guide ID, reservation reference and equipment items from the approved result; for failure use its reason. Validate the complete text against the format before delivery. `deliver` accepts a stable message ID. Upon acceptance record the text, ID, serialized result, actor/recipient and causal link to finalization, then record completion referencing the delivery event. On delivery error record the reason and fail the run.
- [ ] Repeat the test command. Run `uv run pytest -q` and verify no cross-run state survives two invocations. Commit `feat: coordinate simulation lifecycle and customer delivery`.

### Task 10 — Evaluate evidence and integrate LangSmith

**Files:** Create `app/evaluation/checks.py`, `app/evaluation/metrics.py`, `app/observability/langsmith.py`, `tests/test_evaluation.py`, `tests/test_observability.py`. Extend `app/simulation/runner.py` and `.env.example`.

**Interfaces:** `evaluate(scenario: Scenario, evidence: RunEvidence) -> RunReport` and `metrics(evidence: RunEvidence) -> dict`. Add `async run_and_export(scenario, settings, directory) -> tuple[RunReport, Path]` in the runner module. It executes one run, evaluates even a partial failure and writes one trajectory. Capture a nullable LangSmith trace ID in metadata.

- [ ] Write `test_evaluator_rejects_corrupted_evidence`. Independently change the route constraints, weather/date suitability, guide qualification, missing gear, approval order, booking count, correlation, recipient, retry count, recovery record, limit or delivery parent. Assert the corresponding named check fails even with a valid-looking final result. Assert an allowed alternative passes and a legitimate infrastructure failure records delivery as absent. Use causal references for concurrent operations.
- [ ] Write `test_metric_denominators` with two failed attempts in four, one recovered case of two, and one unmatched question of four. Assert `tool_failure_rate == 0.5`, `recovery_success_rate == 0.5`, `human_matching_failure_rate == 0.25`; use null for an undefined rate. Verify per-agent and per-run input/output tokens and call counts on known callback data.
- [ ] Write `test_trace_export_on_failure` and `test_remote_trace_redaction`. Assert each run yields one JSON document with §12.2 payloads, including on timeout. With an in-memory tracing client verify nested model/tool spans, custom bus/HITL/runner events, linked trace ID and redaction of secrets and sensitive human content **before** transmission. Disabled tracing must still export local evidence.
- [ ] Run `uv run pytest tests/test_evaluation.py tests/test_observability.py -q` and observe the missing evaluators.
- [ ] Implement output, business and execution checks from §11.2. Count distinct successful creations separately from attempts. Compare returned IDs to records and actual event ancestry. Compute all nine §11.3 metrics, including elapsed latency, peer messages, task success (confirmed outcome) and scenario pass (all expected checks pass). Record unavailable provider usage as unknown. Aggregate counts and denominators over runs. Enable standard framework tracing via configuration plus custom spans and a sanitized payload boundary. Preserve the local trajectory when remote tracing is disabled.
- [ ] Repeat the test command and inspect a failed trajectory for a specific check name, expected/actual evidence and terminal reason. Commit `feat: evaluate simulation evidence and trace execution`.

### Task 11 — Ship the five scenarios and runnable CLI

**Files:** Create `scenarios/{happy_path,bad_weather,guide_unavailable,hitl_rejection,external_service_failure}.yaml` (five files), `snapshots/{weather,routes,equipment,guides,inventory}.json`, `app/simulation/__main__.py`, `tests/test_scenarios.py`, `tests/test_cli.py`, `README.md`. Extend `app/simulation/scenario.py` to validate cross-file references.

**Interfaces:** `python -m app.simulation (--scenario ID | --all) --mode {mock,real} [--runs N] [--seed S]`. Run repetitions sequentially with fresh runtime state and identical seed/settings. Print status, structured result, check failures, metrics, trajectory path and trace reference when enabled. Return nonzero for configuration errors, failed validation or infrastructure failure.

| Fixture | Observable assertion |
|---|---|
| `happy_path` | Easy beginner route of at most four hours, sufficient gear, second of two presented guides, approval and exactly one booking |
| `bad_weather` | Original date unsafe, safer date confirmed with the customer, reservation on that approved alternative |
| `guide_unavailable` | No guides on the first date, B communicates the issue, revised date has an available qualified guide |
| `hitl_rejection` | Initial equipment shortage, manager rejection, revised feasible equipment arrangement, new approval precedes booking |
| `external_service_failure` | Three weather failures, eligible recorded fallback, safe proposal and successful recovery |

- [ ] Write `test_five_scenario_contracts` and a parameterized `test_scenario_end_to_end` using scripted chat models in tests only. Assert each row's distinct behavior against actual evidence, including HITL and final delivery. Add a test-only variant removing the eligible weather fallback and assert explicit failure with zero bookings. Validate all referenced dates, guide IDs, quantities, expected alternatives and snapshot timestamps before any model call.
- [ ] Write `test_cli_modes_and_runs`. Assert `--all` invokes five distinct scenarios once, `--scenario happy_path --runs 5 --seed 42` uses five independent IDs with the same seed, and a missing endpoint exits nonzero. Verify the normal CLI path selects a real chat model in both modes, using a spy on model construction.
- [ ] Run `uv run pytest tests/test_scenarios.py tests/test_cli.py -q` and observe missing fixtures/entrypoint.
- [ ] Author the five short initial requests, minimal role-specific answers, failure sequences, snapshot selections and expected rules. Set a fixed scenario observation time for mock freshness checks. In real mode support an initial request with dates relative to the run date for a live forecast and use a compatible demo availability preset. Limit hidden case data to its owning component. Implement argument parsing, discovery, sequential execution and exit handling around `run_and_export`.
- [ ] Document `uv sync`, credential/model configuration, LangSmith opt-in, the architecture and allowed communication, exact CLI commands in §14, and `uv run pytest`. Include a two-terminal real-mode example starting `uv run python -m app.operator_demo` and running `uv run python -m app.simulation --scenario happy_path --mode real` with the endpoint configured. Explain catalog provenance, weather horizon, synthetic operator service, in-memory durability and model variability.
- [ ] Repeat both test modules, then run `uv run pytest -q` and `uv run python -m app.simulation --help`. Expect the suite to pass offline and CLI help to match the README. Commit `feat: expose five reproducible hiking scenarios`.

### Task 12 — Collect the assignment evidence

**Files:** Create `docs/evaluation-summary.md`. Generate `trajectories/{scenario_id}/{run_id}.json` via the CLI. Link the representative success and five repeated results from the summary and `README.md`. Consume Tasks 10–11. This is a measured acceptance run.

- [ ] Run `uv run pytest -q` from the locked environment. Record the source revision or archive identifier, model/provider and sampling settings, seed, limits, fixture version and tool mode. Verify model credentials for the measured batch. Record whether LangSmith tracing is enabled.
- [ ] Run `uv run python -m app.simulation --scenario happy_path --mode mock --runs 5 --seed 42` once. Retain all five consecutive trajectories including failures. Check distinct run/request IDs, identical settings and scenario assertions for each. Compare semantic acceptance, route/date/guide and unique booking count across runs.
- [ ] Run `uv run python -m app.simulation --scenario ID --mode mock --seed 42` once for each of `bad_weather`, `guide_unavailable`, `hitl_rejection` and `external_service_failure`, substituting each ID. Verify **nine measured runs across five unique cases**. Keep exploratory real-mode checks outside this count.
- [ ] Start the local operator demo and run the documented real-mode command with an in-horizon forecast and configured endpoint. Inspect the real-mode trajectory for provider provenance and the synthetic confirmation. Inspect a LangSmith trace for model, token usage when provided, tool calls and nested spans. Record the actual outcome and any configuration or provider limitation.
- [ ] In the summary, list the five consecutive outcomes, all nine assertion results, aggregate metrics and a successful trajectory path. Inspect at least one recovery and the final delivery chain. Diagnose failed runs using event/trace IDs. If a fix changes code, fixtures, prompts or settings, label the old batch and collect a complete fresh batch for the new version. Report observed variability and justify each proposed V2 improvement with a measured bottleneck.
- [ ] Verify the source package (repository or ZIP) contains design, README, fixtures, snapshots, tests, representative successful JSON and the evaluation summary with reachable evidence links. Confirm the README commands work from a clean install and the shared artifacts are redacted. Commit `docs: report baseline evaluation and trace findings`.

## Acceptance cross-check

| Acceptance criteria in design §15 | Verification |
|---|---|
| Agent count, generic architecture, state isolation, autonomous tools and allowed peers | Task 8 inspects both compiled agents. Tasks 9–12 exercise actual routing and capture tool decisions. |
| Seven validated tools, real/mock parity, retries, fallback and controlled failure | Tasks 1, 4–6 and 11 compare contracts and inject technical failures. Task 12 exercises the configured real adapters. |
| Interrupt/resume, predefined human responses, selection, rejection, business and HITL recovery | Tasks 3 and 8 verify the mechanism. Task 11 proves the revised booking flow. |
| Queue transport, correlation and finite termination | Tasks 7 and 9 exercise lost, duplicate and late replies, limits, cleanup and deadlock. |
| Approval and idempotency | Task 4 counts actual creations and rejects mismatched terms. Task 10 checks independent booking evidence. |
| Structured output and customer delivery before completion | Tasks 1, 9 and 10 verify conditional fields, sink acceptance and the causal delivery link. |
| Five baseline cases, five consecutive executions, programmatic evaluation | Tasks 10–12 validate the five fixtures and record all nine measured executions. |
| LangSmith, JSON for every run, architecture, setup and limitations | Tasks 2, 10–12 verify exported evidence, trace configuration, README commands and measured recommendations. |
