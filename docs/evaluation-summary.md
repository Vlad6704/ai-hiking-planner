# Baseline evaluation

## OpenAI GPT-6 Luna

Revision `855e338` used `openai:gpt-6-luna` through Chat Completions with reasoning effort `none`. The nine runs used mock providers, the same five fixture definitions, seed 42, a 180-second global deadline and a 90-second peer deadline. The five happy-path runs were consecutive in one CLI process. Each run received fresh graph threads, queues and booking state.

**9/9 runs passed all scenario checks.** Confirmed trips were delivered in 9/9 runs. The happy path passed 5/5 repetitions.

| Run | Case | Checks | Terminal outcome | Seconds | Model calls | Input / output tokens | Evidence |
|---:|---|---|---|---:|---:|---:|---|
| 1 | happy_path | Pass | confirmed | 27.4 | 15 | 27137 / 1588 | [JSON](../trajectories/luna-release/happy_path/e7efe192-9d9a-4118-b4cb-2cffbadc38c5.json) |
| 2 | happy_path | Pass | confirmed | 21.8 | 14 | 21517 / 1113 | [JSON](../trajectories/luna-release/happy_path/213ea2d8-28df-4fdf-a9ac-ab73d67df615.json) |
| 3 | happy_path | Pass | confirmed | 22.1 | 12 | 17585 / 1062 | [JSON](../trajectories/luna-release/happy_path/19cd3512-865f-4198-97e3-ca7896249afb.json) |
| 4 | happy_path | Pass | confirmed | 43.6 | 29 | 65281 / 2051 | [JSON](../trajectories/luna-release/happy_path/3deba861-3b07-4c22-a107-3c20bf38dced.json) |
| 5 | happy_path | Pass | confirmed | 20.0 | 12 | 17861 / 1040 | [JSON](../trajectories/luna-release/happy_path/1ff0caeb-0207-4605-b2b9-56daf29f262f.json) |
| 6 | bad_weather | Pass | confirmed | 24.2 | 14 | 23114 / 1295 | [JSON](../trajectories/luna-release/bad_weather/0f8d72a6-951f-41b8-974b-b13d91fd55da.json) |
| 7 | guide_unavailable | Pass | confirmed | 22.0 | 12 | 17510 / 1092 | [JSON](../trajectories/luna-release/guide_unavailable/15b04bb2-5200-47ff-b8a0-088263915314.json) |
| 8 | hitl_rejection | Pass | confirmed | 26.6 | 17 | 27872 / 1396 | [JSON](../trajectories/luna-release/hitl_rejection/71d574ff-bbce-43bb-8e0d-824e7d301ab5.json) |
| 9 | external_service_failure | Pass | confirmed | 24.6 | 14 | 21581 / 1114 | [JSON](../trajectories/luna-release/external_service_failure/29effd99-e12f-42d3-a875-3b8658981df0.json) |

One raw trajectory reported a failed approval-order check. The operator received fresh approvals for identical terms and retrieved the same reservation. The original evaluator compared the last approval with the first booking attempt. The corrected evaluator checks the approval in force at each attempt and was applied to all nine recorded event streams. The table shows the corrected verdicts. The original JSON retains its initial verdict. [Affected trajectory](../trajectories/luna-release/happy_path/3deba861-3b07-4c22-a107-3c20bf38dced.json)

## Observations

The representative successful trajectory records customer delivery at step 40. The completion event refers to that delivery ID. [Successful trajectory](../trajectories/luna-release/happy_path/e7efe192-9d9a-4118-b4cb-2cffbadc38c5.json)

The batch made 139 model calls, sent 24 peer messages and recorded 3 failed attempts out of 72 domain-tool attempts. Median elapsed time was 24.2 seconds. The simulator returned clarification on 3 of 43 recorded human responses.


The outage case recorded a successful read fallback with strategy `approved_snapshot` after bounded retries.

## Live integration check

The separate real-mode run at revision `26f939f` used Open-Meteo and HTTP requests to the stateless operator demo. Lifecycle outcome: completed. Scenario checks: passed. Terminal reason or trip status: confirmed. [Real-mode trajectory](../trajectories/luna-final-real/happy_path/d9b57f86-3f1c-48cc-9a27-83a1f5c61593.json)

## Earlier local-model baseline

Ollama `gemma4:26b` passed 6/9 runs at revision `b89e885`. The five happy-path repetitions all passed. The local run used different deadlines and preceded the peer-correlation fix. [Ollama trajectories](../trajectories/acceptance/)

## Next experiments

1. Compare typed proposal and reply payloads against the free-text exchange. An observed Luna diagnostic run exhausted the exchange limit after a peer notification left the first request pending. Keep the measured fixtures and count outstanding requests and peer sends.
2. Compare a smaller tool result projection against the current full route and forecast payloads. Use total input tokens, call count and scenario pass rate from the table to measure the effect.
3. Repeat the outage and rejection cases with additional failure schedules. Each has only one measured run in this batch.

The automated suite uses deterministic model doubles for offline end-to-end coverage. Hosted LangSmith trace ingestion was not exercised because no LangSmith credential was configured. The enabled tracing adapter, redaction and local JSON export have automated coverage.
