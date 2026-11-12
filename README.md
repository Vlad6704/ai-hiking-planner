# Picos de Europa hiking planner

Two ReAct agents arrange a hike. The planner speaks to the customer, checks weather and routes, and sends a proposal to the operator. The operator checks guides and stock, asks its manager for a guide selection and approval, and books the approved terms. The planner delivers a validated result to the simulated customer's inbox.

## Setup

Install Python 3.11 or newer and uv. From the repository root run `uv sync --locked`. Both adapter modes use a real chat model with tool calling. Set `HIKING_MODEL=openai:gpt-6-luna` and supply `OPENAI_API_KEY` for the default GPT-6 Luna configuration. The Chat Completions integration uses reasoning effort `none` to enable function calls. To use local inference, select `HIKING_MODEL=ollama:gemma4:26b` and verify the model is installed with `ollama list`. [OpenAI GPT-6 Luna model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)

Set variables in the shell or copy `.env.example` to `.env`, then use `uv run --env-file .env` in place of `uv run` below. Set `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT` and `LANGSMITH_API_KEY` to enable remote tracing. Local JSON works independently.

## Run

```powershell
uv run pytest -q
uv run python -m app.simulation --scenario happy_path --mode mock
uv run python -m app.simulation --scenario happy_path --mode mock --runs 5 --seed 42
uv run python -m app.simulation --all --mode mock
uv run --env-file .env python -m app.simulation --all --parallel --mode mock --peer-timeout 90 --timeout 300
```

Mock mode reads authored scenarios and synthetic weather/operator snapshots.
For routes, each run seeds an isolated temporary SQLite database from
`snapshots/routes.json`: the fixed November 9, 2026 catalog snapshot with
31 routes and 50 variants. It uses the same SQL/FTS search, filters, details and
validated route contracts as real mode, with source refresh disabled. The live
`ROUTE_CATALOG_DB` is untouched, and the temporary database is removed when the
run ends. Route results preserve exact variant IDs such as `PR-PNPE-2:long`.
The `--seed` argument controls the failure schedule; it does not select the route
dataset. Each repetition gets new request, checkpoint, messaging, approval and
booking state. The CLI prints structured checks, metrics and the trajectory
path for every run. A failed check returns exit code 1.

The six authored customer fixtures prefer the Covadonga long loop and specify
one adult. Happy Path permits only its expected date; the other cases support
a next-day alternative. The deterministic human matcher
combines distinct recognized topics in a question and retains clarification
for competing rules with identical evidence. Substitution answers use the
question and structured offered terms together and are constrained by the
fixture's route, dates and rental equipment.

To reproduce the measured Luna batch in PowerShell, set the model and key in `.env`, then run:

```powershell
uv run --env-file .env python -m app.simulation --scenario happy_path --runs 5 --seed 42 --timeout 180 --peer-timeout 90
foreach ($case in 'bad_weather','guide_unavailable','hitl_rejection','external_service_failure') {
    uv run --env-file .env python -m app.simulation --scenario $case --seed 42 --timeout 180 --peer-timeout 90
}
```

For automated real-mode scenarios, start the stateless operator service in one terminal:

```powershell
uv run python -m app.operator_demo
```

In another terminal:

```powershell
$env:OPERATOR_URL = 'http://127.0.0.1:8765'
uv run python -m app.simulation --scenario happy_path --mode real
```

Real mode requests Open-Meteo near the Covadonga Lakes with explicit Celsius, millimetres and km/h units and the Europe/Madrid timezone. It imports the official route catalog into SQLite, uses deterministic equipment rules, and calls HTTP for the three synthetic operator operations. Live requests use tomorrow's date to stay inside the forecast window; actual weather can prevent a safe booking. Guide scheduling and inventory are illustrative. Each HTTP reservation reference derives from the request ID. Approval and idempotency records live in the caller for the lifetime of one run.

## Official route catalog

These commands work without model credentials:

