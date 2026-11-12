# Evaluation summary

## Current model-backed results

On November 12, 2026, the six-scenario sweep passed **5/6** checks. Four
additional `guide_unavailable` runs then passed **4/4**. Across these two
batches, 9/10 runs passed; the guide scenario's combined result was 4/5.
The follow-up was selected after a failure, so this is a record of those
executions, not an unbiased estimate of production reliability.

Both batches used `openai:gpt-6-luna`, temperature 1, mock services, seed 42,
a 90-second peer timeout and a 300-second session timeout. Runs within each
batch executed concurrently in one process. No extra failure override was
applied; each scenario retained its authored conditions and fault behavior.
Mock mode still calls the real LLM provider.

| Scenario | Initial sweep | Additional runs | Initial outcome |
|---|---:|---:|---|
| `happy_path` | 1/1 | — | Confirmed |
| `bad_weather` | 1/1 | — | Confirmed on the suitable date |
| `external_service_failure` | 1/1 | — | Recovered and confirmed |
| `equipment_shortage` | 1/1 | — | Substitute accepted; confirmed |
| `hitl_rejection` | 1/1 | — | Revised terms approved; confirmed |
| `guide_unavailable` | 0/1 | 4/4 | Controlled failed trip; no booking |

The initial guide run failed because B described the revised terms in prose
without a complete structured `trip_offer`. Customer consent could not be
recorded for the offer. The run delivered a generic failure message and had
no runtime error. The later successes do not demonstrate that this failure
mode has been eliminated.

Local batch reports are `logs/fresh-six-20261112.jsonl` and
`logs/guide-four-retries-20261112.jsonl`. They record all ten outcomes, including
the failure and successes whose trajectories were not retained. Runtime logs
and these reports are ignored by Git.

## Retained trajectories

The checkout contains one selected successful automatic example per scenario.
The initial failed guide trace and three successful guide repetitions were
removed during cleanup. **The six selected successes are not a 6/6 sweep.**

These traces predate the pre-commit correction to B's booking-outcome decision
reference: outcomes after a customer decision contain a null `decision_message_id`
even though the decision message is recorded earlier. A deterministic regression
test now verifies that new outcomes carry the received decision's message ID.
Historical trajectories are preserved unchanged; no new paid runs were made for
this correction.

| Scenario | Successful example |
|---|---|
| `happy_path` | [Trajectory](../trajectories/automatic/happy_path/eff941d4-ba18-4f19-a347-20a7f7071a0e.json) |
| `bad_weather` | [Trajectory](../trajectories/automatic/bad_weather/6a880282-c8a2-4969-9c90-3afb5fef9543.json) |
| `external_service_failure` | [Trajectory](../trajectories/automatic/external_service_failure/1dfaaef2-3171-4599-8beb-b23bf176b881.json) |
| `equipment_shortage` | [Trajectory](../trajectories/automatic/equipment_shortage/9b7f151a-3579-4045-9f60-53294c6b8c8c.json) |
| `hitl_rejection` | [Trajectory](../trajectories/automatic/hitl_rejection/cba73f87-6b50-4f31-899f-82b7b6b6743a.json) |
| `guide_unavailable` | [Trajectory](../trajectories/automatic/guide_unavailable/11d8cbf4-8c45-4a99-9d8a-43b471ed5d30.json) |

The selected [manual real-mode trajectory](../trajectories/manual/4f6aae57-b3df-4979-906e-cc4d3c1bd37c.json) is included by explicit user request. It records a
confirmed trip using real weather and the catalog with a demonstration
operator. It contains an actual conversation and travel preferences. This is
a manual example, not an additional automated scenario measurement. Other
generated manual trajectories remain ignored by default.

## Reproduction

```sh
uv run --env-file .env python -m app.simulation --all --runs 1 --parallel --mode mock --peer-timeout 90 --timeout 300
uv run --env-file .env python -m app.simulation --scenario guide_unavailable --runs 4 --parallel --mode mock --peer-timeout 90 --timeout 300
```

Each invocation creates new run/request IDs and independent agent states.
Seed 42 controls the simulated environment, not LLM decisions. Repeating these
commands can produce different tool choices and outcomes. Evaluate every run,
including failures, rather than only selected successful examples.

## Scenario reliability

The historical 30-run inventory-fault experiment recorded a three-way tie:

| Scenario | Passed | Observed pass rate |
|---|---:|---:|
| `happy_path` | 5/5 | 100% |
| `bad_weather` | 5/5 | 100% |
| `equipment_shortage` | 5/5 | 100% |

That experiment used Luna at temperature 1, mock services, five concurrent
repetitions per scenario, inventory timeout probability 0.3, seed 1 and the
same 90/300-second timeouts. The other three scenarios each passed 4/5.
This ranking describes that historical implementation and small sample;
it is not a measured ranking of the current code. The original raw artifacts
are no longer retained. See the
[archived experiment](evaluation-history.md#thirty-concurrent-model-runs-with-inventory-faults).

## Limits of the evidence

- One initial run per scenario does not establish a stable success rate.
- The latest sweep does not verify five consecutive happy-path successes;
  earlier implementations had that result, recorded in the archive.
- Passing means all authored scenario checks passed, not just that a final
  message was delivered. A safe failed trip can fail a booking-success scenario.
- Guide-offer coordination remains a demonstrated intermittent failure.
- These automated runs use mock domain services and real model inference;
  they do not verify a production tour operator or restart durability.

Older model comparisons, token/cache measurements, fault-injection experiments
and migration checks remain in the [evaluation history](evaluation-history.md).
They are historical observations, not additional current-run evidence.
