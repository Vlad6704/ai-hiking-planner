# Agent Systems Engineer — Technical Design Document

**Project:** Multi-Agent Hiking Trip Planning System  
**Version:** 1.0 — Initial Design  
**Date:** November 8, 2026  
**Status:** V1 architecture agreed; implementation details subject to validation  
**Target:** Anadea Agent Systems Engineer Technical Assignment

---

# 1. Overview

## 1.1 Purpose

Design and implement a small multi-agent system that assists customers in planning hiking trips to Picos de Europa, Spain.

The system contains exactly **two operational AI agents and two human participants**. Each AI agent communicates with its assigned human and with the other agent.

The implementation prioritizes:

- Autonomous agent decision-making
- Reliable agent-to-agent communication
- Human-in-the-loop interactions
- Robust tool execution and error recovery
- Reproducible simulation scenarios
- Observability and deterministic evaluation

The initial implementation will use a **ReAct-based architecture**. More sophisticated orchestration will be considered after measuring the baseline.

## 1.2 Design Principles

1. **Keep V1 simple.** Use standard agent implementations rather than prematurely introducing complex workflows.
2. **Separate responsibilities.** Agents handle reasoning, while infrastructure handles communication, execution control and reliability.
3. **Make the environment reproducible.** Fixed scenarios and mock service snapshots enable repeatable tests.
4. **Keep agents environment-agnostic.** The same agent logic must work in both simulated and real environments.
5. **Enforce critical constraints in code.** Safety, authorization, idempotency and booking approval cannot depend exclusively on LLM prompts.
6. **Measure before optimizing.** Use LangSmith and programmatic evaluation to identify improvements for V2.

## 1.3 Scope

V1 includes two independent agents, seven domain tools, agent-to-agent messaging, simulated human interactions, runtime orchestration, retries and recovery, idempotent reservations, tracing, and programmatic evaluation.

The following are outside V1 scope:

- Graphical user interface
- Production-grade distributed messaging infrastructure
- Multi-instance deployment
- Persistent production database
- LLM-as-Judge evaluation
- Full trajectory replay engine
- Advanced planning or supervisor-agent architecture

---

# 2. System Architecture

## 2.1 Participants

| Participant | Role | Responsibilities |
|---|---|---|
| Human A | Customer / hiker | Provides preferences, constraints, experience and equipment information |
| Agent A | Travel Planning Assistant | Gathers requirements, recommends routes and dates, prepares trip proposals |
| Agent B | Tour Operator Assistant | Checks operational availability, coordinates approvals and creates reservations |
| Human B | Tour manager | Selects guides, approves/rejects proposals and resolves escalated issues |

Communication restrictions:

- Human A ↔ Agent A
- Agent A ↔ Agent B
- Agent B ↔ Human B
- No direct Human A ↔ Agent B or Human B ↔ Agent A communication
- No direct Human A ↔ Human B communication within the system

## 2.2 High-Level Architecture

**Human A Simulator ↔ Agent A ↔ Message Bus ↔ Agent B ↔ Human B Simulator**

Supporting components:

| Component | Responsibility |
|---|---|
| Agent Factory | Creates agents with role-specific instructions and tools |
| LangGraph Checkpointer | Maintains independent agent conversation states |
| Message Bus | Routes asynchronous messages between agents |
| Human Simulator | Responds to human interaction requests |
| Environment Adapters | Provide real or mocked external tools |
| Simulation Runner | Initializes and manages scenario execution |
| Trace Recorder | Generates human-readable JSON trajectories |
| LangSmith | Captures LLM and tool execution traces |
| Evaluator | Validates structured results against scenario expectations |

## 2.3 Technology Stack

| Area | Technology |
|---|---|
| Language | Python 3.11+ |
| Agent framework | LangChain `create_agent`, built on LangGraph |
| Agent pattern | ReAct |
| State persistence | LangGraph Checkpointer |
| LLM provider | Configurable third-party provider |
| Data validation | Pydantic v2 |
| Concurrency | asyncio |
| Messaging | asyncio.Queue |
| HTTP integrations | httpx |
| Observability | LangSmith |
| Testing | pytest |
| Configuration | YAML, environment variables |
| Scenario fixtures | YAML / JSON |
| Trajectory export | JSON |

The specific LLM model will be selected during implementation. The same model configuration must be used when comparing repeated baseline runs.

---

# 3. Agent Architecture

## 3.1 Generic ReAct Agent

Both agents share the same underlying architecture.

The Agent Factory accepts:

- Agent identifier
- System instructions
- Tool definitions
- LLM configuration
- Checkpointer
- Runtime dependencies

The generic execution loop follows:

**Receive input → LLM reasoning → Tool selection → Tool execution → Observation → Repeat or finish**

The LLM independently determines which available tool to invoke and when.

No fixed sequence of domain tool calls is imposed in V1.

## 3.2 Agent A — Travel Planning Assistant

### Responsibilities

Agent A is responsible for:

1. Understanding customer preferences.
2. Gathering missing information through Human A interactions.
3. Obtaining weather forecasts.
4. Finding and evaluating hiking routes.
5. Recommending appropriate equipment.
6. Selecting a suitable trip proposal.
7. Contacting Agent B when sufficient customer information has been collected.
8. Handling operational alternatives suggested by Agent B.
9. Returning the final structured trip result.

