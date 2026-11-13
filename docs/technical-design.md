# Agent Systems Engineer — Technical Design Document

**Project:** Multi-Agent Hiking Trip Planning System  
**Version:** 1.2 — Cross-platform manual launcher\
**Date:** November 9, 2026\
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

V1 includes two independent agents, seven domain tools, agent-to-agent messaging, simulated and manual human interactions, runtime orchestration, retries and recovery, idempotent reservations, tracing, and programmatic evaluation.

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

**Customer ↔ Agent A ↔ Message Bus ↔ Agent B ↔ Tour manager**

In automated runs, scenario fixtures supply both humans' answers. In a manual test, each human has a separate terminal. The customer process hosts both agent graphs, their separate checkpointed business states and the in-memory message bus. The manager process listens on loopback for one customer process and exchanges manager prompts and answers as newline-delimited JSON. All communication between the agents uses the message bus.

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

For `openai:gpt-6-sol`, omit the unsupported temperature parameter and record
the unspecified temperature as null in trajectory metadata.
For the Luna comparison, configure `openai:gpt-6-luna` with explicit
`temperature=1` and record that value in trajectory metadata.
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

Informational requests, such as listing routes, do not require trip dates,
gear or a booking proposal. Use `send_to_customer` to present an informational
answer and suspend for the customer's next message, without producing a
terminal TripResult or contacting Agent B. The browser and console reuse their
human-input mechanism for the next message. Record `human.information` when
the answer is presented; correlate the later human response to that event.

`acknowledge_message` ends a turn locally without queueing a message.
Its tool description and agent instructions explicitly say OTHER AGENT rather
than relying on the term "peer": use it only after a message from the other
agent requiring no further action. Never use it for customer or manager
messages, greetings, questions or answers. After a human answer, agents resume
the active task. A peer request
requires an actionable response, including when a proposal cannot proceed.
Peer replies/notifications do not require acknowledgements. `send_to_agent`
defaults to a notification; operational requests must explicitly use request.
Responses/errors without an outstanding correlated request return an error
rather than silently becoming a new request. Runtime reminders must accept a
local acknowledgement as a completed turn. Booking approval/final delivery
requirements remain unchanged.

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

### Date context

Both agents receive the same explicit current local date and timezone in
their system instructions. Real runs use the current date in Europe/Warsaw;
mock runs derive it from the scenario clock in that timezone. Record this
date context in the run metadata. Real scenario defaults use the same local
calendar rather than the execution host's timezone.

For an omitted year, use the year already established in the conversation,
or the current year for unambiguous upcoming dates. Do not ask the customer
to confirm the year solely because it was omitted. Inherit an established
month and year for subsequent day-only ranges such as "13-15". Respect any
explicit year. Clarify genuinely ambiguous or contradictory dates, including
past dates without a clear future interpretation. An obvious nearby New Year
transition uses the upcoming year. Send complete ISO dates to tools.

### Domain Tools

| Tool | Description |
|---|---|
| `get_weather_forecast` | Retrieve weather forecasts |
| `search_hiking_routes` | Find routes matching constraints |
| `get_route_details` | Retrieve detailed route information |
| `get_hiking_equipment` | Retrieve equipment recommendations |
| `reply_with_customer_decision` | Record the customer's decision on a revised offer and return it to Agent B |

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

Each agent has typed, serializable business state alongside its conversation
history. The two checkpointed states are fully separate.

The base agent state extends LangGraph `MessagesState` with:

| Field | Type | Description |
|---|---|---|
| `messages` | Message collection | Agent-specific conversation history and tool interactions |
| `request_id` | UUID string | Identifier for the trip-planning request |
| `inbox`, `outbox` | Structured messages | Received facts, processed IDs and outgoing dispatch records |
| `trip_status`, `pending_interaction` | Structured records | Agent task phase and resumable human question |

Each agent has an independent LangGraph thread.

Thread identifiers:

- `{request_id}:agent_a`
- `{request_id}:agent_b`

Neither an agent nor its tools can access the other agent's history or state,
including through runner fields, shared business objects or closures.

### State ownership

Agent A owns customer requirements, its route/weather/equipment results,
requested terms, offers received from B, actual customer replies and decisions,
and reservation outcomes received from B.

Agent B owns requests received from A, its guide/inventory results, manager
interactions and guide selection, exact approvals/rejections, customer decisions
received from A, booking attempt status, idempotency records and provider receipts.

These facts are explicit serializable fields in their owner's agent state.
Tools read local state and return checkpointed updates, using mechanisms such
as `ToolRuntime.state` and `Command(update=...)`. State fields need not all be
included in every model prompt. No essential business fact may exist only in
a runner attribute, closure or process-local approval/provider registry.

Both agents continue to use the same LangChain `create_agent` architecture.
This ownership model does not require a parent graph with shared agent state.
Parallel tool updates must merge without losing completed sibling results.
Interrupt resume must retain facts already checkpointed by the owning agent.

A peer-owned fact becomes available only after a structured message is received
and its payload recorded in the recipient's own state, with source message
identity and exact proposal references. Each agent validates its local facts
and received evidence. A common request ID does not grant peer-state access.

The runner and bus own transport scheduling, queues, deadlines and execution
limits. Live clients, locks and tasks remain runtime resources; their resumable
business meaning belongs in agent state. Traces and evaluation can observe
execution but cannot supply business facts back to agents or become another
communication channel.

### Checkpointing

A LangGraph checkpointer maintains each agent's complete serializable business
and conversation state across invocations and human interruptions, including
pending interaction identity, exact terms, completed facts and operation status.

V1 may use an in-memory checkpointer for the test runtime.

Persistence across process restarts is not guaranteed in this configuration.

The schemas and tools must permit replacing the in-memory checkpointer with a
database-backed one without moving business facts. End-to-end durable recovery
also requires restoring transport from checkpointed inbox/outbox records and
recreating runtime resources. A checkpointer swap alone does not persist queues.
Stable message IDs and idempotency keys prevent duplicate effects on replay.

---

# 4. Agent-to-Agent Communication

## 4.1 Communication Pattern

Communication uses an **asynchronous Request-Reply pattern over an in-memory Message Bus**.

Messages are the only communication channel between agents, including their
tools. Shared runner fields, business registries, traces and direct reads of
peer checkpoints must not communicate business facts.

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
| `content` | String | Human-readable explanation accompanying the typed payload |
| `timestamp` | ISO 8601 | Creation timestamp |
| `payload` | Typed payload / null | Validated business facts and exact proposal references |

The Message Bus is responsible for metadata and routing. Natural-language
content explains a message; typed payloads carry operational facts. Receiving
a message updates only the recipient's state. Message IDs support deduplication.

The business exchange is:

1. A sends structured requirements, requested route/date/rentals and relevant
   route, weather and equipment facts obtained by A's tools.
2. B returns a structured complete proposal after resource checks and manager
   guide selection, or a structured availability/failure result.
3. A returns the customer decision for that exact offer, linked to B's offer
   message ID and A's originating customer interaction.
4. B returns a structured booking outcome with exact terms, approval/decision
   references and the provider-issued short reservation ID when confirmed.
5. Each recipient checkpoints the received facts in its own state.

### Compact planning evidence

A sends only evidence for the selected route and date: route identity,
difficulty, distance, duration, elevation and operational constraints; the
selected day's forecast with location, provider and issue time; and required,
recommended and missing equipment. Rental quantities remain in the exact terms.
Search result lists, other routes/dates, descriptions, navigation instructions,
points of interest, raw text, catalog metadata and equipment explanation text
must not be copied into peer messages. Original tool observations remain in A's
private checkpoint and the audit trajectory.

Evidence is projected by trusted code, not rewritten by the model. Each compact
fact retains a stable source observation reference scoped to route/date. Only
new or changed evidence is sent; customer decisions reference the exact offer
and actual reply without resending previous evidence. A changed date or route
includes the corresponding new evidence. B retains previously received facts
in its private state for validation. Its model sees compact operational data,
not raw evidence wrappers, query arguments or audit metadata. Transport retries
retain the already checkpointed message rather than rebuilding its evidence.

Booking progress and uncertainty are also communicated through structured
messages when needed. Missing outcome information never proves that no booking
exists. A cannot discover a booking by reading B's provider object.

Agents should not be required to generate message IDs or manage transport-level correlation manually.

## 4.3 Sending Messages

Agents communicate through the shared message bus using `send_to_agent` or A's
dedicated `reply_with_customer_decision` tool for returning a customer's decision.

For example, Agent A may request:

"Please check guide and equipment availability for the proposed trip."

The tool publishes the message into Agent B's queue.

Agent B receives the message and starts or continues its ReAct execution using its existing thread.

## 4.4 Reply Handling

Agent B sends the result through the same communication mechanism.

The runtime uses the correlation identifier to associate the response with the original request.