```sh
uv run python -m app.route_catalog refresh
uv run python -m app.route_catalog search
uv run python -m app.route_catalog search --difficulty easy --max-hours 4 --max-km 10
uv run python -m app.route_catalog search --keywords bosque lago --keyword-match any --max-hours 4
uv run python -m app.route_catalog details PR-PNPE-2:short
```

The database defaults to `data/routes.sqlite3` and is ignored by Git. Set `ROUTE_CATALOG_DB` or pass `--database PATH` to use another location; the runner and operator demo must share that setting. The first real catalog query each Europe/Warsaw calendar day refreshes the source. `refresh` forces another attempt, including after a failed daily attempt. Concurrent processes coordinate through an expiring database lease. Failed or partial imports preserve previous valid data and report freshness explicitly; a first-run failure returns an error rather than synthetic routes.

All search filters are optional. Use minimum/maximum hours, kilometres, ascent (`--min-gain-m`, `--max-gain-m`) and descent (`--min-loss-m`, `--max-loss-m`), difficulty, keywords, sort, limit and offset; see `search --help`. An empty query returns the first 20 active variants, with a maximum page size of 100. Supplied numeric filters exclude unknown measurements. Each public `route_id` identifies a variant and remains unchanged through details and demo booking; `source_route_id` identifies its parent page.

Content search uses literal SQLite FTS5 terms or phrases, accent normalization and BM25 ranking, combined with parameterized numeric SQL filters through a read-only connection. Use source-language keywords (primarily Spanish); for example `cascada` requests a textual waterfall mention, without guaranteeing a match. `--prefix` enables word-prefix matching. Source excerpts explain matches, but a shared page mention does not prove the feature appears on every variant. Full details include original descriptions, cautions, content hashes and timestamps. Ambiguous measurements remain null. A future improvement is hybrid RAG for semantic and multilingual retrieval alongside these SQL filters.

On November 9, 2026 the live import discovered and parsed 31 official route pages into 50 variants. Seven variant durations remained unknown. Repeating the import preserved all 31 content hashes and update timestamps. Mock mode uses the fixed seeded SQLite catalog offline. See the [catalog design](docs/route-catalog-design.md) and [implementation plan](docs/superpowers/plans/2026-11-09-route-catalog.md).

## Manual test in the browser

```sh
uv run --env-file .env python -m app.simulation.web --mode real
```

This starts the local server, manages the HTTP operator demo and opens a page
with two chats: customer/planner on the left and manager/operator on the right.
Enter your initial request on the left, answer questions in the corresponding
chat, select a displayed guide and approve or reject the exact proposal on the
right. Both agents run in the same server process and communicate through queues.
Choose **Simulation** or **Real data** in the Data mode selector before starting
a trip. Switching does not restart the server; `--mode` sets the initial choice.
The selector is locked until you choose New trip. Simulation uses fixture weather
and the seeded catalog. Real data uses live weather and the maintained catalog;
guides, inventory and reservations use the local demo unless an external operator
is configured. The page identifies the data sources and shows mock dates only
in Simulation. Failure-injection settings are reset when switching modes.
Informational answers (such as a route listing) appear in the customer chat
without finishing the trip. Enter your next message to continue planning.
Simple peer acknowledgements finish locally rather than generating another request.
The live trajectory panel on the right shows events as they happen. Expand
an event to inspect its redacted JSON; tool calls, agent messages and failures
remain visible after the trip. On smaller screens the panel sits below the chats.

Use `--mode mock` for fixture-backed services, `--scenario NAME` for another
scenario, `--port 0` for an available port, or `--no-browser` to open the printed
URL yourself. The default port is 8000. One trip runs at a time; refresh reconnects
to it. Cancel stops active work. Completed/cancelled trips save trajectories under
`trajectories/manual/<run-id>.json`, downloadable from the page. Console manual
sessions use the same flat folder; runtime logs remain in `logs/`.
The server binds only to loopback for personal local testing. Stop it with Ctrl+C.

