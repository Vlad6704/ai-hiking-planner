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
```

Mock mode reads the authored scenarios and synthetic snapshots in process. The seed identifies the deterministic failure schedule. Each repetition gets new request, checkpoint, messaging, approval and booking state. The CLI prints structured checks, metrics and the trajectory path for every run. A failed check returns exit code 1.

To reproduce the measured Luna batch in PowerShell, set the model and key in `.env`, then run:

```powershell
uv run --env-file .env python -m app.simulation --scenario happy_path --runs 5 --seed 42 --timeout 180 --peer-timeout 90
foreach ($case in 'bad_weather','guide_unavailable','hitl_rejection','external_service_failure') {
    uv run --env-file .env python -m app.simulation --scenario $case --seed 42 --timeout 180 --peer-timeout 90
}
```

For real mode, start the stateless operator service in one terminal:

```powershell
uv run python -m app.operator_demo
```

In another terminal:

```powershell
$env:OPERATOR_URL = 'http://127.0.0.1:8765'
uv run python -m app.simulation --scenario happy_path --mode real
```

Real mode uses the Open-Meteo forecast near the Covadonga Lakes, a sourced local route catalog, deterministic equipment rules, and HTTP for the three synthetic operator operations. Live requests use tomorrow's date to stay inside the forecast window. Guide scheduling and inventory are illustrative. Each HTTP reservation reference derives from the request ID. Approval and idempotency records live in the caller for the lifetime of one run.

## Execution and evidence

Each agent has a private checkpoint thread and consumes its own queue. The bus owns message IDs and reply deadlines. Human questions interrupt the calling graph and the runner resumes that thread with the scenario answer. A successful reservation must have current resource availability and an approval for the same route, date, guide and equipment. The simulator accepts the final message before the completion event is emitted.

Defaults allow 100 events, 20 peer transmissions, 30 seconds for a peer reply and 120 seconds for a run. Use `--timeout` and `--peer-timeout` to tune deadlines for a slower model. Tool calls have three attempts for transient failures. After exhausted weather attempts a fallback must match the requested location and dates and be no more than six hours old at the scenario clock.

Trajectories appear under `trajectories/<scenario>/<run-id>.json`. Inspect the terminal event and the individual checks when a run fails. The five cases exercise the happy path, weather/date change, unavailable guide, rejected proposal and provider outage. Model wording, call order and outcomes can vary even with temperature zero. The JSON is an analysis record. The in-memory runtime has no restart recovery or production booking integration.

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

[Technical design](docs/technical-design.md) · [Implementation plan](docs/implementation-plan.md) · [Evaluation results](docs/evaluation-summary.md)