Agent A's first operational message uses `send_to_agent(kind="request",
proposal=...)` with exact `route_id`, ISO `date` and equipment quantities.
Prose in `content` supplements these structured fields. A omits `guide_id`
until the manager chooses it.

Agent B reports an availability problem in a structured availability/failure
payload with `kind="response"`, omitting a complete offer. A missing-guide report
asks A to coordinate a feasible date. For a complete alternative offered for
customer consent, B includes `proposal` only after verifying availability and
obtaining the manager's guide selection, so the exact terms include `guide_id`.

#### Customer decision on a revised offer

When the route, date or rental equipment changes, B sends A the complete,
verified alternative as a structured offer. If B supplies only a description,
A requests the missing proposal. A presents the customer-facing terms and
passes the exact offer to `ask_human`. Runtime links the customer's verbatim
reply to that question and offer and resumes A with the reply. The simulator
supplies the customer's words in automated runs. In both manual and automated
runs, A interprets what the customer meant.

For clear acceptance or refusal, A calls
`reply_with_customer_decision(decision: Literal["accepted", "declined"])`.
A's tool binds the decision to the current offer and actual reply in A's state.
It checkpoints the decision and outgoing message intent, then dispatches that
structured message. B records the received decision in its own state. Dispatch
retries use the same message ID and cannot duplicate the business decision.
The trajectory links the recorded decision to the original reply, offer and
outgoing message. A retry must not deliver a second decision. Only acceptance
returned to B for the current exact terms permits B to seek manager approval.
A refusal closes that proposal without booking.

If the reply is ambiguous, A clarifies with the customer about the same offer.
If the customer requests different terms, A asks B to verify those terms and
return a new offer. Neither case grants approval for the old offer. Each agent's
tools validate identity, received evidence and order using only local state.
They do not classify
customer text with keywords or regular expressions.

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
5. The runner obtains a response from the assigned human's simulator or terminal.
6. Runner resumes the graph using `Command(resume=answer)`.

After validating a human response, trusted code checkpoints its complete record
in the owning agent's `interactions` and the relevant consent/approval fields,
and records the full `human.response` audit event. Only then does the tool
return a compact model-facing result in `state.messages`:

- Customer questions, revised-offer replies and `send_to_customer`: verbatim
  human text only. A still interprets acceptance/refusal and returns its decision
  using the existing proposal-bound tool.
- Manager guide selection: `text` and the validated `guide_id`.
- Manager approval/rejection: `text` and boolean `approved`, preserving any
  rejection explanation in the text.

Interaction/event IDs, matching intents/scores, approval references and copied
proposal records remain in private business state and audit events, not the
model-facing tool content. The ordinary LangChain ToolMessage name, role and
tool-call ID remain intact. Validation failures keep their existing error
results. This projection is identical for simulated and manual answers and
does not change checkpoint/resume, consent checks or booking authorization.

In manual mode the planner asks questions in the customer terminal. The operator displays questions, numbered guide IDs and proposed booking terms in the manager terminal. The manager chooses a displayed number, then types `approve` or `reject` when asked about the specific proposal. A rejection can include a requested change. Both interaction modes use the same validation and B's checkpointed approval records.

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
7. Retain supported intents above threshold. Within each clause, combine
   close-scoring intents only when each has distinct matched token evidence.
   Prefer a more specific match over a candidate using only the same evidence.
   Identical evidence for competing intents remains ambiguous.
8. Combine the configured answers in stable fixture order, once per intent.

General questions do not select the structured substitution-consent rule.
Scenario rule overrides merge with the base snapshot rules. The six current
cases include a definite preference for the Covadonga long loop and one adult.
Happy Path allows only its expected date; the other cases support a next-day
alternative. Alternative-date patterns follow that case's policy rather than
repeatedly restating a preferred date or accepting a forbidden change.
Real-mode date answers use the same dynamically selected forecast-window dates.
Authored substitution decisions are constrained to the fixture's preferred
route when that preference has been communicated, allowed dates and
substitution equipment. Before a route preference has been communicated,
use the route from A's original operational proposal for equipment-only
substitutions. A fixture's unspoken route preference must not reject a
replacement item for the already selected route. An offer outside those
constraints receives a refusal. Real-mode guide-shortage preset dates move
with the requested date as well.
The simulator receives both the question and exact structured proposal for a
substitution interrupt. Its decision is based on those combined inputs.

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

For a structured substitution interrupt, restrict fixture matching to the
substitution intent. A clarification with no matched intent does not constitute
a customer refusal and must not create a consent decision. Sol CLI validation
may use the existing configurable 90-second peer and 300-second overall limits
to accommodate slower model responses.

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

Approval decisions are checkpointed in B's state with request ID, exact terms,
manager interaction and approval reference. B validates its own approval and
resource records together with customer consent received from A. B cannot read
A's consent records; A receives approval evidence in B's outcome message.

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
| `metadata` | Optional catalog freshness and refresh identity alongside route results |

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

The Open-Meteo adapter requests explicit Celsius, millimetre and km/h units
and the `Europe/Madrid` forecast timezone. Validate date order, response
arrays, units and finite numeric values before returning a forecast. Invalid
or unsupported dates and malformed provider responses produce typed errors;
transient HTTP failures retain the common bounded retry policy.

Both automated and two-console manual entrypoints accept `--mode mock|real`.
The launcher forwards the selected mode to the customer process. Real-mode
scenario defaults use dates inside the live forecast window. Real mode uses
the configured HTTP operator endpoint. The manual entrypoint manages a local
demo backend automatically as described in Section 14.1; automated scenarios
can still use a separately started service. This remains a demonstration
service rather than a production booking integration.

**Mock source:** Recorded weather-response snapshots.

For a Picos de Europa snapshot only, the mock adapter normalizes known
comma-separated location components: Picos de Europa, Lagos de Covadonga,
Asturias and Spain. A query must name Picos de Europa or Lagos de Covadonga;
Asturias/Spain alone and any unknown component remain unsupported. Ignore case,
extra whitespace and component order. Preserve the snapshot's canonical
location and existing date/range validation. This alias handling is mock-only;
the real Open-Meteo adapter and its accepted location remain unchanged.

**Possible errors:** timeout, service unavailable, invalid location, unsupported forecast date, malformed response.

### Route catalog and retrieval

The detailed feature design for `search_hiking_routes` and `get_route_details`
is maintained in [Persistent Route Catalog and Content Search](route-catalog-design.md).

### `get_hiking_equipment`

**Input:**
- Route characteristics
- Weather conditions
- Trip duration
- Optional equipment already owned

Planner instructions require copying the verified forecast day for the selected
date into the equipment query, including all four numeric weather values.

**Output:**
- Required equipment
- Recommended equipment
- Missing items
- Reasons for recommendations

**MVP data source:** Fake (synthetic) equipment data maintained in the local
`catalogs/equipment.json` file. Both `mock` and `real` modes use this catalog
and deterministic recommendation rules. The MVP does not fetch or normalize
content from Australian Hiker; the source URL in the catalog is a reference only.

**Future content source:** Australian Hiker equipment guidance, including the
Multi-Day Gear List. A future implementation can normalize this source into a
structured catalog and apply deterministic rules appropriate to the selected route.

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

Rental items are the missing equipment agreed for the actual customer request.
An empty rental set is valid when the customer owns the required equipment.
Scenario fixture expectations such as `required_rentals` must not impose
requirements inside the booking tool in either environment mode. Keep weather,
route, resource availability, exact approval and idempotency checks in place.

## 6.5 Real and Mock Integration Strategy

Mock adapters must reproduce the real adapter's normalized schemas and error semantics as closely as possible.

Preferred mock data source: **recorded response snapshots**, stored as fixtures.

Route retrieval uses the same SQLite store, SQL/FTS search, variant identities
and validated response models in both modes. Mock runs initialize an isolated
temporary database from the versioned normalized route seed, use the scenario
clock for freshness, and disable source refresh. They do not read or modify the
live catalog database. See the route feature design for seed details.

Mock mode must support:

- Deterministic responses
- Configurable service failures
- Configurable latency
- Multiple availability outcomes
- Stateful reservation creation
- Idempotency validation

Real mode must use configured external endpoints where available.

The guide scheduling, inventory and booking APIs are imaginary business integrations.
Keep the operator integration simple: provide a small local test service
with three business endpoints for guide availability, equipment inventory and reservation
creation. Availability endpoints return fixed scenario responses; the reservation
endpoint returns a synthetic confirmation with a short code assigned to the request ID.
The service does not persist bookings, update stock or maintain reservation stores.
All reservation providers, including mock, the bundled HTTP demo and external
operator services, use the same short `reservation_id` format:
`TR-XXXXXXXX`, with eight characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`.
The operator service issues the identifier, handles collisions and returns the
same identifier for a repeated idempotent request. The external service is
expected to satisfy this contract. The application uses that single identifier
throughout tool results, final results, customer messages and trajectories.
The in-process `MockOperator` and the single HTTP operator adapter
`HttpOperatorProvider` expose the same validated contracts for all three
operations. If an external provider uses a different identifier format,
its operator adapter must support the system's short-ID contract.
Shared wrappers handle bounded retries. Approval validation remains in the
trusted tool layer before reservation creation. Approval, booking attempt status,
receipts and idempotency bookkeeping are checkpointed in B's state. The runner
does not maintain a second authoritative business registry.

The local service is a demonstration backend, not a live tour operator integration.
No database, booking files, authentication system or separate deployment infrastructure is
required for V1. Document one command to start the service and one to run a
scenario against it. Mock mode continues to run directly in process without
starting an HTTP server, while both modes use real LLM inference.

A missing real endpoint must produce an explicit configuration error rather than silently returning mock data.

### Manual environment presets

The browser offers three presets before starting a trip: Normal conditions
(default), No rain jackets, and No guides on a date. For the third preset the
tester selects the affected date. Apply the selected operator conditions only
to that session, using the same inventory and guide data for the in-process
operator and the bundled HTTP demo. Live weather and route retrieval still use
the configured providers. A separately configured external operator controls
its own availability. Show which conditions apply before the session starts.
The manager can reject any feasible proposal during a manual conversation.

Style the native preset select and affected-date input consistently with the
browser UI: inherited font, white background, rounded corners, a minimum
44-pixel height and a visible green keyboard-focus ring. Give the select a
green chevron and enough width for its longest option. Keep native keyboard
interaction and clear disabled states; allow the controls to wrap on mobile.

Browser and console manual sessions do not run the scenario evaluator. Their
selected scenario supplies the initial test environment, not an expected outcome
for the conversation. Preserve runtime approval, weather, availability, route,
idempotency and terminal-delivery validation. Human reviewers judge whether the
conversation and selected trip meet the customer's preferences.

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

An exhausted retry result explicitly indicates that automatic attempts are
exhausted. Agents must stop reissuing the failed service operation in this
session. B returns an operational failure to A; A submits a failed trip result.
A must not acknowledge an actionable failure and leave the session unfinished.
Technical reasons are retained in logs and trajectories. Customer-facing failed
trip messages use the generic text "We couldn't complete your request. Please
try again later." The detailed failure reason is not copied into customer text.

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

