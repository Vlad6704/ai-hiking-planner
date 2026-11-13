# Picos de Europa hiking planner

Two agents arrange a guided hike. The planner talks to the customer and checks routes and weather. The operator checks guide and equipment availability and asks a manager to approve the booking.

In the published `happy_path` batch, all five consecutive runs passed the scenario checks and confirmed the same route, date, guide and equipment. Follow the messages, tool calls and approval in [one successful trajectory](trajectories/automatic/happy_path/8a630de1-8972-4b01-8e22-60a90475c02e.json).

## Quick start

1. Install Python 3.11 or newer and `uv`. From the repository root, run `uv sync --locked`.
2. Copy [.env.example](.env.example) to `.env` and set `OPENAI_API_KEY` for the default model. Mock mode uses a fixed route catalog, simulated weather and a demo operator. Both agents still call the configured language model.
3. Run one automated hike. The simulator supplies the customer and manager replies.

```sh
uv run --env-file .env python -m app.simulation --scenario happy_path --mode mock --timeout 300 --peer-timeout 90
```

## Where to find reports

- **Published five-run result:** open [reports/automatic/000001/summary.md](reports/automatic/000001/summary.md).
- **Your new runs:** open `reports/automatic/`, choose the highest numbered folder (such as `000002`), then open `summary.md`. The CLI prints the exact path after the batch.
- Each report shows passed/failed checks, token usage, timings and links to individual trajectories. The same folder contains `summary.json` for machine-readable results.

## Repeat the evaluation

Run the happy path five times in sequence with the published batch settings. Model decisions may vary between runs.

```sh
uv run --env-file .env python -m app.simulation --scenario happy_path --mode mock --runs 5 --seed 42 --timeout 300 --peer-timeout 90
```

In the published five-run GPT-6 Luna batch, each hike used **42k–101k input tokens** and **0.8k–2.0k output tokens**, with averages of 62.4k and 1.25k respectively. About **90% of input tokens were served from cache** across the batch. Five runs used 312k input and 6.3k output tokens in total. These measured figures provide a budget reference; usage and cache hits vary between runs and providers. Cached tokens are included in input totals.

To run in parallel use:

```sh
--parallel
```

## Simulate a service failure

Simulate equipment-inventory timeouts with a 30% probability per request attempt, including retries.

```sh
uv run --env-file .env python -m app.simulation --scenario happy_path --mode mock --failure-tool check_equipment_inventory --timeout-probability 0.3 --seed 42 --timeout 300 --peer-timeout 90
```

To test permanent unavailability, replace the probability with the parameter below. Every attempt will time out, including retries.

```sh
--timeout-probability 1
```

The seed controls the injected failure sequence. After exhausted retries, the agents should end the trip gracefully. The original happy-path checks still expect a booking, so this failure experiment can return exit code 1. See the [failure-injection reference](docs/usage.md#execution-and-evidence) for supported behavior.

## Try a trip in the browser

```sh
uv run --env-file .env python -m app.simulation.web
```

The launcher opens the browser. Request a hike in the customer chat, then select a guide and approve or reject the proposal in the manager chat. The live trajectory shows how the agents reach a booking decision. The UI starts in **Real data** mode using Open-Meteo and the maintained route catalog. Select **Simulation** before starting a trip to use fixture data. By default the local operator demo supplies guides, equipment and reservations.

## Offline tests
Use `uv run pytest -q` to run the offline test suite.

## Further reading

- [Usage reference](docs/usage.md) covers model setup, scenario commands, the route catalog, terminal sessions, runtime logs and [repository-local Codex skills](docs/usage.md#repository-local-codex-skills).
- [Technical design](docs/technical-design.md) describes the agents, their tools and the booking rules.
- [Evaluation results](docs/evaluation-summary.md) document scenario outcomes and known failures.