### Decision policy

The system prompt will instruct Agent A to contact Agent B **only after it has resolved the necessary questions with Human A and has sufficient information to prepare a meaningful proposal**.

This decision remains with the LLM.

Required information may include:

- Preferred trip dates or acceptable date range
- Hiking experience
- Physical limitations relevant to route selection
- Preferred route duration and difficulty
- Available equipment
- Additional preferences or restrictions

The exact list can be adjusted by scenario and system instructions.

### Domain Tools

| Tool | Description |
|---|---|
| `get_weather_forecast` | Retrieve weather forecasts |
| `search_hiking_routes` | Find routes matching constraints |
| `get_route_details` | Retrieve detailed route information |
| `get_hiking_equipment` | Retrieve equipment recommendations |

Shared infrastructure tools:

- `ask_human`
- `send_to_agent`

A structured completion mechanism will be used to produce the final `TripResult`.

## 3.3 Agent B — Tour Operator Assistant

### Responsibilities

Agent B is responsible for:

1. Receiving trip proposals from Agent A.
2. Checking guide availability.
3. Checking equipment availability.
4. Presenting operational options to Human B.
5. Receiving guide selections and approval decisions.
6. Handling rejected proposals and escalations.
7. Creating reservations only after valid approval.
8. Returning the operational result to Agent A.

### Domain Tools

| Tool | Description |
|---|---|
| `check_guide_availability` | Find available guides |
| `check_equipment_inventory` | Check equipment availability |
| `create_tour_reservation` | Create an idempotent reservation |

Shared infrastructure tools:

- `ask_human`
- `send_to_agent`

## 3.4 Agent State

V1 uses a minimal state architecture.

The base agent state extends LangGraph `MessagesState` with:

| Field | Type | Description |
|---|---|---|
| `messages` | Message collection | Agent-specific conversation history and tool interactions |
| `request_id` | UUID string | Identifier for the trip-planning request |

Each agent has an independent LangGraph thread.

Thread identifiers:

- `{request_id}:agent_a`
- `{request_id}:agent_b`

An agent cannot access the other agent's private conversation history.

### State ownership

Business information initially remains in the message history.

V1 will not maintain a separate continuously synchronized business state containing route proposals, weather results, guide availability and equipment information.

However, critical operational facts must be stored by the appropriate infrastructure component:

- Processed idempotency keys
- Reservation records
- HITL approval records
- Outstanding agent-to-agent requests
- Simulation lifecycle status

These records are not part of the LLM's conversational memory.

### Checkpointing

A LangGraph checkpointer maintains conversation state across invocations and human interruptions.

V1 may use an in-memory checkpointer for the test runtime.

Persistence across process restarts is not guaranteed in this configuration.

A persistent checkpointer is a possible future improvement.

---

# 4. Agent-to-Agent Communication

## 4.1 Communication Pattern

Communication uses an **asynchronous Request-Reply pattern over an in-memory Message Bus**.

The Message Bus maintains separate queues:

- `agent_a_queue`
- `agent_b_queue`

Each agent has an independent consumer loop that awaits incoming messages.

A successful send means the message has been queued, not that the receiving agent has processed it.

## 4.2 Message Envelope

The transport layer attaches the following metadata:

| Field | Type | Description |
|---|---|---|
| `message_id` | UUID | Unique message identifier |
| `request_id` | UUID | Common trip-planning request identifier |
| `sender` | Agent ID | Sending agent |
| `recipient` | Agent ID | Receiving agent |
| `correlation_id` | UUID / null | Links responses to requests |
| `type` | Enum | `request`, `response`, `notification` or `error` |
| `content` | String / structured payload | Message content |
| `timestamp` | ISO 8601 | Creation timestamp |

The Message Bus is responsible for metadata and routing.

Agents should not be required to generate message IDs or manage transport-level correlation manually.

## 4.3 Sending Messages

Agents communicate through the shared `send_to_agent` tool.

For example, Agent A may request:

"Please check guide and equipment availability for the proposed trip."

The tool publishes the message into Agent B's queue.

Agent B receives the message and starts or continues its ReAct execution using its existing thread.

## 4.4 Reply Handling

Agent B sends the result through the same communication mechanism.

The runtime uses the correlation identifier to associate the response with the original request.

Agent A is then resumed through a new input in its existing thread.

**Agent-to-agent communication does not use LangGraph `interrupt()`.**

## 4.5 Pending Requests

The orchestration layer maintains a registry of pending inter-agent requests.

For each request it tracks:

- Requesting agent
- Receiving agent
- Message ID
- Correlation ID
- Waiting status
- Deadline
- Completion status

After sending a request, Agent A may finish its current execution turn while the overall trip-planning process remains active.

The runtime must not interpret the end of that turn as final task completion.

## 4.6 Timeouts and Duplicates

The communication layer must handle:

- Missing responses
- Unexpected responses
- Duplicate message IDs
- Messages arriving after the request was closed

Duplicate messages should not trigger duplicate side-effecting operations.

A default agent-response timeout will be configurable.

---

# 5. Human Interaction and HITL