CLI and browser manual sessions expose an optional mock-only timeout override
for one domain tool. The CLI accepts `--failure-tool <tool-name>` and
`--timeout-probability <0..1>`, used together, with the existing `--seed`.
The browser presents a Failure injection tool selector, timeout percentage
(0..100) and seed (default 42). Controls are locked for the current session.
Real mode rejects supplied injection settings and hides these controls.

Each provider attempt independently samples the configured timeout probability
using the run's seeded generator. Retries remain bounded by existing policy.
The override replaces the selected tool's fixture failure rule. Selecting
weather also overrides the legacy always-failing weather flag. Other tool
rules and scenario fallback availability retain their configured values.
Without an override, the scenario uses its authored failure settings.
Store effective failure rules and the seed in trajectory metadata. Each
concurrent run owns its random generator and failure counters. A fixed seed
repeats the random sequence, while model decisions and tool order may vary.
Automatic scenario checks retain their authored expectations, so deliberately
preventing completion can produce a failed scenario evaluation with a safe
controlled failure. Manual sessions report their actual outcome.

---

# 9. Simulation Runtime

## 9.1 Purpose

`SimulationRunner` executes predefined test scenarios using real agents and a controlled environment.

The agents continue to use real LLM inference and standard tool calling.

The automated environment controls human responses, mock service data and failure injection. Manual runs use keyboard input for both participants and retain the selected scenario's mock services and failure settings.

## 9.2 Responsibilities

The Runner:

1. Loads scenario configuration.
2. Initializes the environment.
3. Creates agents and their independent states.
4. Initializes Message Bus queues.
5. Sends the initial Human A message.
6. Coordinates pending agent messages.
7. Handles LangGraph interruptions.
8. Routes each human response to the graph thread that issued the interrupt.
9. Enforces execution limits.
10. Detects terminal outcomes.
11. Collects the final result and trajectory.
12. Invokes programmatic evaluation.
13. Cleans up runtime resources.

Each scenario run must start with isolated agent threads, queues, mock-service state and idempotency records.

The simulation CLI accepts `--parallel` with either `--all` or `--scenario`.
It schedules all selected runs, including `--runs` repetitions, concurrently
with `asyncio.gather` in one Python process. Each run writes its own trajectory
and prints its report when it completes. The exit code is nonzero if any run
fails. Without `--parallel`, runs execute sequentially.

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

- Agent A submits valid business fields through `TripSubmission`; A's tool binds
  identifiers from its own state and B's received outcome, validates the resulting
  `TripResult` and delivers its final message to Human A.
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

Agent A submits the final structured business fields through `TripSubmission`.

`submit_trip_result` accepts `TripSubmission`. A's tool binds the request ID
from A's state and the reservation ID from B's structured outcome already
received and checkpointed by A. It validates submitted terms against that
message and builds `TripResult`, then renders the canonical final text.
It cannot read B's receipt, provider wrapper, approval registry or checkpoint.
Approval and availability enforcement occurs at B's booking boundary using
B's own facts and the planning/consent evidence received from A.

This prevents an intermediate conversational response from being misinterpreted as a completed task.

Before accepting completion, A checks its local pending requests and received
outcome. B's outcome must establish that its operational work is resolved.
Transport lifecycle checks can establish message delivery, but cannot replace
an outcome payload with knowledge obtained by inspecting B's business state.

After validating the result, the completion mechanism must deliver the final
message to Human A through the human communication adapter. In automated runs,
the customer simulator accepts the message. In manual runs, the customer adapter
prints and flushes the final text in the planner terminal and records delivery.
The manager terminal receives the session outcome. The message must agree with the
validated result and summarize the confirmed trip and reservation reference,
or show the generic failure message when Agent A submits a failed result.

Only after delivery succeeds may the runtime record `human.message_delivered`
and then `simulation.completed`. A delivery failure must not be reported as
successful simulation completion. After a runtime stop such as deadlock, step
limit or timeout, cancel active agent tasks and attempt one bounded final
customer delivery. Preserve the runtime error and record `simulation.failed`
with the actual delivery status. Cleanup and terminal delivery have a small
reserved event allowance beyond the normal work-step limit, so exhausting the
work budget cannot prevent the final notification.

Terminal customer delivery, including runtime safety notification, uses only
A's checkpointed state. B sends booking progress before invoking a reservation
side effect and sends the outcome afterwards. A checkpoints these messages.
The bus can drain already queued outcome messages into A's inbox during cleanup;
the runtime must never read B's state to complete A's knowledge.

If A's received facts establish that no reservation was attempted, construct
a failed result and deliver the generic message above. If A has received a
verified confirmation, render its canonical message. If a reservation attempt has an
uncertain outcome, deliver "We couldn't confirm your booking status. Please
contact the operator before trying again." Preserve the uncertain status rather
than asserting that no booking exists. A missing terminal response to pending
booking work is treated as unconfirmed. Neither path resumes booking work.
An unsuccessful notification is recorded as a delivery failure without a
successful completion event. Already delivered final messages are not repeated.

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

## 10.2 Automated Scenarios

The original five baseline cases and the additional equipment shortage case are defined below.
Each uses a short initial request, only the human response fixtures needed for
that case, fixed mock-service data and explicit expected-result assertions.
The fixtures are synthetic and informed by the assignment's hiking-trip example.

The no-fallback variant of External Service Failure is an optional extension.

### Scenario 1 — Happy Path

**Input:** Beginner explicitly requests the Lagos de Covadonga long loop
(`PR-PNPE-2:long`), about 2.5 hours, within a four-hour limit. Include this route
in the initial message so every repetition receives the same preference even
when the model asks different follow-up questions. Real-mode date adaptation
retains the explicit route requirement.

**Environment:** Good weather, suitable routes, two available guides and sufficient equipment.

**Human B:** Selects guide option 2 and approves.

**Expected:** Confirmed reservation with `PR-PNPE-2:long`, the selected guide and
exactly one booking operation. The scenario sets `expected_route_id`; evaluation
requires that ID and successful verification through route search or exact
route details. A known exact ID need not be searched before its details are
retrieved. Merely naming an ID without tool evidence is insufficient.
Scenarios without an explicit expected route still require verified tool evidence
but do not pin one route ID.
Happy Path sets `allow_alternative_date=false`: its initial message and human
date answers allow only `expected_date`, and proposal-bound consent rejects
another date. Real-mode date adaptation keeps this single-date constraint on
the generated date. Other scenarios retain their existing date alternatives.

### Scenario 2 — Bad Weather

**Input:** Tourist requests a hike on a date with unsuitable weather.

**Environment:** Weather fixtures contain a safer alternative date.

**Expected:** Agent A identifies an alternative, obtains any necessary confirmation and the system completes an acceptable reservation.

### Scenario 3 — Guide Unavailable

**Input:** Tourist selects an otherwise acceptable trip.

