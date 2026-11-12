# Evaluation history (archived)

> Historical experiment notes, preserved on November 12, 2026. These results
> describe earlier code, models, fixtures and evaluators; they are not current
> system guarantees. Statements about future work, unavailable tracing,
> contracts and test counts apply only to their original experiment. The
> original local reports and trajectories were removed during cleanup.
> Missing artifact links below are preserved as text references, not evidence
> available in this checkout. See the [current evaluation summary](evaluation-summary.md).

## Scenario reliability

The three highest observed scenario pass rates in the historical
[30-run inventory-fault batch](#thirty-concurrent-model-runs-with-inventory-faults)
were tied:

| Scenario | Passed | Observed pass rate |
|---|---:|---:|
| `happy_path` | 5/5 | 100% |
| `bad_weather` | 5/5 | 100% |
| `equipment_shortage` | 5/5 | 100% |

That batch used Luna at temperature 1, mock providers, five repetitions of each
of six scenarios concurrently in one process, inventory timeout probability
0.3, seed 1, a 90-second peer timeout and a 300-second session timeout. The other
three scenarios each passed 4/5 runs. Success means passing the authored scenario
checks, not merely delivering a terminal message.

These are historical measurements on the implementation used for that batch,
not a guarantee or a fresh reliability measurement of the current system. Five
observations per scenario are a small sample, and reusing seed 1 does not sample
independent fault schedules. The table preserves previously recorded results;
the original batch report and trajectories were removed during local cleanup.
Selected successful trajectories alone must not be used to calculate pass rates.

## OpenAI GPT-6 Luna

Revision `855e338` used `openai:gpt-6-luna` through Chat Completions with reasoning effort `none`. The nine runs used mock providers, the same five fixture definitions, seed 42, a 180-second global deadline and a 90-second peer deadline. The five happy-path runs were consecutive in one CLI process. Each run received fresh graph threads, queues and booking state.

**9/9 runs passed all scenario checks.** Confirmed trips were delivered in 9/9 runs. The happy path passed 5/5 repetitions.

| Run | Case | Checks | Terminal outcome | Seconds | Model calls | Input / output tokens | Evidence |
|---:|---|---|---|---:|---:|---:|---|
| 1 | happy_path | Pass | confirmed | 27.4 | 15 | 27137 / 1588 | JSON (removed historical artifact: `../trajectories/automatic/happy_path/e7efe192-9d9a-4118-b4cb-2cffbadc38c5.json`) |
| 2 | happy_path | Pass | confirmed | 21.8 | 14 | 21517 / 1113 | JSON (removed historical artifact: `../trajectories/automatic/happy_path/213ea2d8-28df-4fdf-a9ac-ab73d67df615.json`) |
| 3 | happy_path | Pass | confirmed | 22.1 | 12 | 17585 / 1062 | JSON (removed historical artifact: `../trajectories/automatic/happy_path/19cd3512-865f-4198-97e3-ca7896249afb.json`) |
| 4 | happy_path | Pass | confirmed | 43.6 | 29 | 65281 / 2051 | JSON (removed historical artifact: `../trajectories/automatic/happy_path/3deba861-3b07-4c22-a107-3c20bf38dced.json`) |
| 5 | happy_path | Pass | confirmed | 20.0 | 12 | 17861 / 1040 | JSON (removed historical artifact: `../trajectories/automatic/happy_path/1ff0caeb-0207-4605-b2b9-56daf29f262f.json`) |
| 6 | bad_weather | Pass | confirmed | 24.2 | 14 | 23114 / 1295 | JSON (removed historical artifact: `../trajectories/automatic/bad_weather/0f8d72a6-951f-41b8-974b-b13d91fd55da.json`) |
| 7 | guide_unavailable | Pass | confirmed | 22.0 | 12 | 17510 / 1092 | JSON (removed historical artifact: `../trajectories/automatic/guide_unavailable/15b04bb2-5200-47ff-b8a0-088263915314.json`) |
| 8 | hitl_rejection | Pass | confirmed | 26.6 | 17 | 27872 / 1396 | JSON (removed historical artifact: `../trajectories/automatic/hitl_rejection/71d574ff-bbce-43bb-8e0d-824e7d301ab5.json`) |
| 9 | external_service_failure | Pass | confirmed | 24.6 | 14 | 21581 / 1114 | JSON (removed historical artifact: `../trajectories/automatic/external_service_failure/29effd99-e12f-42d3-a875-3b8658981df0.json`) |

One raw trajectory reported a failed approval-order check. The operator received fresh approvals for identical terms and retrieved the same reservation. The original evaluator compared the last approval with the first booking attempt. The corrected evaluator checks the approval in force at each attempt and was applied to all nine recorded event streams. The table shows the corrected verdicts. The original JSON retains its initial verdict. Affected trajectory (removed historical artifact: `../trajectories/automatic/happy_path/3deba861-3b07-4c22-a107-3c20bf38dced.json`)

## Observations

The representative successful trajectory records customer delivery at step 40. The completion event refers to that delivery ID. Successful trajectory (removed historical artifact: `../trajectories/automatic/happy_path/e7efe192-9d9a-4118-b4cb-2cffbadc38c5.json`)

The batch made 139 model calls, sent 24 peer messages and recorded 3 failed attempts out of 72 domain-tool attempts. Median elapsed time was 24.2 seconds. The simulator returned clarification on 3 of 43 recorded human responses.


The outage case recorded a successful read fallback with strategy `approved_snapshot` after bounded retries.

## Live integration check

The separate real-mode run at revision `26f939f` used Open-Meteo and HTTP requests to the stateless operator demo. Lifecycle outcome: completed. Scenario checks: passed. Terminal reason or trip status: confirmed. Real-mode trajectory (removed historical artifact: `../trajectories/automatic/happy_path/d9b57f86-3f1c-48cc-9a27-83a1f5c61593.json`)

## Earlier local-model baseline

Ollama `gemma4:26b` passed 6/9 runs at revision `b89e885`. The five happy-path repetitions all passed. The local run used different deadlines and preceded the peer-correlation fix. [Ollama trajectories](#ollama-run-artifacts)

## Next experiments

1. Compare typed proposal and reply payloads against the free-text exchange. An observed Luna diagnostic run exhausted the exchange limit after a peer notification left the first request pending. Keep the measured fixtures and count outstanding requests and peer sends.
2. Compare a smaller tool result projection against the current full route and forecast payloads. Use total input tokens, call count and scenario pass rate from the table to measure the effect.
3. Repeat the outage and rejection cases with additional failure schedules. Each has only one measured run in this batch.

The automated suite uses deterministic model doubles for offline end-to-end coverage. Hosted LangSmith trace ingestion was not exercised because no LangSmith credential was configured. The enabled tracing adapter, redaction and local JSON export have automated coverage.

## Ollama run artifacts

- bad_weather: a39b7657-bfce-43e7-a1c5-49427f569370 (removed historical artifact: `../trajectories/automatic/bad_weather/a39b7657-bfce-43e7-a1c5-49427f569370.json`)
- external_service_failure: eb1c73b5-c6fc-4f74-a9d6-22a77fa881bc (removed historical artifact: `../trajectories/automatic/external_service_failure/eb1c73b5-c6fc-4f74-a9d6-22a77fa881bc.json`)
- guide_unavailable: f7523298-cbe6-43d3-8226-9be17ac68232 (removed historical artifact: `../trajectories/automatic/guide_unavailable/f7523298-cbe6-43d3-8226-9be17ac68232.json`)
- happy_path: 3bf946f2-17e3-4b37-985d-04a5cc6a3f67 (removed historical artifact: `../trajectories/automatic/happy_path/3bf946f2-17e3-4b37-985d-04a5cc6a3f67.json`)
- happy_path: 4663f3ac-1876-4709-b3e2-d362041a151f (removed historical artifact: `../trajectories/automatic/happy_path/4663f3ac-1876-4709-b3e2-d362041a151f.json`)
- happy_path: 49524fd2-a345-47d0-903f-1d8f91e15a4d (removed historical artifact: `../trajectories/automatic/happy_path/49524fd2-a345-47d0-903f-1d8f91e15a4d.json`)
- happy_path: 5c601278-0cf7-49b5-a5cb-1351d7dd011f (removed historical artifact: `../trajectories/automatic/happy_path/5c601278-0cf7-49b5-a5cb-1351d7dd011f.json`)
- happy_path: 6de7db84-0dc6-4299-8f21-6105d6ff38fb (removed historical artifact: `../trajectories/automatic/happy_path/6de7db84-0dc6-4299-8f21-6105d6ff38fb.json`)
- hitl_rejection: 48adc0ef-d73c-4520-911f-5df41333a4a9 (removed historical artifact: `../trajectories/automatic/hitl_rejection/48adc0ef-d73c-4520-911f-5df41333a4a9.json`)

## Parallel retrieval validation — November 11, 2026

Sol was run with mock services and real model inference using:

```sh
uv run --env-file .env python -m app.simulation --all --mode mock --peer-timeout 90 --timeout 300
```

All six cases passed. The table compares the immediately preceding successful
sequential executions with one new batch-enabled execution per case. Earlier
reference runs were collected individually at different times and include
different model decisions. These observations do not establish repeatability
or isolate concurrency from model/provider latency.

| Scenario | Sequential model calls | Batched model calls | Sequential seconds | Batched seconds |
|---|---:|---:|---:|---:|
| bad_weather | 17 | 13 | 53.4 | 40.5 |
| equipment_shortage | 20 | 15 | 60.0 | 43.5 |
| external_service_failure | 17 | 13 | 49.9 | 35.6 |
| guide_unavailable | 26 | 27 | 80.0 | 81.4 |
| happy_path | 16 | 11 | 44.0 | 28.5 |
| hitl_rejection | 23 | 17 | 70.5 | 42.1 |
| Total | 119 | 96 | 357.8 | 271.6 |

In guide_unavailable, B decreased from 11 to 10 model calls while A increased
from 15 to 17. Each case recorded at least one multi-tool response for each
agent. Per-agent evaluation metrics expose this as parallel_tool_batches.

New local trajectory IDs, in table order: 898eed52-6c65-4e63-b52d-9251c982ec47,
61e50acf-86a9-460f-bf93-1de7148c406b, 8d3e0d99-61c2-4a9c-bd07-1b8d1c52d0c2,
e19899c4-6131-4430-b2a9-848576cf3ae3, 5939e177-4c7f-479b-83b4-12e7105db349,
710aa815-b644-4660-9bdf-73bfcd5e73fe. Local runs remain ignored by Git.

## Deterministic customer fixture validation — November 11, 2026

After updating compound-question matching and adding explicit route/date/party
answers, all six mock CLI scenarios passed on Sol with 90-second peer and
300-second overall deadlines. Each reported human_matching_failure_rate=0.
After review, the three substitution scenarios were repeated with proposal-bound
fixture decisions and also passed. The final offline suite passed 249 tests.

For guide_unavailable, the previous recorded run e19899c4-6131-4430-b2a9-848576cf3ae3
had eight customer questions, 27 model calls and 81.4 seconds. The new run
3408c17d-09ce-4d2b-9679-f5708f1c524b had three customer questions, 20 model calls
(A=11, B=9), zero clarification replies and 50.5 seconds. These are individual
executions with potentially different model decisions, not repeatability data.

The fixtures now explicitly prefer PR-PNPE-2:long. Deterministic matching remains
scoped to the six authored cases; arbitrary natural-language dialogue is not
covered by these results.

## Luna temperature 1 comparison — November 11, 2026

Ran all six mock cases with real Luna inference, explicit temperature=1,
90-second peer and 300-second overall limits. Four cases passed in this run.

| Scenario | Passed | Model calls |
|---|---|---:|
| bad_weather | True | 13 |
| equipment_shortage | False | 16 |
| external_service_failure | True | 10 |
| guide_unavailable | True | 21 |
| happy_path | True | 16 |
| hitl_rejection | False | 14 |

Equipment shortage ended in deadlock after an incomplete substitution offer,
an informational customer message and local acknowledgement. HITL rejection
ended in a controlled refusal: the fixture rejected PR-PNPE-2:short because
its configured preference is PR-PNPE-2:long. These are individual observations,
not model reliability estimates.

### Luna HITL follow-up

After removing enforcement of an unspoken fixture route preference, a repeat
of hitl_rejection with Luna temperature=1 passed all checks on PR-PNPE-2:short.
Trajectory: 9e22dc8a-b92e-4e7c-ac2e-2261b976e31a. It used 17 model calls and
45.4 seconds with the same 90/300 limits. The fixture uses the original
operational proposal's route unless it has actually stated its route preference.
The full offline suite passed 251 tests. The earlier six-case results remain
historical; this follow-up reran only hitl_rejection.

### Luna equipment-shortage follow-up

After making guide selection and structured substitution steps explicit in the
agent instructions, equipment_shortage passed with Luna temperature=1.
Trajectory a599b0da-59bd-42a9-8606-990f25abd88d contains customer consent,
fresh manager approval and one poncho reservation, with no local
acknowledgements or turn-error replies. It used 14 model calls and 29.9 seconds.
Focused regression verification passed 18 tests. This is one successful repeat,
not a repeated reliability measurement.

## Compact route content — November 11, 2026

Model-facing route search now returns summaries and keyword excerpts. Full
original results remain in SQLite, runtime observations and trajectory events.
Selected-route details omit the redundant full_text aggregate. The planner is
instructed to select a candidate before expanding its details.

Validation used Luna temperature=1, mock services and 90/300-second limits.
The first intermediate batch passed five cases. Equipment shortage expanded all
nine route candidates, prompting a clarification to fetch selected candidates
rather than exhaust the list. Guide unavailability failed with an acknowledgement
deadlock. The final batch below also passed five cases; guide_unavailable again
ended after A acknowledged B's message without continuing the active task.

| Scenario | Previous input tokens | Compact input tokens | Compact passed |
|---|---:|---:|---|
| bad_weather | 60,513 | 40,117 | True |
| equipment_shortage | 78,675 | 54,988 | True |
| external_service_failure | 32,902 | 35,524 | True |
| guide_unavailable | 154,850 | 73,442 | False |
| happy_path | 56,264 | 46,764 | True |
| hitl_rejection | 78,793 | 61,863 | True |

For the five completed successful cases, input totals changed from
307,147 to 239,256 (22.1 percent lower). The failed guide case
is excluded because early termination makes its total incomparable.
These are individual model executions with differing tool choices, not a
controlled reliability or latency estimate.

The full offline suite passed 256 tests. Dedicated checks verify actual compact
ToolMessage content, keyword excerpts, degraded status, missing-route errors,
and original trace/observation preservation. Independent review found no
blocking projection issue.

## Cache usage validation — November 11, 2026

One happy_path run on Luna temperature=1 with mock services passed all scenario
checks. Trajectory 84dd428c-f594-434d-a358-b93b8eaf2324 reports all 13 calls with
cache-read and cache-write data.

| Scope | Input tokens | Cache reads | Cache writes | Cached-input share |
|---|---:|---:|---:|---:|
| Agent A | 32,992 | 29,984 | 2,984 | 90.88% |
| Agent B | 11,030 | 10,058 | 957 | 91.19% |
| Total | 44,022 | 40,042 | 3,941 | 90.96% |

Output tokens totaled 1,237. Cache reads and writes are contained in input
usage. The remaining 39 input tokens are outside those categories. No monetary
cost is inferred. Old reports omitted cache details, so their actual cache
usage cannot be reconstructed from aggregate input/output counts.
One unsupported weather-date query was rejected and the planner recovered.
Focused observability, evaluation and graph tests passed 29 cases.

## Short reservation codes and runtime-bound results — November 11, 2026

The model-facing completion tool now accepts TripSubmission business fields.
Runtime builds TripResult with the active request ID and verified receipt ID,
validates exact terms and renders the final message. Mock and bundled demo
codes use TR-XXXXXXXX with process-local collision checking and stable reuse
per request. External receipt identifiers pass through unchanged.

The final offline suite passed 277 tests, including collision retries,
thread-safe issuance, HTTP-demo reuse, missing model ID fields, runtime-generated
confirmation text, external receipt preservation and rejection of altered
business fields.

A Luna temperature=1 mock batch with 90/300 limits passed equipment_shortage,
external_service_failure, guide_unavailable, happy_path and hitl_rejection.
Each produced a short-code confirmation with no receipt-copy mismatch.
The bad_weather run eb0212fd-6f7f-464b-8a33-a8fc87491261 failed the scenario:
the model requested weather for 'Lagos de Covadonga, Picos de Europa' rather
than the supported 'Picos de Europa', then issued a controlled refusal.
This result is retained; the batch is five of six, not a six-case pass.
Independent review found no blocking code issue; outdated completion-contract
paragraphs identified by the reviewer were updated.

## Configurable failure injection validation — November 12, 2026

The CLI and browser expose a mock-only tool timeout override and seed. The full
regression suite passed 321 tests. API tests cover validation, mock settings
round-trip, real-mode rejection, and concurrent failure-schedule isolation.
Graph tests cover transient recovery and controlled failure. Browser JavaScript
passed a syntax check; visual browser rendering was not inspected in this change.

Two additional Luna model runs exercised the CLI overrides:

| Override | Outcome | Local trajectory |
|---|---|---|
| Inventory timeout probability 0.3, seed 1 | One injected timeout, successful retry, confirmed booking, scenario passed | `trajectories/automatic/happy_path/813774e5-d599-4ada-9d48-f35baafa8ea2.json` |
| Weather timeout probability 1, seed 42, no fallback | Controlled failed trip delivered, no reservation, no runtime error | `trajectories/automatic/happy_path/b18024db-ceb3-4d7c-bcbd-0b4558052f6a.json` |

The second run fails the authored happy-path evaluation because that case expects
a confirmed booking. It verifies safe handling of a deliberately unavailable
dependency. The model initiated seven forecast operations, each exhausting three
attempts, for 21 timeouts. Retry bounds apply per operation; the model can initiate
another operation. Effective failure rules and seeds are present in both traces.

### Thirty concurrent model runs with inventory faults

Ran `--all --parallel --runs 5 --mode mock --failure-tool check_equipment_inventory
--timeout-probability 0.3 --seed 1 --peer-timeout 90 --timeout 300` in one process.
All 30 runs encountered an inventory timeout; all 30 affected operations recovered
on retry. The same seed was deliberately reused for each run, so these repetitions
exercise model variation under a repeatable fault sequence rather than estimate
the timeout probability empirically.

| Scenario | Passed |
|---|---|
| happy_path | 5/5 |
| bad_weather | 5/5 |
| equipment_shortage | 5/5 |
| external_service_failure | 4/5 |
| guide_unavailable | 4/5 |
| hitl_rejection | 4/5 |

Overall, 27/30 passed their authored scenario checks. One external-service case
confirmed November 11 instead of the expected November 10. One rejection case
closed on customer refusal before reaching the intended manager rejection.
One guide-shortage case stalled when B described an offer only in prose and A
acknowledged the message. Inventory retry recovery succeeded in each case.
Local batch reports are in
`logs/failure-batch-05ebd4cf-7dbb-438a-8b40-aa3553e43e1c.jsonl`.

### Graceful termination under permanent inventory failure

After adding explicit exhausted-retry information and final customer delivery,
three Luna mock scenarios ran concurrently with inventory timeout probability
1 and seed 1. Each ended with a failed trip, no runtime error, exactly three
inventory timeouts, no booking and one delivered customer message:
"We couldn't complete your request. Please try again later."

| Scenario | Local run ID |
|---|---|
| happy_path | cfc28db7-323f-4e58-a542-dffcdfe440b8 |
| equipment_shortage | a9acd515-33aa-42a8-84d8-7450871a0043 |
| guide_unavailable | a07a6178-d1b4-4ab1-af58-3c8a005fdc2b |

These are controlled failed trips. Their authored scenario evaluations still
expect confirmed bookings and therefore remain failed. The runtime safety
notification path is covered separately by lifecycle tests, since these three
model runs ended through A's normal failed-result submission.

## Isolated agent state migration — November 12, 2026

Agent business facts now live in separate checkpointed states. Typed messages
are the only peer fact exchange. The final regression suite passed 364 tests.
Coverage includes private-state reconstruction, deduplicated inbox/outbox,
parallel observation merging and safe handling of a lost booking response.

The migrated architecture passed all six normal scenarios concurrently and
five happy_path runs consecutively on Luna. These model runs preceded the final
reservation replay-protection refinements, which were covered by the final
full suite. Batch reports are retained locally in
`logs/isolated-state-model-0ecffa58-7c42-409f-953c-0b643e98f735.jsonl` and
`logs/isolated-state-sequential-80c6f562-4e40-4e8b-b964-42e0ac417cd4.jsonl`.

Three further concurrent model runs with permanent inventory timeouts
(happy_path, equipment_shortage, guide_unavailable) each ended with a failed
trip, no runtime error and one generic final customer message. Their authored
booking-success checks remain failed, as expected for this outage experiment.
Reports are in `logs/isolated-state-outage-24f47b83-4229-40d0-afed-63c496ba2716.jsonl`.

No database-backed saver or production broker was introduced. Reconstructing a
driver against the same saver is tested; process termination still loses V1's
in-memory persistence. See the isolated-agent-state implementation plan for
the completed steps and explicit implementation decisions.
