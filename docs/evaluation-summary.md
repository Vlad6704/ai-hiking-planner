# Evaluation summary

## Latest five consecutive runs: identical business outcomes

After fixing mock-weather aliases, requiring the selected route, constraining
Happy Path to its requested date and accepting verified route-details evidence,
**all five sequential happy-path runs passed every scenario check**. This batch
used the uncommitted working tree after `7302019`, Luna at temperature 1, mock
services, seed 42, a 90-second peer timeout and a 300-second session timeout.
Start/end timestamps confirm the runs did not overlap.

Every run confirmed `PR-PNPE-2:long` on November 10, 2026 with guide Luis and
one rain jacket. Request and reservation IDs were distinct per run, as expected.
There were no runtime errors or weather-tool failures. The business fields
matched in all five; tool sequences and latency still varied. This sample does
not establish deterministic model behavior or a guaranteed future pass rate.

| Run | Passed | Seconds | Model calls | Trajectory |
|---:|---|---:|---:|---|
| 1 | Yes | 24.7 | 11 | [JSON](../trajectories/automatic/happy_path/8a630de1-8972-4b01-8e22-60a90475c02e.json) |
| 2 | Yes | 25.0 | 13 | [JSON](../trajectories/automatic/happy_path/d26a1fb5-1819-4f64-95bd-d30868303457.json) |
| 3 | Yes | 31.4 | 14 | [JSON](../trajectories/automatic/happy_path/71a0c1a0-eb83-4375-8366-38f7fd25d73a.json) |
| 4 | Yes | 27.4 | 16 | [JSON](../trajectories/automatic/happy_path/46b4ad0b-fc8a-4a35-bf84-334b1db471ca.json) |
| 5 | Yes | 43.1 | 22 | [JSON](../trajectories/automatic/happy_path/6f5d61cd-6f28-413b-94ef-1e30b73e7229.json) |

The complete local report is `logs/happy-path-five-fixed-date-20261112.jsonl`.
Only these latest five happy-path traces are included in this commit.
Earlier experimental happy-path batches remain local and ignored; their
outcomes below remain documented without publishing those JSON files.
The six scenario examples and manual trace from earlier commits are unchanged.

## Current offline corrections

After the latest model batch below, route evaluation was corrected to accept
successful search or exact route-details evidence, while rejecting error
results and still requiring the explicitly requested route ID. Happy Path now
allows only its expected date in the initial request, date answers and
proposal-bound consent. Other scenarios retain their date alternatives.
The five-run batch above validates these corrections. Previous trajectories
and their original verdicts remain unchanged. Offline verification passed
399 tests before that model batch.

## Latest mock-weather validation

After the mock-only location fix, five sequential explicit-route happy-path
runs all confirmed `PR-PNPE-2:long` with Luis and one rain jacket, with no
weather-tool failures or runtime errors. **The existing evaluator passed 3/5.**
Real-provider code was unchanged. Offline regression verification passed 397 tests.

| Run | Date | Evaluation | Trajectory |
|---:|---|---|---|
| 1 | November 10 | Pass | Local-only trace `db1972e8-bab0-4f5d-a639-3831392f8ff3` |
| 2 | November 10 | Pass | Local-only trace `9ea63679-2dac-44da-aa6b-ca0ce19d1c1c` |
| 3 | November 10 | Fail: route check requires search | Local-only trace `d138f845-5d24-4dcb-81b7-c2bfb5f88f28` |
| 4 | November 11 | Fail: expected November 10 | Local-only trace `67dc2449-64e5-4bef-9a7d-e4a42601b5db` |
| 5 | November 10 | Pass | Local-only trace `f7d5c082-a43d-4d90-be4a-d8833d2a5bae` |

Run 3 fetched the explicitly named route using `get_route_details`, without a
search call; runtime accepted the verified route, but the evaluator's route
check still required a search result. Run 4 received an explicit November 11
answer from the fixture's alternative-date rule while discussing another
route/area, then booked that allowed date. The fixture's fallback date was
inconsistent with this scenario's fixed expected date in that batch. Neither
issue was changed in the mock-weather-only fix; both were addressed afterwards
by the offline corrections above. These five results do not establish
identical dates across all runs. Local report:
`logs/happy-path-five-mock-aliases-20261112.jsonl`.

## Earlier six-scenario sweep

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

## Five consecutive happy-path runs

On November 12, 2026, revision `7302019` passed **5/5 consecutive happy-path
runs** in one process, with `--parallel` omitted. Recorded start/end timestamps
confirm the runs did not overlap. All five used Luna at temperature 1, mock
services, seed 42 and the same 90/300-second timeouts. Every scenario check
passed and no runtime error occurred. These earlier five trajectories remain local only.