## 5.1 Unified Interaction Mechanism

Both agents use the same `ask_human` tool.

It supports:

- Ordinary questions
- Clarifications
- Confirmation requests
- Selecting one option among several
- Approve/reject decisions

The interaction uses LangGraph:

1. Agent invokes `ask_human`.
2. Tool calls `interrupt()`.
3. Graph execution is suspended.
4. Simulation Runner receives the interrupt.
5. Human Simulator generates the predetermined response.
6. Runner resumes the graph using `Command(resume=answer)`.

The same mechanism can later be connected to a real user interface without changing the agent's business tools.

## 5.2 Human Simulator

The Human Simulator does not generate responses through an LLM in V1.

Instead, each scenario defines a fixed collection of question-and-answer patterns.

Example scenario data:

| Intent | Keywords | Response |
|---|---|---|
| Hiking experience | experience, beginner, hiking before | "I'm a beginner." |
| Preferred duration | hours, duration, how long | "Around four hours." |
| Equipment owned | equipment, boots, backpack | "I have boots and a backpack." |
| Guide selection | choose, select, guide | "2" |
| Booking approval | approve, confirm, booking | "Approved." |

### Keyword Matching

Proposed matching algorithm:

1. Normalize question text.
2. Convert to lowercase.
3. Remove punctuation.
4. Tokenize and remove common stop words.
5. Compare against configured keyword groups.
6. Calculate match scores.
7. Select the highest-scoring supported intent.
8. Return its configured response.

Suggested initial scoring:

- Score range: 0–1
- Minimum acceptable score: 0.60
- Minimum lead over the second candidate: 0.15

These thresholds are **proposed defaults**, not validated values. They will be adjusted after testing.

### Multiple Questions

If an agent asks multiple recognizable questions in one message, the simulator should identify multiple intents and combine their predefined answers into a natural response.

For example:

"How experienced are you, and what equipment do you own?"

Response:

"I'm a beginner. I have hiking boots and a backpack."

The combined response must remain consistent with the scenario.

### Unrecognized Questions

If no acceptable match is found:

1. Return a neutral clarification, for example: "Could you clarify what information you need?"
2. Track unmatched attempts.
3. After a configurable number of repeated failures, terminate the affected scenario with `human_response_unmatched`.

Default: two clarification attempts.

### Future Alternative

If keyword matching proves unreliable, an LLM-based matching component may replace the matcher.

This would be an environment-level improvement, not a change to the operational agents.

## 5.3 Human B Approval and Selection

Human B can:

- Approve a proposed booking
- Reject a proposed booking
- Select a guide by option number
- Request an alternative
- Resolve escalated decisions

For example:

Agent B: "Two guides are available: 1. Guide A, 2. Guide B. Which one should we book?"

Human B Simulator: "2"

The numeric response must map to the options presented in that interaction, using a stable ordering.

The system must validate the selected guide against actual available-guide records before booking.

### Approval Enforcement

`create_tour_reservation` must verify that a valid Human B approval exists for the selected proposal.

The booking adapter must reject unauthorized booking requests even if the LLM attempts the call.

Approval decisions are stored in a runtime approval registry indexed by `request_id`, with the relevant proposal parameters.

---

# 6. External Tool Architecture

## 6.1 Adapter Pattern

Every domain tool supports two execution modes:

- `real`
- `mock`

Both modes implement the same interface.

The LLM receives identical tool names, descriptions, argument schemas and normalized result schemas regardless of mode.

Execution mode is selected through runtime configuration and is not part of the agent's reasoning.

## 6.2 Common Tool Result Contract

Every tool adapter returns a validated result or a typed error.

Recommended common response fields:

| Field | Description |
|---|---|
| `status` | `success`, `error` or `degraded` |
| `data` | Tool-specific structured result |
| `source` | Provider or fixture identifier |
| `mode` | `real` or `mock` |
| `error` | Error code and message when applicable |

Operational metadata such as latency, attempts and trace identifiers is captured by the tool wrapper.

## 6.3 Agent A Tool Contracts

### `get_weather_forecast`

**Input:** location or coordinates, date/date range.

**Output:**
- Forecast date/time
- Temperature
- Precipitation probability
- Precipitation amount
- Wind conditions
- Data timestamp
- Provider metadata

**Real source:** Open-Meteo API or another configured forecast provider.

**Mock source:** Recorded weather-response snapshots.

**Possible errors:** timeout, service unavailable, invalid location, unsupported forecast date, malformed response.

### `search_hiking_routes`

**Input:**
- Difficulty preference
- Maximum duration
- Optional maximum distance
- Optional elevation constraints
- Location

**Output:** list of candidate routes containing route ID, name, difficulty, distance, estimated duration and elevation gain.

**Real source:** route catalog assembled from the official Picos de Europa resources.

**Mock source:** recorded catalog fixtures.

The real adapter may use a periodically updated local catalog if the source does not provide a stable public API.

### `get_route_details`

**Input:** `route_id`.

**Output:**
- Route description
- Distance
- Estimated duration
- Elevation gain
- Difficulty
- Route-specific constraints
- Source reference

**Possible errors:** route not found, unavailable data, upstream error.

### `get_hiking_equipment`