## Manual test with two terminals

After completing Setup, run this single command from the project root:

```sh
uv run --env-file .env python -m app.simulation.manual
```

It opens the operator and customer in separate windows, waits for the operator's listener, and confirms the customer is connected before reporting success. The windows remain open after completion until you press Enter. Start your conversation at `Customer:` in the planner window; answer manager questions in the operator window.

Windows uses native consoles, macOS uses Terminal, and Linux uses an available `gnome-terminal`, `konsole`, `x-terminal-emulator` or `xterm`. Linux needs a graphical desktop. On macOS, allow Terminal automation if prompted and keep model credentials in the project `.env`, which each new Terminal window reloads through `uv`.

To select another scenario or an available port, run:

```sh
uv run --env-file .env python -m app.simulation.manual --scenario hitl_rejection --port 0
```

The normal default is port `18766`; `--port 0` selects an available port automatically. Use `--startup-timeout 60` if either console needs more than the default 30 seconds to become ready. An occupied port or a startup failure stops the attempt and prints an error. On this Windows development host, native window startup is smoke-tested; macOS and Linux dispatch is verified with command-boundary tests.

For the two-command fallback, open two terminals in the project root. Start the operator first. Both terminals join one trip. The customer process runs both agent graphs and owns their shared in-memory bus. The operator terminal connects the human manager to Agent B through a local loopback socket.

| Terminal | Your role | Command |
|---|---|---|
| B — Operator | Tour manager | `uv run python -m app.simulation.manual operator` |
| A — Planner | Customer | `uv run --env-file .env python -m app.simulation.manual customer` |

1. In terminal B, wait for `Listening on 127.0.0.1:18766`. Start terminal A and press Enter at `Customer:` to request an easy hike on November 10, 2026. The mock snapshot also covers November 11.
2. Answer the planner's questions in A. Example: “I'm a beginner with no physical limitations. I want a guided hike of up to four hours. I have boots, water and a first aid kit. I need to rent a rain jacket.” Confirm the proposed date and route if asked.
3. In B, read the operator's question and numbered guide IDs. Enter the number beside the guide you want. At the approval prompt, inspect the route, date, guide ID and equipment quantities. Enter `approve` to authorize those terms.
4. In A, verify the final confirmation contains the selected guide, exact route variant (for example `PR-PNPE-2:long`), the date, rain jacket and a short `TR-XXXXXXXX` reference. B prints the session outcome. The path printed in A points to the JSON trajectory under `trajectories/manual/`. Its events should show Human B's answer before booking and customer delivery before completion.

To test manager rejection, start a session with `--scenario hitl_rejection`. Both jackets and ponchos are available. In B reject the jacket proposal and request a poncho. In A answer the substitution question, then check that B seeks fresh approval before booking the revised terms.

To test equipment shortage, use `--scenario equipment_shortage` in mock mode or select the jacket shortage preset in the browser. Ask for a rental jacket. B checks availability and asks A to offer the available poncho. Repeat the session with a different answer to exercise both outcomes. Declining the substitute should end the proposal without a reservation.

The manual session uses GPT-6 Luna (or the configured model) with mock services and real keyboard input for both humans. Browser and console manual sessions do not run scenario evaluation. Their trajectories record the actual session status, structured trip result and runtime error, without `passed`, scenario checks or evaluation metrics. The selected scenario supplies the initial environment; a changed date, different rental kit or controlled refusal is not a failed scenario test. Runtime approval, weather, route, availability and idempotency checks still apply. Automated scenarios retain their evaluator in both mock and real mode. If the port is occupied, pass the same unused `--port NUMBER` to both commands. Each operator process accepts one customer session.

For manual testing against Open-Meteo and the official catalog, use the same
single-command launcher with real mode:

```sh
uv run --env-file .env python -m app.simulation.manual --mode real
```