**Environment:** No guides available for the original date, but an alternative is available.

**Expected:** Agent B identifies the issue, agents coordinate a revised proposal and a valid reservation is eventually confirmed.

### Scenario 4 — HITL Rejection

Both rain jackets and ponchos are in stock. Agent B verifies that the proposed
jacket is available and submits the feasible jacket proposal. The manager
rejects it and asks B to offer a poncho. B verifies availability and asks A
to obtain the tourist's explicit agreement. Only after agreement may B seek
fresh approval of the revised exact terms and book them. A rejection creates
no reservation. A tourist declining the substitution ends this proposal
without booking.

### Scenario 5 — External Service Failure

**Input:** Normal trip-planning request.

**Environment:** Weather provider fails after all configured retries.

**Fallback:** An eligible weather snapshot is available.

**Expected:** Controlled fallback is recorded, the agent uses valid fallback data and completes the scenario if all safety requirements remain satisfied.

A variant without a valid fallback must terminate with a defined failure status rather than inventing weather information.

### Additional scenario — Equipment Shortage

B obtains the manager's guide selection before sending the complete substitute
proposal to A. This selection precedes customer consent; approval of the revised
booking follows consent. A requests a complete structured offer if B only
describes a substitute in prose. A uses the substitution question flow to obtain
the customer decision and then returns that decision to B.

The requested rain jacket is unavailable and a poncho is available. B checks
the requested inventory, then checks the substitute and asks A to present it
to the tourist. A returns the tourist's decision to B. B may submit the
substitute to the manager only after the tourist accepts it. If declined,
finish without a reservation. Record the checks, customer decision, manager
approval and booking in causal order. Exercise both customer choices in tests.

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

Runtime produces the persisted Pydantic-compatible `TripResult` from Agent A's
business submission and trusted identifiers.

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

## 11.3 Performance Metrics

### 11.3.1 Per-run evaluation in the trajectory (implemented)

Each automatic run stores its evaluation in the trajectory JSON under `result`:
`checks` contains individual assertions, `passed` is the scenario verdict and
`metrics` contains performance measurements. The CLI also prints this result.
There is no separate per-run report file. This subsection retains the original
metrics table; the batch-summary specification starts in Section 11.3.2.

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

The original table above describes metric concepts. In the current per-run JSON,
`task_success_rate` is a 0/1 booking-confirmation indicator and
`scenario_pass_rate` is a 0/1 all-checks-passed indicator. Rates over multiple
runs belong to the batch summary. `latency_ms` measures elapsed monotonic time
from trace initialization until evaluation. `recovery_success_rate` counts
explicit `recovery.applied` / `recovery.started` events, not ordinary retries.
A controlled failed trip can pass a scenario expecting refusal.

Automatic evaluation reports cached input reads, cache writes when supplied by
the provider, and cached-input share, both per agent and for the run. Use
LangChain usage metadata's cache_read/cache_creation values, including
priority/flex variants. Zero is a reported zero; missing usage remains null.
A cache total or ratio is available only when all model calls in that scope
reported that field. Include reporting coverage counts. Cached reads and writes
are parts of input usage and must not be added to total input tokens again.
Earlier trajectories lacking cache fields cannot establish historical cache hits.

### 11.3.2 Automated batch summary

**Status:** Implemented for the automatic CLI. Existing per-run evaluation and
trajectory outputs remain available independently of this batch summary.

One invocation of the automated simulation CLI defines one batch, including
all selected scenarios and repetitions. Aggregate that invocation's results,
not a directory scan of historical trajectories or selected successful examples.
The same contract applies to sequential and parallel execution. Manual sessions
remain outside this automated scenario summary.

#### Batch identity and comparison context

Assign a `batch_id` and record start/end timestamps, requested scenarios and
repetitions, execution mode, sequential/parallel scheduling, effective model and
temperature, seeds, failure-injection settings, timeouts and execution limits.
Record scenario/snapshot fingerprints and catalog seed identity where available.
Include the source revision and dirty-worktree flag when Git is available;
unavailable revision metadata is null, for example in a ZIP distribution.
Preserve a per-run entry with scenario, repetition, run/request IDs, outcome,
checks, metrics and trajectory reference. These identifiers support diagnosis
but are not part of the business-outcome comparison.

Provide overall totals and a breakdown per scenario. Compare repeatability only
within the same scenario, effective fixture and runtime/model configuration.
Different seeds may be listed as an intentional experimental variable; do not
silently describe different configurations as identical repetitions.

#### Required batch metrics

Each row below defines one metric. Report overall values and a breakdown per
scenario. LLM and cache metrics also have a per-agent breakdown; tool metrics
also have a per-tool breakdown. Counts, units and denominators must be explicit.

##### Primary metrics

Show this block first in both the console and Markdown batch summaries.

| Metric | Definition |
|---|---|
| Scenario pass rate | Passed run count / planned run count; missing reports cannot pass. |
| Successful business-result repeatability | Most frequent successful normalized result's count / planned repetitions within a comparable scenario group. |
| Runtime error count | Runs ending with a startup or execution error, including runs that also have a trip result. |
| Mean run latency | Sum of reported `latency_ms` / latency sample count. |
| Median run latency | Median of reported `latency_ms`. |
| Maximum run latency | Maximum reported `latency_ms`. |
| Total input tokens | Sum of reported input-token counts, subject to usage completeness rules. |
| Mean input tokens | Sum of measured per-run input-token counts / runs reporting that measurement. |
| Total output tokens | Sum of reported output-token counts, subject to usage completeness rules. |
| Mean output tokens | Sum of measured per-run output-token counts / runs reporting that measurement. |
| Cached input tokens | Sum of reported cached input reads, subject to cache completeness rules. |
| Cache-write tokens | Sum of reported cache-creation tokens, subject to cache completeness rules. |
| Cached-input share | Summed cached input reads / summed input tokens for the same scope. |
| Total LLM call count | Sum of model invocation counts. |
| Mean LLM call count | Total measured model invocation count / runs reporting that measurement. |

##### Sample size and coverage

Display these counts alongside the primary metrics so missing runs and latency
sample size remain visible. Apply the usage-coverage rules below to token totals
and means.

| Metric | Definition |
|---|---|
| Planned run count | Number of requested scenario/repetition pairs. |
| Reported run count | Number of runs with an evaluation result. |
| Latency sample count | Runs reporting `latency_ms`. |

##### Diagnostic metrics