**Input:**
- Route characteristics
- Weather conditions
- Trip duration
- Optional equipment already owned

**Output:**
- Required equipment
- Recommended equipment
- Missing items
- Reasons for recommendations

**Primary content source:** Australian Hiker equipment guidance, including the Multi-Day Gear List.

The service normalizes source information into a structured catalog and applies deterministic rules appropriate to the selected route.

Recommendations must distinguish day hikes from multi-day hikes.

## 6.4 Agent B Tool Contracts

### `check_guide_availability`

**Input:** date, route ID, optional group size.

**Output:** list of available guides with stable IDs, names, availability and relevant route qualifications.

**Errors:** service unavailable, invalid date, no available guides.

No available guides is a valid business result, not a technical exception.

### `check_equipment_inventory`

**Input:** required equipment items, date, optional quantities.

**Output:** per-item availability, rentable quantities and unavailable items.

**Errors:** inventory service unavailable, invalid item, malformed request.

### `create_tour_reservation`

**Input:**
- `request_id`
- `idempotency_key`
- `route_id`
- `date`
- `guide_id`
- Equipment reservations, if required
- Approval reference

**Output:**
- Reservation ID
- Reservation status
- Confirmed route/date/guide
- Creation timestamp

**Errors:**
- Missing approval
- Invalid guide or equipment
- Inventory conflict
- Idempotency conflict
- Service unavailable
- Timeout / uncertain outcome

## 6.5 Real and Mock Integration Strategy

Mock adapters must reproduce the real adapter's normalized schemas and error semantics as closely as possible.

Preferred mock data source: **recorded response snapshots**, stored as fixtures.

Mock mode must support:

- Deterministic responses
- Configurable service failures
- Configurable latency
- Multiple availability outcomes
- Stateful reservation creation
- Idempotency validation

Real mode must use configured external endpoints where available.

The guide scheduling, inventory and booking APIs are imaginary business integrations.
Keep their tools and HTTP adapters simple: provide a small local test service
with three endpoints for guide availability, equipment inventory and reservation
creation. Availability endpoints return fixed scenario responses; the reservation
endpoint returns a synthetic confirmation with an ID derived from the request ID.
The service does not persist bookings, update stock or maintain reservation stores.
Use the same validated contracts as the mock adapters.
The HTTP adapters only send requests, enforce timeouts and normalize responses;
shared wrappers handle bounded retries. Approval validation remains in the
trusted tool layer before reservation creation. Only minimal per-run approval
and idempotency bookkeeping is retained by the runtime for validation and
duplicate-call protection; it is discarded after the run.

The local service is a demonstration backend, not a live tour operator integration.
No database, booking files, authentication system or separate deployment infrastructure is
required for V1. Document one command to start the service and one to run a
scenario against it. Mock mode continues to run directly in process without
starting an HTTP server, while both modes use real LLM inference.

A missing real endpoint must produce an explicit configuration error rather than silently returning mock data.

---

# 7. Request Identity and Idempotency

## 7.1 Request ID

A unique `request_id` is initialized and stored in Agent A's state when Human A starts a new trip-planning request.

The same identifier is propagated to Agent B and associated infrastructure components.

The identifier persists throughout the request's lifecycle.

A new independent trip-planning request receives a new identifier.

## 7.2 Booking Idempotency

Reservation operations use an idempotency key derived from the request ID:

`booking:{request_id}`

V1 assumes one final reservation operation per request.

The Booking Service maintains an idempotency store associating:

- Idempotency key
- Request payload fingerprint
- Reservation status
- Previous result

Rules:

1. First valid request creates the reservation.
2. Identical repeated request returns the previous result.
3. Reusing the same key with different reservation parameters returns an idempotency conflict.
4. A timed-out request may be retried using the same key.
5. The system must never create duplicate reservations for the same successful operation.

If future requirements allow multiple independent booking operations inside one trip request, the key format must include an additional operation identifier.

---

# 8. Error Handling and Recovery

## 8.1 Recovery Categories

### Category A — Transient Technical Failure

Examples:

- HTTP timeout
- HTTP 429
- HTTP 503
- Temporary network interruption

Handling:

1. Tool wrapper catches the error.
2. Applies bounded retries.
3. Uses exponential backoff.
4. Returns success or a typed final error.

Recommended defaults:

- Maximum attempts: 3, including the initial request
- Backoff: 0.5 s, 1 s before subsequent attempts
- Optional jitter
- Configurable per-tool timeout

Retries should apply only to retryable errors. Side-effecting tools additionally require idempotency protection.

### Category B — Recoverable Business Failure

Examples:

- Unavailable guide
- Unsuitable weather
- Unavailable equipment
- Route does not satisfy requirements

Handling:

The responsible LLM agent evaluates alternatives, potentially invokes additional tools and consults the appropriate participant.

These situations are domain outcomes, not infrastructure failures.

### Category C — Human-Recoverable Failure

Examples:

- No automatically acceptable alternative
- Ambiguous manager approval
- Decision outside the agent's authorized scope
- Proposal requiring manual reconsideration

Handling:

1. Agent formulates an escalation question.
2. Invokes `ask_human`.
3. Execution pauses through `interrupt()`.
4. Human response is supplied.
5. Agent continues with the new decision.