This opens both human consoles and starts the local HTTP operator demo
automatically; no separate service command is required. The default operator
URL is `http://127.0.0.1:8765`. A plain HTTP loopback `OPERATOR_URL` can select
another local port. An existing healthy demo is reused; an unrelated occupied
port produces a startup error. Remote or custom-path endpoints remain externally
managed. The customer process stops the demo it started when its session ends.

Weather and routes use real planning adapters. The HTTP operator remains a demo
with synthetic guides, inventory and reservations. The two-command fallback
accepts `--mode real` on the `customer` command and also manages the local demo.
Both manual and automated modes save catalog refresh diagnostics and the content
identity used by each route tool in their trajectories.

The booking tool accepts an empty rental set when the customer owns the required
equipment; scenario rental expectations do not impose booking requirements.
Before starting a browser trip, choose normal conditions, a jacket shortage,
or a guide shortage on a selected date. These presets control operator
availability for the session in mock mode and with the bundled HTTP demo.
A separately configured external operator supplies its own availability.

## Runtime logs

Application logging is separate from LangSmith tracing and trajectory JSON.
Every CLI process writes UTF-8 JSON Lines immediately under repository-root
`logs/`. Files identify the process role, PID and startup timestamp, for example
`manual-customer-1234-20261109T180000000000Z.jsonl`. The embedded operator demo
uses the customer process's file with `component=operator_demo`. Each file
rotates at 5 MiB with three backups; older process logs remain available until
you remove them. Logs are ignored by Git.

Set `LOG_DIR` for another directory and `LOG_LEVEL` to `DEBUG`, `INFO` (default),
`WARNING`, `ERROR` or `CRITICAL`. Errors also appear in stderr. HTTP/LLM library
payload diagnostics stay disabled even at application DEBUG level. Log records
redact configured secrets, authentication fields and URL userinfo/query strings;
request/response bodies, human messages and prompts are not recorded.

For a manual-session error, inspect the latest `manual-customer-*.jsonl` and
`manual-operator-*.jsonl`; launcher/bootstrap failures are logged too. The
launcher prints the log directory. Trajectories do not contain runtime-log paths.
Match `run_id`, `request_id` and `operation_id` to
the agent trajectory. Records include UTC timestamps, component, process and
thread identity, plus exception type, errno/winerror and traceback for failures.
Stacks retain frame locations and exception chains without source lines or
locals. Validation/provider exceptions omit embedded input/body values while
retaining error counts or status. Conversion errors and chained causes omit
arbitrary value-bearing text while preserving frame locations, types and codes.

An `asyncio.exception` record captures callback failures even when no tool fails
and the booking completes. It includes local/peer socket addresses when the
transport is still available, including bound transport callbacks. Null addresses
mean the information was unavailable. HTTP records identify sanitized
destinations, status and duration and can correlate a request with its tool.
This adds diagnostics for connection resets; it does not change their handling,
the event-loop implementation or booking outcomes.

## Execution and evidence

