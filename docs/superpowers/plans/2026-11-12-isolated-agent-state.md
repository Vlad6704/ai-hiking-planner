# Isolated Agent State and Structured Messaging Implementation Plan

> **For agentic workers:** When implementation is authorized, use the repository-local executing-plans or subagent-driven-development skill task by task. Track the steps below. This document authorizes no implementation, independent review or commit by itself.

**Goal:** Keep each agent's business facts in its own checkpointed state and exchange every peer-owned fact through a validated message.

**Architecture:** Retain two LangChain `create_agent` graphs and their private threads. A role-local driver handles its graph's checkpointed inbox/outbox and transport acknowledgements. The runner schedules drivers and resources without providing shared business facts to tools.

**Tech Stack:** Existing Python 3.11+, LangChain, LangGraph, Pydantic v2, asyncio, pytest and InMemorySaver.

**Spec:** [Technical design](../../technical-design.md), especially §§3.4, 4, 5.3, 6.5, 9.6 and the result contract. The design takes precedence over this plan.

## Global Constraints

- Messages are the only communication channel between agents, including their tools.
- Each agent owns serializable business facts and can read only its own state.
- Keep in-memory checkpointing for V1 and allow checkpointer injection. A database and complete process-restart recovery are future work.
- Preserve exact route variant IDs, short reservation IDs, approval enforcement, safety checks and external idempotency semantics.
- Preserve the seven domain tools, parallel read batches, console/browser human interactions and mock/real provider contracts.
- Customer-facing failure text remains generic. Detailed evidence stays in logs and trajectories.
- Project content is English. Commits require an explicit user request.

## Review Focus

1. A dropped or text-only message must not allow the receiver to obtain the missing fact from shared memory. Tested in Tasks 2, 4 and 5.
2. Dispatch can succeed before its acknowledgement is checkpointed. Re-dispatch must reuse message identity and avoid repeated business effects. Tested in Tasks 2 and 3.
3. A resumed human/tool node can execute again. A reply must apply to its exact offer once, and a booking must preserve its original idempotency key. Tested in Tasks 3 and 4.
4. Concurrent read tools can update the same state collection. Completed sibling facts must survive merging and resume. Tested in Tasks 1 and 3.
5. B may have attempted a reservation while A lacks the outcome. Terminal delivery must preserve uncertainty without inspecting B. Tested in Tasks 4 and 5.

## File Map

| File | Responsibility |
|---|---|
| Create `app/models/messages.py` | Typed peer payloads and envelope validation |
| Create `app/agents/state.py` | Role-specific state, serializable records and merge reducers |
| Create `app/agents/driver.py` | One agent's graph invocation, checkpointed receive and dispatch |
| Create `app/agents/middleware.py` | State preparation before side-effect tool execution |
| Modify `app/agents/factory.py`, `app/agents/tools.py` | Inject private context and use state updates |
| Modify `app/messaging/bus.py` | Transport of validated stable envelopes |
| Modify `app/humans/approval.py`, `app/tools/operator.py` | Validate B-owned records rather than keep private business registries |
| Modify `app/simulation/runner.py` | Resource orchestration, transport/lifecycle and final observation |
| Modify `app/simulation/manual.py`, `app/simulation/web.py` | Human input delivery and status projection from the owning agent |
| Modify `app/evaluation/checks.py`, `app/observability/trace.py` | Passive evidence and evaluation with no feedback channel |
| Modify `README.md` | Explain state ownership, messages and recovery limits |

The work is a coupled migration. The intermediate contracts can be tested in
isolation; release the system only after Tasks 1–6 pass together. Preserve
historical exported trajectories. Existing completed plans remain historical.

### Task 1. Define message contracts and private agent state

**Files:** Create `app/models/messages.py`, `app/agents/state.py`, `tests/test_agent_state.py`; modify `app/agents/factory.py`; reuse domain models from `app/models/contracts.py`.

**Interfaces:**

- `PeerEnvelope` contains message/request/sender/recipient/correlation IDs, timestamp, transport kind, explanatory content and a discriminated `payload`.
- Payload kinds are `trip_request`, `trip_offer`, `customer_decision`, `availability_result`, `reservation_progress`, `reservation_outcome`, and `operational_failure`.
- Trip requests carry exact requested terms and relevant typed route, forecast and equipment facts from A. Reuse existing models rather than parallel string representations.
- Offers carry full `Proposal`; the envelope message ID identifies the immutable offer. Decisions carry offer message ID, exact terms, accepted/declined and the original customer interaction/reply reference.
- Reservation progress carries operation/idempotency identity, exact terms and pending/uncertain status. Outcomes carry confirmed/failed/uncertain status, decision/approval references and a validated `Reservation` only when confirmed.
- `PlannerState(AgentState)` and `OperatorState(AgentState)` implement §3.4. Inbox/outbox records and facts retain their source IDs. B alone stores approval and provider operation records. A stores only received outcomes.
- Use keyed, idempotent merge reducers for fact and message collections. Distinct tool call/message IDs merge; replay of an identical record is a no-op; conflicting content under an existing immutable ID is rejected.