| Run | Route variant | Seconds | Model calls | Trajectory |
|---:|---|---:|---:|---|
| 1 | `PR-PNPE-2:long` | 26.4 | 14 | Local-only trace `59eca78c-3abb-4d86-b61a-5b7500569271` |
| 2 | `PR-PNPE-2:long` | 18.4 | 12 | Local-only trace `02168b3a-22ef-482e-8f31-a8d370706559` |
| 3 | `PR-PNPE-2:long` | 20.3 | 13 | Local-only trace `44dcbc6e-4e9c-4212-87ee-43b03046f3d5` |
| 4 | `PR-PNPE-2:short` | 20.6 | 12 | Local-only trace `eaf5bf50-e2e9-43a2-bac0-5d9a4cbaa746` |
| 5 | `PR-PNPE-2:short` | 22.1 | 12 | Local-only trace `9ce4b798-26f4-409c-ac53-a4c7101ecee0` |

All five confirmed November 10, 2026 with guide Luis and one rain jacket.
The route differed: three long-loop and two short-loop bookings. These results
demonstrate consistent successful completion, not identical full business
outcomes or deterministic model behavior. Independent request/reservation IDs
are expected to differ. The local complete report is
`logs/happy-path-five-consecutive-20261112.jsonl`.

```sh
uv run --env-file .env python -m app.simulation --scenario happy_path --runs 5 --seed 42 --mode mock --peer-timeout 90 --timeout 300
```

## Explicit-route repeatability follow-up

The next five sequential runs used a revised happy-path fixture: its initial
message explicitly requests `PR-PNPE-2:long`, and `expected_route_id` makes the
evaluator reject another route. Real-mode date adaptation also retains that
explicit route requirement. This is an uncommitted change after revision
`7302019`, not a repeat of the unchanged earlier fixture. Model, temperature,
seed, services and timeouts remained the same.

**3/5 runs passed scenario checks; 4/5 created a confirmed reservation.** Every
confirmed reservation used the requested long loop. The first confirmed the
customer-accepted alternative date, November 11, instead of the scenario's
expected November 10; the second safely refused without a booking. The final
three confirmed November 10 with Luis and one rain jacket. There were no
runtime errors.

| Run | Scenario result | Business outcome | Seconds | Trajectory |
|---:|---|---|---:|---|
| 1 | Fail: expected date | Long loop, November 11, confirmed | 26.8 | Local-only trace `c27dc7c0-2fd9-423a-9d75-6740a089e4bd` |
| 2 | Fail: no booking | Controlled failed trip | 12.9 | Local-only trace `84424085-a433-4387-8ea8-995bafcc8a33` |
| 3 | Pass | Long loop, November 10, confirmed | 22.4 | Local-only trace `98ad08ed-8324-4d3e-b717-fa059007dcea` |
| 4 | Pass | Long loop, November 10, confirmed | 20.9 | Local-only trace `ce4e450d-162a-4f2c-bd4a-9efe85030481` |
| 5 | Pass | Long loop, November 10, confirmed | 20.4 | Local-only trace `57837358-119b-41be-861d-157db71947d7` |

Naming the route in the initial request exposed a mock-weather limitation:
queries such as `Lagos de Covadonga, Picos de Europa` or
`Picos de Europa, Asturias, Spain` returned `unsupported_forecast`. Some runs
recovered by using the supported `Picos de Europa` location; others moved to
another date or refused. Explicit route disclosure removed variation in booked
route identity, but did not establish five identical successful outcomes.
All five traces, including both failed evaluations, remain local only. The local
report is `logs/happy-path-five-explicit-route-20261112.jsonl`.

## Retained trajectories

Git retains one selected successful automatic example per scenario from the
earlier commit, plus only the latest five-run happy-path batch. The three
previous happy-path batches remain local and ignored. The initial failed
guide trace and three successful guide repetitions were removed during cleanup.
**The six selected successes are not a 6/6 sweep.**

The six selected examples in the table below predate the pre-commit correction
to B's booking-outcome decision reference: outcomes after a customer decision contain a null `decision_message_id`
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
- Earlier five-run batches had route/date variation or failed checks. The
  latest fixed-date batch passed 5/5 with matching business outcomes; five
  observations alone do not establish broad reliability.
- Passing means all authored scenario checks passed, not just that a final
  message was delivered. A safe failed trip can fail a booking-success scenario.
- Guide-offer coordination remains a demonstrated intermittent failure.
- These automated runs use mock domain services and real model inference;
  they do not verify a production tour operator or restart durability.

Older model comparisons, token/cache measurements, fault-injection experiments
and migration checks remain in the [evaluation history](evaluation-history.md).
They are historical observations, not additional current-run evidence.