Escalation must respect the communication restrictions between agents and their assigned humans.

### Category D — External Service Unavailable After Retries

An external service remains unavailable after exhausting its configured retries.

Handling:

1. Check whether an approved fallback exists.
2. Apply fallback if safe and valid.
3. Otherwise terminate with an explicit failure.

Possible read-only fallback: a previously recorded snapshot, provided it meets the validity requirements for the operation.

Safety-critical decisions must not treat stale weather or unavailable booking confirmation as verified current information.

For booking operations with uncertain outcomes, first check operation status using the idempotency key where supported. Never assume that a timeout means the reservation was not created.

## 8.2 Failure Injection

Mock adapters support configured failures through scenario fixtures.

Example behavior:

- First attempt: timeout
- Second attempt: HTTP 503
- Third attempt: success

Or:

- All attempts: timeout
- Fallback unavailable
- Expected result: controlled failure

A seeded random generator may be used to simulate probabilistic failures while preserving reproducibility.

---

# 9. Simulation Runtime

## 9.1 Purpose

`SimulationRunner` executes predefined test scenarios using real agents and a controlled environment.

The agents continue to use real LLM inference and standard tool calling.

The environment controls human responses, mock service data and failure injection.

## 9.2 Responsibilities

The Runner:

1. Loads scenario configuration.
2. Initializes the environment.
3. Creates agents and their independent states.
4. Initializes Message Bus queues.
5. Sends the initial Human A message.
6. Coordinates pending agent messages.
7. Handles LangGraph interruptions.
8. Supplies Human Simulator responses.
9. Enforces execution limits.
10. Detects terminal outcomes.
11. Collects the final result and trajectory.
12. Invokes programmatic evaluation.
13. Cleans up runtime resources.

Each scenario run must start with isolated agent threads, queues, mock-service state and idempotency records.

## 9.3 Execution Model

The runtime uses asynchronous Python tasks.

Each agent independently processes messages from its queue.

When an agent is suspended by a human interrupt, the Runner services that interrupt and resumes the corresponding LangGraph thread.

The Runner does not directly determine which domain tool an agent should invoke.

## 9.4 Logical Steps

Each significant event receives a monotonically increasing sequence number.

This sequence acts as a logical simulation step.

Physical execution time and logical step count are separate concepts.

V1 will not implement a full virtual-time scheduler. This is an event-driven approximation of discrete-time simulation, designed for readable trajectories and repeatable scenarios.

Asynchronous ordering may differ between runs; evaluation will focus on causal correctness and terminal outcomes rather than exact event-order equality.

## 9.5 Termination

A scenario ends when one of the following occurs:

- Agent A submits a valid terminal `TripResult` and its final message is delivered to Human A.
- A non-recoverable failure is reported.
- Global timeout is reached.
- Maximum number of execution steps is exceeded.
- A deadlock or unmatched-human-response condition is detected.

A normal end of an individual ReAct invocation is **not** automatically considered completion of the entire scenario.

Recommended initial limits:

- Maximum recorded steps: 100
- Maximum agent-to-agent exchanges: 20
- Global runtime timeout: configurable, initially 120 seconds

These values are provisional and should be tuned during testing.

## 9.6 Finalization Contract

Agent A is responsible for producing the final structured trip result.

V1 should expose an explicit completion mechanism, such as a `submit_trip_result` tool accepting the `TripResult` schema and a final human-facing message from Agent A.

This prevents an intermediate conversational response from being misinterpreted as a completed task.

Before accepting completion, runtime validation checks that no mandatory pending operation or unresolved approval remains.

After validating the result, the completion mechanism must deliver the final
message to Human A through the human communication adapter. In simulation mode,
delivery means that the Human A simulator's message sink accepts the message;
no UI or human acknowledgment is required. The message must agree with the
validated result and summarize the confirmed trip and reservation reference,
or explain the failure when Agent A submits a failed result.

Only after delivery succeeds may the runtime record `human.message_delivered`
and then `simulation.completed`. A delivery failure must not be reported as
successful simulation completion. Infrastructure-level failures, such as a
global timeout, may terminate with `simulation.failed` without a final message;
the trajectory must record that delivery did not occur and why.

The completion interface is a domain-level capability, not a simulator-specific addition to ordinary human-facing messages.

---

# 10. Scenario Definitions

## 10.1 Scenario Format

Every scenario contains:

- Scenario ID and description
- Initial Human A message
- Human A question-answer fixtures
- Human B decision fixtures
- Mock service snapshots
- Failure injection configuration
- Expected result and validation rules

Agents must not receive the scenario ID, expected result, or hidden fixtures as part of their instructions.

## 10.2 Five Baseline Scenarios

The initial dataset contains five manually authored scenarios defined below.
Each uses a short initial request, only the human response fixtures needed for
that case, fixed mock-service data and explicit expected-result assertions.
The fixtures are synthetic and informed by the assignment's hiking-trip example.

The no-fallback variant of External Service Failure is an optional extension.

### Scenario 1 — Happy Path

**Input:** Beginner requests an easy four-hour hike.

**Environment:** Good weather, suitable routes, two available guides and sufficient equipment.