| Metric | Definition |
|---|---|
| Started run count | Number of runs whose execution started. |
| Missing report count | Planned runs without an evaluation result. |
| Not-started run count | Planned runs whose execution never started. |
| Passed run count | Runs for which all expected scenario checks pass. |
| Confirmed execution count | Runs with a confirmed trip result and no runtime error. |
| Controlled failed-trip count | Runs with a failed trip result and no runtime error. |
| Incomplete run count | Runs without a terminal result or a recorded runtime error, including not-started runs. |
| Confirmed-booking count | Runs with a confirmed booking receipt, including those with a subsequent runtime error. |
| Booking confirmation rate | Confirmed-booking count / planned run count; missing evidence cannot count as confirmation. |
| Check failure count | Number of false results for each named check; include the count of runs reporting that check as its denominator. |
| Error-code count | Number of runs reporting each runtime error code. |
| Business-result frequency | Count of each normalized business result within a comparable scenario group. |
| Agent-message count | Number of `agent.message_sent` events. |
| Measured-run count | Number of runs reporting a given measurement; report separately for each applicable metric. |
| Token-usage reporting call count | Model calls reporting input/output token usage. |
| Cache-read reporting call count | Model calls reporting cached input reads. |
| Cache-write reporting call count | Model calls reporting cache-creation tokens. |
| Tool-attempt count | Number of `tool.called` events. |
| Failed tool-attempt count | Number of `tool.failed` events. |
| Tool failure rate | Failed tool-attempt count / tool-attempt count. |
| Tool retry count | Number of `tool.retry` events. |
| Explicit fallback-attempt count | Number of `recovery.started` events. |
| Successful fallback count | Number of `recovery.applied` events. |
| Explicit fallback success rate | Successful fallback count / explicit fallback-attempt count. |
| Batch wall time | Elapsed monotonic time for the complete invocation, not the sum of individual run latencies. |

The four execution counts (confirmed, controlled failed, runtime error and
incomplete) are mutually exclusive and cover all planned runs. Runtime errors
take precedence. Preserve the separate business status when a receipt exists:
an execution failure does not prove that no reservation exists.

Report latency sample count, mean, median and maximum for all measured runs and
separately for passed and non-passed runs. Use the implemented `latency_ms`
interval described in Section 11.3.1. Empty groups produce null statistics.

Normalize a business result using status, route ID, date, guide ID and sorted
equipment items. Exclude request IDs, reservation IDs, timestamps, wording and
tool ordering. Report its fields rather than only an opaque hash. Show the
repeatability distribution alongside scenario pass rate: repeated failed trips
must not be presented as reliable successful bookings. This measurement compares
the existing final-result fields; it does not establish identical model behavior
or identical rental quantities absent from that result schema.

#### Aggregation rules and incomplete data

- Calculate tool failure rate from summed failed attempts / summed attempts,
  not the mean of per-run rates. Calculate cached-input share from summed cache
  reads / summed input tokens, not the mean of per-run cache shares.
- Preserve missing measurements as null, never zero. Include measured-run and
  model-call coverage where relevant, using the usage callback's reported-call
  counts. Distinguish a complete total from a known subtotal. A total or ratio
  needing unavailable usage is null; a labeled observed subtotal may still be
  shown. Means over measured runs must state that denominator.
- Count `tool.retry` as retries. Explicit fallback accounting uses
  `recovery.started` and `recovery.applied`; do not imply that the existing
  fallback success ratio measures every operation recovered by retry.
- A per-run exception must be recorded without discarding completed sibling
  results or silently cancelling the remaining selected cases. On batch
  interruption, retain available results, identify incomplete/not-started runs
  and mark the summary incomplete. Do not manufacture missing trajectories.
- Scenario pass rate is separate from confirmed-booking rate. A deliberate
  outage may safely end in refusal and still fail a scenario expecting booking.
- Default summary metrics do not include estimated monetary cost, subjective
  answer quality or production drift scores. Do not use p95 as the headline
  latency statistic for a five-run sample.

#### Output artifacts

- Each batch produces console output and `summary.json` / `summary.md` in
  `reports/automatic/<batch_number>/`.
- Allocate sequential, zero-padded directory numbers atomically. Keep the UUID
  `batch_id` in JSON.
- Include all planned runs and relative links to available trajectories,
  including failed runs. Preserve existing per-run CLI output.
- JSON retains full-precision metrics and reporting coverage.
- Markdown and console use readable labels, formatted numbers, percentages and
  seconds. Show missing data as `Unavailable`; explain partial coverage.
- Present primary metrics first. Group diagnostics by topic, agent and tool.
- Scenario checks show `Check | Passed | Failed`; exclude missing or inapplicable
  results from both counts.
- Console diagnostics show failed checks and errors, followed by artifact locations.

Use portable relative artifact references and apply the existing redaction rules.
Generated reports stay ignored by Git unless explicitly selected for publication.
Failed mandatory checks, missing runs or execution errors retain a nonzero CLI
exit status; writing a summary does not turn a failed batch into a success.

## 11.4 Future Evaluation Strategy

For the original acceptance batch, use the five baseline scenarios in Section 10.2. Run four scenarios once
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

## 12.0 Runtime Logging

Use Python's standard-library logging independently of LangSmith and JSON
trajectories. Persist operational logs immediately as UTF-8 JSON Lines so
startup failures and asynchronous callback errors remain available even when
a run never finishes or tracing is disabled. Do not replace or reinterpret
the existing trajectory events or evaluation outcomes.

### Files and configuration

- Default directory: repository-root `logs/`, excluded from Git.
- `LOG_DIR` overrides that directory; `LOG_LEVEL` defaults to `INFO` and
  accepts `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`.
- Give each process its own role/PID/start-time filename. Threads in that
  process share its handler; separate consoles never rotate the same file.
- Rotate at 5 MiB, keeping three backup files per process log. Old process
  logs are retained until removed by the operator.
- Initialize logging once per process. Repeated setup must not duplicate
  handlers. A logging-directory/configuration failure produces an explicit
  startup error. Keep errors visible in stderr as well as the file.

### Records and boundaries

Each record contains UTC timestamp, severity, logger/event, process ID,
thread name and component/role. Include run ID, request ID, actor, tool-call
operation ID and attempt when available. Exception records include exception
type, message, errno/winerror when present and the formatted traceback.
Retain stack frame filenames, line numbers, function names and exception
chains, but omit source-code lines and locals. Summarize validation/provider
exceptions without their embedded input/body values; keep their type and
validation count or HTTP status for diagnosis. Omit value-conversion details
and arbitrary messages from chained causes, retaining their frames/types and
errno/winerror codes.

Log process/startup failures, console connection/disconnection, run start/end,
tool failures/retries and catalog refresh failures. Record outbound HTTP
method, sanitized destination, response status and duration for the planning
and operator adapters. Never log request/response bodies, human messages,
LLM prompts, credentials or authentication headers. Keep noisy HTTP/LLM
library diagnostics at WARNING even when application logging uses DEBUG.
Apply redaction to messages, exception text and structured fields, including
URL credentials/query strings and configured secret values.