All reservation providers use short `TR-XXXXXXXX` codes, with eight characters
from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`. The shared contract validates this
format for provider receipts and final results. A provider using another format
must support this contract through its operator adapter.
Mock and bundled HTTP-demo codes are collision-checked and stable for a request
within the provider process; restarting it resets its identity mappings.
The model submits business fields only. A's finalization tool binds the request
and verified reservation ID from its own checkpointed state, using the outcome
received from B. It renders the final confirmation. The same
reservation ID appears in tool results, customer messages and trajectories.

Each agent has a separate typed business state in its private LangGraph thread.
A owns customer requirements and planning facts. B owns guide/inventory facts,
manager approval and booking records. Neither agent's tools can read the
other's state. Structured messages carry requests, offers, customer decisions,
booking progress and final outcomes. A recipient validates and checkpoints
the payload before continuing its model. Tools assemble payloads from their
own state and validated arguments.

An outgoing message is checkpointed before dispatch. Inbox and outbox records
use stable message IDs, with duplicate delivery suppressed. Independent read
tools merge observation records without overwriting a sibling's result.
Human interaction data and replies are checkpointed in the owning agent.
Evaluation and traces observe these exchanges without providing business facts
back to either agent.

V1 uses InMemorySaver. Reconstructing an agent with the same saver can resume
its saved state, while process termination still loses the saver and queues.
A database-backed checkpointer can be injected without relocating business
facts. Complete process-restart recovery also needs durable/restored transport
dispatch and recreated client resources. A checkpoint database alone does not
make external side effects transactional.

Automatic reports include `cached_input_tokens`, `cache_write_tokens`,
`cache_read_ratio` and reporting-coverage counts, per agent and overall.
Cache totals and ratios are null when any model call in that scope omits the
corresponding field. Reported zeros remain zero. Cache reads/writes are already
included in input tokens.

Mock failure injection can override one tool in any scenario:

```sh
uv run --env-file .env python -m app.simulation --scenario happy_path --mode mock --failure-tool check_equipment_inventory --timeout-probability 0.3 --seed 1
```

The probability applies to each provider attempt, including retries. Both
failure options are required together. Use a value from 0 to 1; 1 fails every
attempt. In the browser's mock mode, select a tool under Failure injection,
enter a timeout percentage (0–100) and an integer seed before starting.
Scenario defaults retain the scenario's authored faults. Selecting a tool
replaces its fault rule; selecting weather also overrides an always-failing
weather fixture. The seed and effective rules are saved in the trajectory.
The same seed repeats the fault random sequence; model decisions and tool order
can still vary. Real mode rejects injection overrides. An intentionally
unavailable service may produce a safe failed trip while the automatic scenario
evaluation still fails its original success expectation.

Route search sends the model compact candidate summaries and keyword-match
excerpts. The planner selects a candidate before requesting full details and
reads its directions and cautions before proposing a trip. Complete original
tool results remain in trajectory events under the existing redaction limits
and in A's checkpointed observations. SQLite and the route catalog CLI retain full
records.

Agents can request independent read-only tools in one model response. LangGraph
runs those tools concurrently. Agent instructions keep human questions,
messaging, approvals and booking in separate model responses. Per-agent
`parallel_tool_batches` counts responses requesting multiple tools. The
[evaluation history](docs/evaluation-history.md#parallel-retrieval-validation--november-11-2026)
records the measured Sol comparison.

Each agent has a private checkpoint thread and consumes its own queue. The bus owns message IDs and reply deadlines. Human questions interrupt the calling graph and the runner resumes that thread with the scenario answer. A successful reservation must have current resource availability and an approval for the same route, date, guide and equipment. The simulator accepts the final message before the completion event is emitted.

Defaults allow 100 events, 20 peer transmissions, 30 seconds for a peer reply and 120 seconds for a run. Use `--timeout` and `--peer-timeout` to tune deadlines for a slower model. Tool calls have three attempts for transient failures. After exhausted weather attempts a fallback must match the requested location and dates and be no more than six hours old at the scenario clock.

Automated trajectories appear under `trajectories/automatic/<scenario>/<run-id>.json`;
`--output` replaces the root directory. Browser and console manual sessions both
write `trajectories/manual/<run-id>.json`, without scenario subdirectories.
The default `trajectories/` root contains only `manual/` and `automatic/`.
Git includes six selected successful automatic examples, only the latest five
successful consecutive happy-path trajectories and one selected manual trajectory.
Earlier experimental happy-path batches remain local and ignored. See the [evaluation summary](docs/evaluation-summary.md)
for the complete batch outcomes, including the initial guide failure. Old
artifacts were removed; `trajectories/` is ignored by default. Explicitly publish
selected examples with `git add -f <trajectory-path>`; already tracked examples
remain tracked. Selected examples do not establish an overall success rate.

Inspect the terminal event and the individual checks when a run fails. The automated cases cover the happy path, weather/date changes, unavailable guides, manager rejection, provider outages and equipment shortages. Model wording, call order and outcomes can vary even with temperature zero. The JSON is an analysis record. The in-memory runtime has no restart recovery or production booking integration.

The Covadonga route data and equipment guidance were consulted on November 8, 2026. [Park route description](https://www.miteco.gob.es/es/parques-nacionales-oapn/red-parques-nacionales/parques-nacionales/picos-europa/guia-visitante/ruta-lagos-covadonga.html) · [Australian Hiker equipment list](https://australianhiker.com.au/gear/multiday-gear-list/)

## Repository-local Codex skills

The following skills are versioned in `.agents/skills/` and travel with this repository. No global skill installation is required. When a global copy has the same name, explicitly use the repository-local `SKILL.md` linked below; Codex can discover both copies.

| Skill | Purpose |
|---|---|
| [writing-plans](.agents/skills/writing-plans/SKILL.md) | Turn the technical design into implementation tasks with interfaces, tests and verification commands. |
| [executing-plans](.agents/skills/executing-plans/SKILL.md) | Execute a plan in the current agent session, recording progress and verifying each task. |
| [langchain-fundamentals](.agents/skills/langchain-fundamentals/SKILL.md) | Build LangChain agents, tools, middleware and structured outputs. |
| [langgraph-fundamentals](.agents/skills/langgraph-fundamentals/SKILL.md) | Work with graph state, nodes, routing, persistence and interrupt/resume. |
| [subagent-driven-development](.agents/skills/subagent-driven-development/SKILL.md) | Execute a plan with a fresh implementer and task reviewer for each task, followed by a final review. |

For example, ask Codex to use `.agents/skills/writing-plans/SKILL.md` to plan a change, then choose either `executing-plans` or `subagent-driven-development` to implement the reviewed plan. Subagent execution requires the corresponding tools in the active Codex session. The skills are available on the next turn; restart Codex if they do not appear.

The local bundle also includes eight supporting Superpowers skills: `using-superpowers`, `using-git-worktrees`, `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `requesting-code-review`, `receiving-code-review` and `finishing-a-development-branch`. These supply the workflow instructions, review templates and platform references used by the planning and execution skills. Keep their directory layout intact so relative references and helper scripts continue to resolve.