**Human B:** Selects guide option 2 and approves.

**Expected:** Confirmed reservation with a suitable route, selected guide and exactly one booking operation.

### Scenario 2 — Bad Weather

**Input:** Tourist requests a hike on a date with unsuitable weather.

**Environment:** Weather fixtures contain a safer alternative date.

**Expected:** Agent A identifies an alternative, obtains any necessary confirmation and the system completes an acceptable reservation.

### Scenario 3 — Guide Unavailable

**Input:** Tourist selects an otherwise acceptable trip.

**Environment:** No guides available for the original date, but an alternative is available.

**Expected:** Agent B identifies the issue, agents coordinate a revised proposal and a valid reservation is eventually confirmed.

### Scenario 4 — HITL Rejection

**Input:** Proposed trip initially lacks required available equipment.

**Human B:** Rejects the first proposal.

**Environment:** An alternative equipment arrangement exists.

**Expected:** Agents adapt the proposal, obtain a new valid approval and finalize the booking.

### Scenario 5 — External Service Failure

**Input:** Normal trip-planning request.

**Environment:** Weather provider fails after all configured retries.

**Fallback:** An eligible weather snapshot is available.

**Expected:** Controlled fallback is recorded, the agent uses valid fallback data and completes the scenario if all safety requirements remain satisfied.

A variant without a valid fallback must terminate with a defined failure status rather than inventing weather information.

## 10.3 Repeated Execution Test

The system must run the same test scenario five consecutive times.

All five executions use:

- Identical scenario fixtures
- Identical LLM configuration
- Identical external-tool mode
- Identical human response rules
- Identical failure-injection seed

The expected outcome is semantic convergence to an acceptable terminal result.

The system does not require identical wording, tool-call order or generated reasoning in every execution.

---

# 11. Structured Output and Evaluation

## 11.1 Final Result Schema

Agent A returns a Pydantic-compatible `TripResult`.

Required fields:

| Field | Type |
|---|---|
| `request_id` | string |
| `status` | `confirmed` or `failed` |
| `route_id` | string / null |
| `date` | ISO date / null |
| `guide_id` | string / null |
| `reservation_id` | string / null |
| `equipment_items` | list of strings |
| `failure_reason` | string / null |

The schema defines conditional validation:

- A confirmed result requires route, date, guide and reservation identifiers.
- A failed result requires a meaningful failure reason.
- IDs must correspond to records created or returned by tools.
- The final result alone is not sufficient evidence that booking constraints were satisfied.

## 11.2 Evaluation Strategy

Evaluation will be **fully programmatic** in V1.

No LLM-as-Judge component is required.

Three validation layers:

### A. Output Validation

Validate the final Pydantic schema and compare its values with scenario expectations.

### B. Business Invariant Validation

Verify:

- Selected route satisfies relevant customer constraints.
- Selected guide is available.
- Required equipment requirements are satisfied.
- Manager approval exists.
- Booking happened after approval.
- Reservation was created at most once.
- The final status matches the actual environment state.

### C. Execution Validation

Inspect recorded events to verify:

- Required agent-to-agent interaction occurred.
- Human responses were routed correctly.
- For a normally completed scenario, Agent A's final message was delivered to Human A, agrees with the validated `TripResult`, and was recorded before `simulation.completed`.
- Retry limits were respected.
- Recovery actions were recorded.
- No forbidden communication occurred.
- Execution terminated within the configured limits.

Evaluation should allow multiple valid business outcomes where the scenario permits alternatives.

## 11.3 Initial Metrics

| Metric | Definition |
|---|---|
| Task success rate | Successful runs / total runs |
| Scenario pass rate | Runs satisfying all expected assertions / total runs |
| End-to-end latency | Time from initial message to terminal result |
| LLM token usage | Total input and output tokens |
| LLM call count | Number of model invocations |
| Tool failure rate | Failed tool attempts / total tool attempts |
| Recovery success rate | Successfully recovered failure cases / recoverable cases |
| Agent interaction count | Number of agent-to-agent messages |
| Human matching failure rate | Unmatched human questions / all human questions |

Metrics should be available per agent and per simulation run where applicable.

## 11.4 Future Evaluation Strategy

Start with the five scenarios defined in Section 10.2. Run four scenarios once
each and one selected scenario five consecutive times for the assignment's
repeatability demonstration: nine runs in total, not twenty-five. The five runs
of the selected scenario also count toward scenario coverage. Repeated runs do not increase the
number of unique dataset cases. This small dataset is intended for initial
technical validation; it does not establish broad production reliability.

For production, the system can expand its evaluation dataset using anonymized real interactions, previously observed failures and edge cases.

Production drift can be monitored through changes in success rate, validation failures, retries, token usage, latency, conversation length and human escalation frequency.

A fixed regression dataset should be used to compare prompt, model and architecture changes.

---

# 12. Observability and JSON Trajectory

## 12.1 LangSmith

LangSmith is the primary LLM observability platform.

It captures:

- LLM inputs and outputs
- Model identifiers
- Token usage
- Tool invocations
- Execution duration
- Errors
- Nested execution traces

Integration should use standard LangChain/LangGraph tracing configuration.