Install an asyncio exception handler on both the simulation/customer loop
and the embedded operator server loop. Capture callback failures independently
of awaited tool errors, without suppressing them or changing event-loop type.
Preserve a previously installed custom exception handler. Include callback/
task identity and local/peer socket addresses when available. A callback
context may expose its transport only through the bound callback; inspect
that conservatively. Closed/absent transports must not break the handler;
unavailable addresses remain explicitly unknown rather than guessed.

Capture uncaught main-thread and worker-thread exceptions as well. Logging
must not change retry policy, booking approval, terminal outcomes or network
error propagation. Scope/reset per-run correlation to avoid IDs leaking into
a later run. Restore scoped loop handlers after use.

### Entrypoints and verification

Configure process logging for the manual launcher/consoles (including the
lightweight bootstrap), automated simulation CLI, catalog CLI and standalone
operator demo. The background demo uses the customer process's log with its
own component identity. Do not include runtime-log paths in trajectory metadata.
Correlate logs and trajectories by run/request IDs; document log location through
LOG_DIR and README rather than exporting local filesystem paths.

Tests must verify valid JSON, rotation, redaction, idempotent initialization,
context isolation, actual asyncio callback failures with transport addresses,
handler chaining, background-loop capture and preserved awaited errors.
Exercise startup/error logging in subprocesses and retain existing scenario,
launcher and HTTP-adapter regression coverage. A logged cleanup warning does
not by itself turn a successful booking into a failed run.

Verified on November 9, 2026: 146 offline tests passed. Independent staged
review passed after response-value and authorization redaction regressions
were fixed. Controlled callback diagnostics retained both TCP endpoint
addresses and WinError 10054; subprocess startup errors persisted to JSONL.

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

Automated simulation path (a CLI `--output` value can replace the root):

`trajectories/automatic/{scenario_id}/{run_id}.json`

Both browser and console manual sessions write directly to
`trajectories/manual/{run_id}.json`, without scenario subdirectories. Keep the
scenario identifier in metadata. The default trajectory root has only `manual/`
and `automatic/` directories. Consolidate older batches into this layout while
preserving run IDs and JSON contents, and update evaluation report links.

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

The model-facing `submit_trip_result` accepts business fields through a
`TripSubmission` (status, route, date, guide, equipment, failure reason).
A's tool binds request_id and reservation_id from A's checkpointed state.
The reservation ID must come from B's structured confirmation received through
the bus. Final validation uses that received evidence and A's local facts.
The canonical text is rendered from the validated result; the model does not
copy technical IDs into the submission. No direct access to B's receipt is used.
Persisted `TripResult` retains the active request ID and the operator-issued
short reservation ID. The same short-ID contract applies to external receipts.
A's tool uses the received verified short ID directly, without generating an alias.

For automated scenarios, the final section contains:

- Structured `TripResult`
- Execution outcome
- Validation pass/fail
- Individual validation checks
- Aggregated execution metrics
- Optional error summary

For browser and console manual sessions, the result section contains only:

- `status`: actual session status (`confirmed`, `failed`, `cancelled`, `error`
  or `incomplete`), without an overall evaluation verdict.
- `trip_result`: the structured `TripResult`, or null if none was produced.
- `error`: runtime error summary, or null.

Do not include `passed`, scenario checks or scenario evaluation metrics in
manual exports. A controlled refusal to book is a business result (`failed`),
not a scenario-test verdict. Cancellation retains its actual session status.
Automated evaluation is independent of the selected real/mock environment.

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

## 14.1 Manual test entrypoint

### Browser interface

`uv run --env-file .env python -m app.simulation.web --mode real` starts a
loopback-only FastAPI server and opens the browser after binding its port.
The page presents customer/planner and manager/operator chats side by side.
Both agents remain in one server process and communicate through the existing
queues. Browser polling and structured replies replace terminal human input;
all selection, approval and booking checks remain in the existing runner.

Before creating a browser session, a Simulation / Real data selector chooses
the data mode for that session without restarting the server. The CLI `--mode`
sets the initial selection. Session creation accepts the selected mode and
returns it in snapshots; refreshing reconnects using the session's actual mode.
The selector is locked until the user starts a new trip, and the API rejects
another session while one is active. Mode-specific configuration controls mock
dates, failure injection and availability presets; mock-only settings must not
carry over into real sessions. The local HTTP operator demo is initialized on
demand when real mode is selected and released at server shutdown. Simulation
continues to use its in-process operator even after the demo was initialized.
Clearly show that real mode uses live weather and the maintained route catalog,
while guides, inventory and reservations remain demonstrative unless an external
operator is configured. Errors initializing real mode are shown without silently
falling back to simulation.

Support one active trip per server. In mock mode, show the scenario's simulated current date and the dates
covered by its weather fixtures before and during a trip. Place the notice in
the Session conditions area and keep that area visible while scrolling. Read these dates from
scenario data. Hide this notice in real mode.

The customer starts a trip with an initial
request; each pending question has an ID, and replies must match its actor
and ID. Numbered guide choices display the provider's `Guide.name`. Keep the
original guide IDs and ordering for selection validation and booking. If a guide
name is unavailable, display its ID as a fallback. Show exact proposal terms with Approve /
Reject controls and a rejection reason. Display errors, terminal outcome,
final customer message and a downloadable trajectory. Render all messages
as text, not HTML. Refreshing the page reconnects to the current trip.
New trip clears the previous session's displayed error and returns to the
initial request form. Late polling responses or errors for the previous session
must not restore its content or overwrite a new session.
Enter sends the initial request or a chat answer; Shift+Enter inserts a new
line. Ignore composition/repeated key events and prevent duplicate sends
while a request is in flight. Approval/rejection still requires its explicit
button and is never triggered by Enter in the rejection-reason field.
Show a third, right-hand live trajectory panel, updated by the same polling
as the chats. Display ordered events with sequence, time, actor and type;
expand an event to inspect its redacted JSON, including tool activity and
inter-agent messages. Apply the trajectory export's redaction before sending
events to the browser. Preserve expanded events and chat drafts across polls.
The panel is available during execution and retained after completion; on
narrow screens it moves below the chats. It shows recorded events, not private
model reasoning or system log records.
Record the human interrupt when the question is presented, before waiting
for input. The live trajectory must show it while the human is still thinking;
record the response only after submission and emit no duplicate interrupt.

The browser can cancel a trip; server shutdown cancels active work and saves
its trajectory. Every terminal run saves `trajectories/manual/{run_id}.json`,
with runtime logging unchanged. The real-mode demo backend is managed for
the server lifetime using the existing ownership checks. Mock mode stays
offline apart from model inference. Bind only to 127.0.0.1, reject unexpected
Host/Origin values and do not enable cross-origin access. This is a personal
local test UI, not a multi-user deployment. Existing console commands remain
available.