- [x] Write `tests/test_agent_state.py` for payload round-trip, invalid sender/payload combinations, missing exact terms, invalid reservation ID, state isolation, conflicting IDs and concurrent reducer updates. Assert that serializing one state contains no peer state or live runtime object.
- [x] Run `uv run pytest tests/test_agent_state.py -q` and observe failures for the missing contracts.
- [x] Implement the contracts and schemas. Retain two private graph threads and select the schema by agent role.
- [x] Rerun the test command. Expect all tests to pass.

### Task 2. Persist receive and dispatch through the owning driver

**Files:** Create `app/agents/driver.py`, `tests/test_agent_dispatch.py`; modify `app/messaging/bus.py`, `tests/test_bus.py`.

**Interfaces:**

- `MessageBus.send_envelope(envelope: PeerEnvelope, *, caused_by: str | None = None) -> str` queues an already identified envelope and returns its ID. Preserve routing, correlation, exchange limits and reply deadlines.
- `AgentDriver(actor, graph, config, transport)` owns one graph/thread. `receive(envelope: PeerEnvelope) -> None` validates and checkpoints the inbox plus the recipient's facts before model continuation. `flush_outbox() -> None` reads only its own pending records, dispatches, then checkpoints acknowledgement.
- Only a newly checkpointed outbox record may be sent. Persist an outgoing response before releasing its incoming request. A queued transport item is acknowledged as received only after the receiver's checkpoint succeeds.
- The bus retains transport bookkeeping. Business deduplication lives in each state, so a fresh bus can accept replay with the same IDs. The runner never constructs business payloads from shared facts.

- [x] Write tests for send-before-ack failure, duplicate receive, rejected sender/request ID, acknowledgement checkpoint failure, correlation expiry and two concurrent sessions. Assert one business application despite repeated transport delivery.
- [x] Run `uv run pytest tests/test_agent_dispatch.py tests/test_bus.py -q`; confirm new dispatch cases fail.
- [x] Implement stable-ID transport and driver dispatch/receive boundaries. Keep queued data immutable to prevent later mutation of sender state from changing receiver facts.
- [x] Rerun the command. Expect all cases to pass, including re-instantiating a driver with the same in-memory checkpointer and fresh transport resources.

### Task 3. Move tool observations and human interactions into private state

**Files:** Modify `app/agents/tools.py`, `app/agents/factory.py`, `app/agents/driver.py`, `app/humans/approval.py`, `app/simulation/runner.py`, `app/simulation/manual.py`, `app/simulation/web.py`; create `tests/test_message_only_isolation.py`; adapt `tests/test_parallel_tools.py`, `tests/test_customer_information.py` and relevant human tests.

**Interfaces:**

- Replace `bind_tools(run, actor)` with `bind_tools(actor, context)` where context provides role-local provider clients, clock, transport dispatch access and trace emission, but no runner, peer driver or peer checkpoint.
- Tools read `ToolRuntime.state` and return `Command(update=...)` with the appropriate tool message. Observation facts include the validated query, complete result, tool-call ID and date. Keep compact model-facing route projections.
- Human interruption carries a stable interaction ID and exact local proposal. The owning driver records the interaction and actual reply in its checkpoint. Human adapters only collect/deliver text and choices.
- Guide selection/approval validators become functions over B's checkpointed records. `reply_with_customer_decision` reads A's local offer/reply, records its interpretation and stages a decision payload. B obtains consent solely by receiving that payload.
- New incoming offers invalidate A's old offer-bound decision. B's changed terms invalidate old approvals. Replaying an answered interaction must not consume another fixture answer or ask the human twice.