The shell helpers require Bash and standard Unix tools. On Windows, use Git Bash from Git for Windows; its Bash executable is typically `C:/Program Files/Git/bin/bash.exe`. Temporary plan briefs, review packages and progress ledgers live under the ignored `.superpowers/sdd/` directory.

Superpowers is pinned to commit `22f0b463e7a5e579904dd6211a520321035526f7`; the LangChain skills match commit `126c384d8552dcb476b226c244172186cc3f4328`. [sources.json](.agents/skills/sources.json) records each upstream directory, commit and file checksum. The four existing skills were copied from their installed versions; the subagent workflow and supporting skills were downloaded from the matching Superpowers commit. Update snapshots intentionally, together with their source metadata and licenses. These files guide development and are separate from the application's Python dependencies.

Upstream sources: [Superpowers](https://github.com/obra/superpowers/tree/22f0b463e7a5e579904dd6211a520321035526f7) and [LangChain Skills](https://github.com/langchain-ai/langchain-skills/tree/126c384d8552dcb476b226c244172186cc3f4328). Both bundles include their MIT notices: [Superpowers license](.agents/skills/SUPERPOWERS-LICENSE.txt) and [LangChain license](.agents/skills/LANGCHAIN-LICENSE.txt). [Codex skill discovery documentation](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).

[Technical design](docs/technical-design.md) · [Implementation plan](docs/implementation-plan.md) · [Evaluation results](docs/evaluation-summary.md) · [Top three scenarios and historical reliability](docs/evaluation-summary.md#scenario-reliability)