### Console interface

From the project root, `uv run --env-file .env python -m app.simulation.manual`
opens both human terminals automatically. The optional `launch` role is an
explicit alias. The launcher uses the current Python environment, starts the
operator first and waits up to 30 seconds for a private temporary readiness
file written after its loopback listener is bound. It must not probe the
listener with a TCP connection, because the operator accepts one customer.
Only after readiness does it start the customer with the reported port and
selected scenario. The customer acknowledges a connected, ready-for-input
console through its own temporary status file before the launcher reports
success. `--port 0` requests an available port; `--startup-timeout` controls
each console's readiness deadline. An occupied port, startup error or timeout
must prevent customer launch and produce an actionable error.
Status files are published atomically. A short bounded retry tolerates transient
file-access contention, including a Windows reader briefly blocking replacement;
persistent publication errors still fail startup.
If customer launch fails, stop the processes started for that attempt. A lightweight
console bootstrap publishes its PID before importing the agent runtime.
Cancellation marks the attempt before cleanup; queued consoles check the
marker and attempt-directory lifetime before startup and after runtime
imports, so a delayed terminal cannot start a session after a timeout.

Adding `--mode real` to the same manual command must start the complete
session without a separate service command. The customer process defaults
`OPERATOR_URL` to `http://127.0.0.1:8765` when absent. For plain HTTP loopback
URLs, it starts the demo backend in a daemon thread inside that process and
waits for readiness before publishing the customer-ready status. The demo
provides `GET /health` with its service identity. Reuse a healthy demo already
listening at that URL; an occupied port belonging to another service is an
explicit startup error. Configured non-loopback or custom-path endpoints
remain externally managed. Mock mode starts no HTTP backend.

The customer process stops only a demo server it started, including after
EOF, errors or cancellation. A closed customer process cannot leave behind
a separate demo-server process. Both human consoles still open automatically.
The live weather and route adapters remain real; guide scheduling, inventory
and reservation responses remain the documented synthetic HTTP demo.

Windows uses a new console for each child process. macOS uses Terminal via
AppleScript and reloads the project `.env` through `uv` when present, because
an existing Terminal application does not inherit the launcher's shell
environment. Use `.env` for macOS credentials. Linux requires a graphical
desktop and an installed supported terminal (`gnome-terminal`, `konsole`,
`x-terminal-emulator` or `xterm`). Missing terminal support must explain the
two-command fallback below. Launches must preserve paths containing spaces
and shell metacharacters. Automatically opened consoles wait for Enter after
the session ends so the result remains visible.

For manual startup or environments without graphical terminal support,
start the terminals in this order from the project root.

| Terminal | Command | Participant |
|---|---|---|
| B | `uv run python -m app.simulation.manual operator` | The tour manager selects a guide and decides whether to approve the terms. |
| A | `uv run --env-file .env python -m app.simulation.manual customer` | The customer enters the initial request, answers the planner and receives the final result. |

The default address is `127.0.0.1:18766`. Both commands accept `--port`. The customer command selects the initial test environment with `--scenario` (default `happy_path`) and loads the configured model. Manual runs allow 3,600 seconds overall and 900 seconds for a peer reply to accommodate typing. Each run writes `trajectories/manual/{run_id}.json`, without scenario subdirectories. It records the actual result and runtime errors without scenario evaluation. See the [manual test runbook](usage.md#manual-test-with-two-terminals) for the approval and rejection walkthrough.

---

# 15. Acceptance Criteria

V1 is considered complete when:

- [ ] Exactly two operational AI agents are implemented using the same generic architecture.
- [ ] Both agents maintain independent conversation states.
- [ ] Each agent's complete business state is serializable and checkpointed independently; no business facts depend on runner attributes or peer-state access.
- [ ] Structured messages are the only exchange of business facts between agents and their tools. A fact absent from the received payload cannot be obtained from a shared registry.
- [ ] Checkpoint/resume preserves pending human interactions, decisions and completed tool facts. Duplicate message dispatch/reception does not repeat business effects.
- [ ] Agent A communicates only with Human A and Agent B.
- [ ] Agent B communicates only with Human B and Agent A.
- [ ] Both agents can autonomously invoke their tools.
- [ ] All seven domain tools expose validated input/output contracts.
- [ ] All external tools support real/mock adapter interfaces.
- [ ] Human interactions use LangGraph interrupt/resume.
- [ ] Human Simulator supports predefined question-answer matching.
- [ ] In a two-terminal manual test, the customer receives the confirmed reservation after the manager selects a guide and approves the displayed terms. Verify in the trajectory that a rejected proposal cannot create a reservation and revised terms require fresh approval.
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

Typed, isolated agent business state is required in V1 by Section 3.4. This
section no longer defers it to V2. Future improvements may optimize the size
and projections of each agent's state while preserving message-only exchange.

**Potential benefit:** fewer repeated LLM interpretations and more deterministic routing.

### 16.2 Hybrid Deterministic Workflow

Move predictable operations into explicit LangGraph nodes while retaining LLM reasoning for ambiguous decisions.

**Potential benefit:** better reliability and fewer unnecessary model calls.

### 16.3 Parallel Tool Execution

Implemented in V1 after measuring sequential model-call overhead. The agent
may request several independent read-only tools in one model response. The
existing LangGraph tool node executes them concurrently. Allowed retrieval
tools are weather, route search, route details, equipment advice, guide
availability and inventory. Every call must already have its required inputs.
For example, weather and route search can share a batch; guide availability
and inventory can share a batch for a known route/date.

Agent instructions require human questions, customer messages, peer messages,
acknowledgements, reservation creation and final result delivery to each run
alone. A dependent lookup waits for its prerequisites. Approval and booking
retain their existing runtime validations.

Verify concurrency with deterministic graph tests and barrier synchronization.
Verify checkpoint/interrupt resume preserves completed sibling reads. Record
`parallel_tool_batches` per agent in evaluation metrics as the count of model
responses requesting more than one tool. Compare measured model calls and
elapsed time with the preceding sequential runs; a single run is not a
repeatability guarantee.

**Potential benefit:** reduced end-to-end latency.

### 16.4 Context Optimization

Reduce irrelevant message history and large raw tool responses in model context.

**Potential benefit:** lower token consumption and potentially more consistent decisions.

### 16.5 Tool Gating

Restrict available tools according to the current workflow phase.

**Potential benefit:** fewer incorrect calls and stronger control over execution.

### 16.6 Persistent Execution

Replace the V1 in-memory checkpointer with a persistent implementation and
restore message dispatch from the isolated checkpointed inbox/outbox records.
Recreate transport and client resources to recover after process restarts.

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