- [x] Write tests for checkpointed parallel weather/routes and guide/inventory results, human interrupt/resume after driver recreation, stale offers, duplicate replies, and clarification without consent. A tool must continue with only its owner's saved state and reconstructed clients.
- [x] Run `uv run pytest tests/test_message_only_isolation.py tests/test_parallel_tools.py tests/test_substitution_safeguards.py -q` and identify the current runner dependencies.
- [x] Migrate observations, guide selection, approvals and customer decisions. Adapt mock human replies and browser/console pending questions to use the same local interaction records.
- [x] Rerun the command plus `uv run pytest tests/test_customer_information.py tests/test_humans.py tests/test_web_manual.py tests/test_manual.py -q`. Preserve information replies, Enter-to-send, presets, date notice and failure controls.

### Task 4. Enforce booking through B's state and publish its outcome

**Files:** Create `app/agents/middleware.py`, `tests/test_agent_booking_state.py`; modify `app/tools/operator.py`, `app/agents/tools.py`, `app/agents/driver.py`, `app/agents/factory.py`; adapt `tests/test_booking.py`, `tests/test_reservation_identity.py`.

**Interfaces:**

- `reserve_from_state(state: OperatorState, request: BookingRequest, provider) -> Reservation` validates B's local approval, received consent/planning facts and B's resource checks. It has no access to A's state or global `observed` collection.
- Eliminate authoritative `OperatorTools.terms/result` and `ApprovalRegistry.records` storage. Retain provider adapters and service-side idempotency behavior. All caller-side attempt identity, terms and outcome are B state fields.
- B-local `after_model` middleware prepares a stable booking intent and `reservation_progress` outbox entry before a selected booking tool executes. Use the supported `create_agent(interrupt_before=["tools"])` execution boundary: B's driver checkpoints/dispatches its pending outbox and resumes the already selected tools without a new model call. This internal scheduling boundary carries no peer payload through a human `interrupt()`.
- Dispatch and checkpoint progress acknowledgement before starting the provider side effect. After it, checkpoint B's receipt or uncertainty and stage the corresponding outcome message. Never fabricate a receipt on replay.
- A later tool-node replay finds the existing B attempt. A saved confirmed outcome is returned without another booking. An unresolved attempt is reconciled using the same idempotency key where supported; otherwise retain uncertainty and stop automatic booking retries.

- [x] Write tests with no A state reference available to B. Booking without a received decision, with wrong terms or missing local manager approval must fail. Valid received evidence must allow booking.
- [x] Test a pause before booking, lost progress acknowledgement, successful side effect before outcome checkpoint, provider timeout after accepting a booking, duplicate outcome and a provider without safe idempotent retry. Assert one logical reservation and truthful uncertainty.
- [x] Run `uv run pytest tests/test_agent_booking_state.py tests/test_booking.py tests/test_reservation_identity.py -q` and confirm the missing state-based flow fails.
- [x] Implement the staged booking boundary. Preserve one-tool-at-a-time booking and permit existing independent read batches. Validate private-state checkpointing at the static tool boundary with the installed LangChain API.
- [x] Rerun the command. Recreate B's driver between phases using the same saver and verify stable request/message/idempotency identity.

### Task 5. Finalize from A's received facts and remove shared channels

**Files:** Modify `app/simulation/runner.py`, `app/simulation/outcome.py`, `app/simulation/manual.py`, `app/simulation/web.py`, `app/evaluation/checks.py`, `app/observability/trace.py`; adapt `tests/test_graceful_completion.py`, `tests/test_evaluation.py`, `tests/test_logging_integration.py`; create `tests/test_message_only_isolation.py`.

**Interfaces:**

- `submit_trip_result` validates against A's checkpointed received outcome, binds IDs from that record and renders the canonical text. It cannot inspect B's provider, graph or approval state.
- Remove shared business attributes from the runner: `approvals`, `selected`, `observed`, `inventory_checks`, `original_proposal`, `rejected_proposals`, `substitution` and the authoritative operator wrapper. Public final output is a projection of A's saved result.
- Keep runner resource/lifecycle state and per-role drivers. Passive evaluation derives observations, approval order and delivery from trace evidence, rather than live business attributes that tools can also read.
- Runtime safety delivery delegates to A's local driver. After stopping agent work, checkpoint queued outcomes through A's normal receive path. Missing outcome after pending booking yields the existing generic uncertainty notice. A can render confirmation only from a received confirmed outcome.

