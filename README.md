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

[Technical design](docs/technical-design.md) · [Implementation plan](docs/implementation-plan.md) · [Evaluation results](docs/evaluation-summary.md)