Custom components such as the Message Bus, Human Simulator and Simulation Runner must emit additional instrumentation where automatic tracing is insufficient.

## 12.2 JSON Trajectory

Every simulation produces one human-readable JSON trajectory file.

The trajectory is intended **only for analysis**, not execution replay.

Suggested path:

`trajectories/{scenario_id}/{run_id}.json`

The document uses three top-level sections:

- `metadata`
- `events`
- `result`

### Metadata Schema

| Field | Type | Description |
|---|---|---|
| `schema_version` | string | Trajectory format version |
| `run_id` | UUID | Unique execution ID |
| `request_id` | UUID | Business request ID |
| `scenario_id` | string | Executed scenario |
| `seed` | integer / null | Failure-injection seed |
| `started_at` | timestamp | Run start |
| `finished_at` | timestamp / null | Run end |
| `duration_ms` | integer | Total duration |
| `model` | string | Configured LLM model |
| `environment_mode` | string | Real/mock configuration |
| `langsmith_trace_id` | string / null | LangSmith correlation |

### Event Schema

Every event contains:

| Field | Type | Description |
|---|---|---|
| `event_id` | UUID | Unique event |
| `seq` | integer | Monotonically increasing step |
| `timestamp` | ISO 8601 | Event time |
| `type` | string | Event category |
| `actor` | string | Originating component |
| `recipient` | string / null | Target |
| `caused_by` | UUID / null | Causal parent event |
| `operation_id` | UUID / null | Related operation |
| `data` | object | Event-specific payload |

### Event Types

**Communication**

- `human.message`
- `human.interrupt`
- `human.response`
- `human.message_delivered`
- `agent.message_sent`
- `agent.message_received`

**Tool Execution**

- `tool.called`
- `tool.completed`
- `tool.failed`
- `tool.retry`

**Recovery**

- `recovery.started`
- `recovery.applied`
- `recovery.failed`

**Lifecycle**

- `simulation.started`
- `simulation.completed`
- `simulation.failed`

### Event-Specific Payload Requirements

**`tool.called`**

Must contain tool name, arguments, execution mode, tool-call ID and attempt number.

**`tool.completed`**

Must contain tool-call ID, normalized output, duration and status.

**`tool.failed`**

Must contain tool-call ID, error code, retryability and attempt number.

**`human.interrupt`**

Must contain the actual human-facing question and interaction ID.

**`human.response`**

Must contain the human response, matched intent, match score and corresponding interaction ID.

**`human.message_delivered`**

Records confirmed delivery through the human communication adapter. For the
final response, `actor` must be `agent_a` and `recipient` must be `human_a`.
The event data must contain the message ID, delivered message text,
`message_kind: final_result` and the corresponding validated `TripResult`.
The event must be causally linked to the finalization operation, and
`simulation.completed` must reference this delivery event through `caused_by`.

**`agent.message_sent`**

Must contain message ID, correlation ID, destination and transmitted content.

**`recovery.applied`**

Must identify the failed operation, selected recovery strategy and outcome.

### Causality

Three mechanisms are used:

1. `seq` defines the observed event order.
2. `caused_by` connects an event to its immediate causal predecessor.
3. `operation_id` groups related tool, message or HITL events.

For concurrent operations, event order alone must not be used to infer dependencies.

### Result Section

The final section contains:

- Structured `TripResult`
- Execution outcome
- Validation pass/fail
- Individual validation checks
- Aggregated execution metrics
- Optional error summary

### Data Protection

Tracing must not include credentials, API keys or authentication tokens.

Sensitive user information should be redacted before trace export.

---

# 13. Suggested Project Structure

A compact project structure is recommended:

| Path | Responsibility |
|---|---|
| `app/agents/` | Agent factory, prompts and configurations |
| `app/tools/` | Domain tools and common wrappers |
| `app/tools/adapters/` | Real and mock provider implementations |
| `app/messaging/` | Message bus and envelope schemas |
| `app/humans/` | Human Simulator and keyword matcher |
| `app/simulation/` | Runner, lifecycle and scenario loading |
| `app/models/` | Pydantic contracts |
| `app/observability/` | JSON Trace Recorder |
| `app/evaluation/` | Validators and metrics |
| `scenarios/` | Scenario configurations |
| `snapshots/` | External-service mock responses |
| `tests/` | Unit and integration tests |
| `trajectories/` | Generated execution artifacts |
| `README.md` | Setup and execution instructions |

Actual module boundaries may be simplified during implementation.

---

# 14. Execution Interface

The system provides a CLI entrypoint.

Proposed commands:

**Run one scenario**

`python -m app.simulation --scenario happy_path --mode mock`

**Run the same scenario five times**

`python -m app.simulation --scenario happy_path --mode mock --runs 5 --seed 42`

**Run all available scenarios**

`python -m app.simulation --all --mode mock`

**Run automated tests**

`pytest`

Expected outputs:

- Console execution summary
- Structured final result
- JSON trajectory file
- Evaluation metrics
- LangSmith trace reference when tracing is enabled

The README must explain dependency installation, environment configuration, LLM credentials, real/mock mode selection and execution commands.

---

# 15. Acceptance Criteria

V1 is considered complete when:

- [ ] Exactly two operational AI agents are implemented using the same generic architecture.
- [ ] Both agents maintain independent conversation states.
- [ ] Agent A communicates only with Human A and Agent B.
- [ ] Agent B communicates only with Human B and Agent A.
- [ ] Both agents can autonomously invoke their tools.
- [ ] All seven domain tools expose validated input/output contracts.
- [ ] All external tools support real/mock adapter interfaces.
- [ ] Human interactions use LangGraph interrupt/resume.
- [ ] Human Simulator supports predefined question-answer matching.
- [ ] Human B can approve, reject or select an option.
- [ ] Agent-to-agent messaging uses asynchronous queues and correlation identifiers.
- [ ] Technical retries and exponential backoff are implemented.
- [ ] Business recovery and HITL recovery are demonstrated.
- [ ] External-service failure produces an approved fallback or controlled failure.
- [ ] Booking operations enforce idempotency.
- [ ] Booking requires a valid Human B approval.
- [ ] Simulation execution has finite termination limits.
- [ ] All five baseline scenarios can be executed.
- [ ] One scenario can be executed five times consecutively.
- [ ] Final responses use a validated structured schema.
- [ ] Normal scenario completion requires delivery of Agent A's final response to Human A and a corresponding `human.message_delivered` event before `simulation.completed`.
- [ ] Evaluation runs without an LLM judge.
- [ ] LangSmith tracing is available.
- [ ] Every run produces a human-readable JSON trajectory.
- [ ] Documentation explains architecture, setup and known limitations.

---

# 16. Future Architecture — V2

The initial ReAct implementation serves as the baseline.

V2 should be proposed or implemented only after analyzing observed inefficiencies.

Potential improvements:

### 16.1 Structured Business State

Introduce typed state for trip requirements, proposals, resource availability, approvals and reservations.

**Potential benefit:** fewer repeated LLM interpretations and more deterministic routing.

### 16.2 Hybrid Deterministic Workflow

Move predictable operations into explicit LangGraph nodes while retaining LLM reasoning for ambiguous decisions.

**Potential benefit:** better reliability and fewer unnecessary model calls.

### 16.3 Parallel Tool Execution

Execute independent data retrieval operations concurrently.

**Potential benefit:** reduced end-to-end latency.

### 16.4 Context Optimization

Reduce irrelevant message history and large raw tool responses in model context.

**Potential benefit:** lower token consumption and potentially more consistent decisions.

### 16.5 Tool Gating

Restrict available tools according to the current workflow phase.

**Potential benefit:** fewer incorrect calls and stronger control over execution.

### 16.6 Persistent Execution

Introduce persistent checkpointing and durable communication for recovery after process restarts.

**Potential benefit:** stronger operational reliability.

## V1 vs V2 Evaluation

If V2 is implemented, it must be compared with V1 using identical scenarios and model configurations.

Comparison dimensions:

- Scenario pass rate
- LLM invocation count
- Input/output tokens
- End-to-end latency
- Tool failures
- Recovery success
- Implementation complexity

Architectural improvements should be justified by observed measurements rather than assumptions.

---

# 17. Open Implementation Decisions

The overall V1 architecture is defined. The following details remain configurable or require validation during implementation:

| Topic | Proposed Default / Remaining Decision |
|---|---|
| LLM model | Select a reliable model supported by LangChain |
| Checkpointer | In-memory for V1 |
| Keyword matching | Weighted keyword scoring, threshold 0.60 |
| Multiple human questions | Combine answers for independently matched intents |
| Human matcher fallback | LLM-based matcher only if deterministic matching is insufficient |
| Retry policy | 3 attempts, exponential backoff |
| Simulation limits | 100 steps, 20 inter-agent exchanges, 120 s global timeout |
| Operator service demo | Stateless local HTTP service returning fixed availability and synthetic booking confirmations |
| Booking completion | Explicit structured terminal submission |
| Trace payload size | Record normalized outputs; cap or redact oversized payloads |
| Snapshot validity | Define provider-specific freshness rules |
| V2 scope | Decide after reviewing ReAct traces |

These defaults can change without altering the core architecture.

---

# 18. Delivery Plan

## Phase 1 — Baseline

Implement the two generic ReAct agents, domain tools, Message Bus and HITL interactions.

## Phase 2 — Simulation

Implement scenario fixtures, human matching, real/mock adapters and runtime orchestration.

## Phase 3 — Reliability

Add retry policies, recovery, idempotency and termination limits.

## Phase 4 — Observability and Evaluation

Integrate LangSmith, implement JSON trajectory export, add deterministic validation and execute five consecutive runs.

## Phase 5 — Review and Recommendations

Analyze traces, identify architectural bottlenecks and document justified V2 improvements.

## Final Deliverables

- Source code in a GitHub repository or ZIP archive
- Technical Design Document
- README with reproducible execution instructions
- Scenario fixtures and snapshots
- Automated tests
- One representative successful JSON trajectory
- Results of five consecutive runs
- Evaluation summary
- Architectural improvement recommendations

**Design summary:** V1 deliberately favors two independent, configurable ReAct agents supported by lightweight deterministic infrastructure. This keeps the implementation small enough for the assignment while making agent behavior, failures, human interactions and final outcomes observable and testable.