- [x] Test that dropping a confirmation message prevents A from reading its reservation ID even when B has a receipt. Dropping a decision must block B despite A's local acceptance. Reject text-only operational facts. Mutating one state must not mutate the other.
- [x] Test runtime stops before/after progress, while outcome is queued, after confirmed receipt reception, and on delivery failure. Preserve one generic final delivery and finite terminal allowance.
- [x] Run `uv run pytest tests/test_message_only_isolation.py tests/test_graceful_completion.py tests/test_evaluation.py -q` and observe failures against the old shared implementation.
- [x] Cut over the runner, finalization, evaluation and manual adapters. Keep existing historical JSON artifacts readable; new events include typed payload and source IDs. Historical evidence can be evaluated without becoming runtime state.
- [x] Rerun the command and `uv run pytest tests/test_web_manual.py tests/test_manual.py tests/test_trace.py tests/test_logging_integration.py -q`. Runtime failure remains distinct from successful agent completion.

### Task 6. Prove the migration through public entry points

**Files:** Modify `tests/test_integration.py`, `tests/test_cli.py`, `README.md`, `docs/evaluation-summary.md`; complete this plan's checkboxes only from actual evidence.

- [x] Update scripted agents to emit typed requests/offers/decisions/outcomes. Exercise all six scenarios through the real graph, including refusal and manager-requested changes. Assert B's receipt and A's received receipt agree only after message delivery.
- [x] Run `uv run pytest -q`. Expect a green suite; record the actual count and any pre-existing warnings. Old tests must assert private-state/message behavior rather than reintroduce shared convenience fields.
- [x] Run `uv run --env-file .env python -m app.simulation --scenario happy_path --runs 5 --seed 42 --peer-timeout 90 --timeout 300`. Record all five sequential results, including failures.
- [x] Run `uv run --env-file .env python -m app.simulation --all --parallel --mode mock --peer-timeout 90 --timeout 300`. Inspect proposals, approvals and outcomes crossing message boundaries with independent per-run state.
- [x] Repeat permanent inventory failure for happy_path, equipment_shortage and guide_unavailable. Check generic delivery, no fabricated receipt and actual normal/runtime termination. Exercise uncertain provider outcome with deterministic provider doubles; do not create real external bookings for this check.
- [x] Update README ownership and resume limitations, and append measured evidence to the evaluation summary. Clearly distinguish checkpoint resume inside a live test runtime from persistent process-restart recovery. Preserve observed failures in the report.

## Completion Evidence Required

The implementing agent must provide passing commands, the message/state
isolation and resume test results, the fresh sequential/parallel model reports,
and a list of any remaining shared business dependencies. Completion requires
that list to be empty. Persistent database deployment, production broker setup
and arbitrary historical trajectory replay are outside this migration.


## Completed verification

The complete migrated suite passed 364 tests with 13 existing dependency
warnings. Focused tests cover real LangChain middleware pauses, parallel fact
merging, checkpoint reconstruction, message deduplication, lost provider
responses, generic terminal notices and passive evaluation.

Normal model verification used Luna: all six scenarios passed concurrently
(`logs/isolated-state-model-0ecffa58-7c42-409f-953c-0b643e98f735.jsonl`), followed
by five consecutive happy_path passes
(`logs/isolated-state-sequential-80c6f562-4e40-4e8b-b964-42e0ac417cd4.jsonl`).
These normal runs preceded the final replay-protection refinements. The full
364-test suite was run after those refinements.

Final outage verification ran happy_path, equipment_shortage and
 guide_unavailable concurrently with inventory timeout probability 1. Each
returned a failed trip with no runtime error, no booking and exactly one generic
customer message. Reports are in
`logs/isolated-state-outage-24f47b83-4229-40d0-afed-63c496ba2716.jsonl`.

Implementation details settled during execution:

- Booking validation is `AgentContext.prepare_booking/reserve` over a scoped
  checkpoint snapshot rather than the originally sketched standalone function.
- Typed customer decisions include refreshed planning facts when terms change.
  Availability results include typed guide/inventory observations.
- The driver pauses before and after tools to checkpoint dispatch and preserve
  return-direct peer turn boundaries. Parallel read tools remain parallel.
- B checkpoints executing status before provider execution. A one-use role-local
  execution capability permits that live continuation. A recreated driver cannot
  repeat a non-idempotent operation from executing status; it preserves uncertainty.
- Legacy approval/provider business registries were removed. Historical tests
  were migrated to explicit private state and message contracts.
- Checkpoint/resume coverage is in test_message_only_isolation.py,
  test_agent_dispatch.py and test_parallel_tools.py. Tests were verified through
  focused groups and the full suite, rather than every originally sketched
  command grouping. The existing tests were extended without a separate
  test_agent_checkpointing.py file.

No remaining shared authoritative business dependencies were found in the active
agent/runner/evaluator paths. Runtime resources and passive observations remain
outside business state by design. V1 still uses in-memory queues and savers;
this migration does not claim process-restart durability. No commit was created.
