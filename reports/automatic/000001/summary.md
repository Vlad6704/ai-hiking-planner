# Automated batch summary

Batch: 317f911a-2c8b-450f-87e7-d79118c4fd14

## Overall

### Primary metrics

| Metric | Result |
|---|---:|
| Scenario checks passed | 5 of 5 (100%) |
| Same successful trip result (happy_path) | 5 of 5 (100%) |
| Runtime errors | 0 |
| Average run time | 30.3 s |
| Median run time | 27.4 s |
| Longest run time | 43.1 s |
| Total input tokens | 311,968 |
| Average input tokens per run | 62,393.6 (from 5 runs) |
| Total output tokens | 6,254 |
| Average output tokens per run | 1,250.8 (from 5 runs) |
| Cached input tokens | 281,332 |
| Cache-write tokens | 30,408 |
| Input served from cache | 90.2% |
| Total model calls | 76 |
| Average model calls per run | 15.2 (from 5 runs) |

Token usage reported for all 5 runs.

### Sample size and coverage

| Metric | Result |
|---|---:|
| Planned runs | 5 |
| Reported runs | 5 |
| Runs with timing data | 5 |

### Diagnostic metrics

#### Execution outcomes

| Metric | Result |
|---|---:|
| Confirmed execution count | 5 |
| Controlled failed trip count | 0 |
| Runtime errors | 0 |
| Incomplete run count | 0 |
| Passed run count | 5 |
| Confirmed booking count | 5 |
| Booking confirmation rate | 5 of 5 (100%) |

#### Run accounting

| Metric | Result |
|---|---:|
| Started run count | 5 |
| Missing report count | 0 |
| Not started run count | 0 |

#### Successful run timing

| Metric | Result |
|---|---:|
| Runs with timing data | 5 |
| Average run time | 30.3 s |
| Median run time | 27.4 s |
| Longest run time | 43.1 s |

#### Unsuccessful run timing

| Metric | Result |
|---|---:|
| Runs with timing data | 0 |
| Average run time | Unavailable |
| Median run time | Unavailable |
| Longest run time | Unavailable |

#### Usage coverage

| Metric | Result |
|---|---:|
| Token usage reported calls | 76 |
| Cache read reported calls | 76 |
| Cache write reported calls | 76 |

#### Tool reliability

| Metric | Result |
|---|---:|
| Tool attempt count | 47 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Communication

| Metric | Result |
|---|---:|
| Agent message count | 19 |

#### Batch timing

| Metric | Result |
|---|---:|
| Batch wall time ms | Unavailable |

#### Scenario checks

Missing or inapplicable check results are excluded from both counts.

| Check | Passed | Failed |
|---|---:|---:|
| Booking confirmed | 5 | 0 |
| Expected date selected | 5 | 0 |
| Route matches requirements | 5 | 0 |
| Guide matches requirements | 5 | 0 |
| Booking matches approved proposal | 5 | 0 |
| Required agent communication completed | 5 | 0 |
| Execution stayed within limits | 5 | 0 |
| Final result delivered | 5 | 0 |
| Approval received before booking | 5 | 0 |
| No duplicate reservations | 5 | 0 |
| Tool attempts stayed within limits | 5 | 0 |
| Messages routed to correct participants | 5 | 0 |
| Weather suitable for selected trip | 5 | 0 |
| Required equipment included | 5 | 0 |

#### Agent A

| Metric | Result |
|---|---:|
| Total model calls | 46 |
| Average model calls per run | 9.2 (from 5 runs) |
| Total input tokens | 230,488 |
| Average input tokens per run | 46,097.6 (from 5 runs) |
| Total output tokens | 3,798 |
| Average output tokens per run | 759.6 (from 5 runs) |
| Cached input tokens | 208,164 |
| Cache-write tokens | 22,186 |
| Token usage reported calls | 46 |
| Cache read reported calls | 46 |
| Cache write reported calls | 46 |
| Input served from cache | 90.3% |

#### Agent B

| Metric | Result |
|---|---:|
| Total model calls | 30 |
| Average model calls per run | 6 (from 5 runs) |
| Total input tokens | 81,480 |
| Average input tokens per run | 16,296 (from 5 runs) |
| Total output tokens | 2,456 |
| Average output tokens per run | 491.2 (from 5 runs) |
| Cached input tokens | 73,168 |
| Cache-write tokens | 8,222 |
| Token usage reported calls | 30 |
| Cache read reported calls | 30 |
| Cache write reported calls | 30 |
| Input served from cache | 89.8% |

#### Search hiking routes

| Metric | Result |
|---|---:|
| Tool attempt count | 10 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Get weather forecast

| Metric | Result |
|---|---:|
| Tool attempt count | 8 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Get hiking equipment

| Metric | Result |
|---|---:|
| Tool attempt count | 6 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Get route details

| Metric | Result |
|---|---:|
| Tool attempt count | 6 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Check equipment inventory

| Metric | Result |
|---|---:|
| Tool attempt count | 6 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Check guide availability

| Metric | Result |
|---|---:|
| Tool attempt count | 6 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Create tour reservation

| Metric | Result |
|---|---:|
| Tool attempt count | 5 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

## happy_path

### Primary metrics

| Metric | Result |
|---|---:|
| Scenario checks passed | 5 of 5 (100%) |
| Same successful trip result (happy_path) | 5 of 5 (100%) |
| Runtime errors | 0 |
| Average run time | 30.3 s |
| Median run time | 27.4 s |
| Longest run time | 43.1 s |
| Total input tokens | 311,968 |
| Average input tokens per run | 62,393.6 (from 5 runs) |
| Total output tokens | 6,254 |
| Average output tokens per run | 1,250.8 (from 5 runs) |
| Cached input tokens | 281,332 |
| Cache-write tokens | 30,408 |
| Input served from cache | 90.2% |
| Total model calls | 76 |
| Average model calls per run | 15.2 (from 5 runs) |

Token usage reported for all 5 runs.

### Sample size and coverage

| Metric | Result |
|---|---:|
| Planned runs | 5 |
| Reported runs | 5 |
| Runs with timing data | 5 |

### Diagnostic metrics

#### Execution outcomes

| Metric | Result |
|---|---:|
| Confirmed execution count | 5 |
| Controlled failed trip count | 0 |
| Runtime errors | 0 |
| Incomplete run count | 0 |
| Passed run count | 5 |
| Confirmed booking count | 5 |
| Booking confirmation rate | 5 of 5 (100%) |

#### Run accounting

| Metric | Result |
|---|---:|
| Started run count | 5 |
| Missing report count | 0 |
| Not started run count | 0 |

#### Successful run timing

| Metric | Result |
|---|---:|
| Runs with timing data | 5 |
| Average run time | 30.3 s |
| Median run time | 27.4 s |
| Longest run time | 43.1 s |

#### Unsuccessful run timing

| Metric | Result |
|---|---:|
| Runs with timing data | 0 |
| Average run time | Unavailable |
| Median run time | Unavailable |
| Longest run time | Unavailable |

#### Usage coverage

| Metric | Result |
|---|---:|
| Token usage reported calls | 76 |
| Cache read reported calls | 76 |
| Cache write reported calls | 76 |

#### Tool reliability

| Metric | Result |
|---|---:|
| Tool attempt count | 47 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Communication

| Metric | Result |
|---|---:|
| Agent message count | 19 |

#### Scenario checks

Missing or inapplicable check results are excluded from both counts.

| Check | Passed | Failed |
|---|---:|---:|
| Booking confirmed | 5 | 0 |
| Expected date selected | 5 | 0 |
| Route matches requirements | 5 | 0 |
| Guide matches requirements | 5 | 0 |
| Booking matches approved proposal | 5 | 0 |
| Required agent communication completed | 5 | 0 |
| Execution stayed within limits | 5 | 0 |
| Final result delivered | 5 | 0 |
| Approval received before booking | 5 | 0 |
| No duplicate reservations | 5 | 0 |
| Tool attempts stayed within limits | 5 | 0 |
| Messages routed to correct participants | 5 | 0 |
| Weather suitable for selected trip | 5 | 0 |
| Required equipment included | 5 | 0 |

#### Agent A

| Metric | Result |
|---|---:|
| Total model calls | 46 |
| Average model calls per run | 9.2 (from 5 runs) |
| Total input tokens | 230,488 |
| Average input tokens per run | 46,097.6 (from 5 runs) |
| Total output tokens | 3,798 |
| Average output tokens per run | 759.6 (from 5 runs) |
| Cached input tokens | 208,164 |
| Cache-write tokens | 22,186 |
| Token usage reported calls | 46 |
| Cache read reported calls | 46 |
| Cache write reported calls | 46 |
| Input served from cache | 90.3% |

#### Agent B

| Metric | Result |
|---|---:|
| Total model calls | 30 |
| Average model calls per run | 6 (from 5 runs) |
| Total input tokens | 81,480 |
| Average input tokens per run | 16,296 (from 5 runs) |
| Total output tokens | 2,456 |
| Average output tokens per run | 491.2 (from 5 runs) |
| Cached input tokens | 73,168 |
| Cache-write tokens | 8,222 |
| Token usage reported calls | 30 |
| Cache read reported calls | 30 |
| Cache write reported calls | 30 |
| Input served from cache | 89.8% |

#### Search hiking routes

| Metric | Result |
|---|---:|
| Tool attempt count | 10 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Get weather forecast

| Metric | Result |
|---|---:|
| Tool attempt count | 8 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Get hiking equipment

| Metric | Result |
|---|---:|
| Tool attempt count | 6 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Get route details

| Metric | Result |
|---|---:|
| Tool attempt count | 6 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Check equipment inventory

| Metric | Result |
|---|---:|
| Tool attempt count | 6 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Check guide availability

| Metric | Result |
|---|---:|
| Tool attempt count | 6 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

#### Create tour reservation

| Metric | Result |
|---|---:|
| Tool attempt count | 5 |
| Failed tool attempt count | 0 |
| Tool retry count | 0 |
| Fallback attempt count | 0 |
| Successful fallback count | 0 |
| Tool failure rate | 0% |
| Fallback success rate | Unavailable |

## Run artifacts

- happy_path #1: [trajectory](<../../../trajectories/automatic/happy_path/8a630de1-8972-4b01-8e22-60a90475c02e.json>)
- happy_path #2: [trajectory](<../../../trajectories/automatic/happy_path/d26a1fb5-1819-4f64-95bd-d30868303457.json>)
- happy_path #3: [trajectory](<../../../trajectories/automatic/happy_path/71a0c1a0-eb83-4375-8366-38f7fd25d73a.json>)
- happy_path #4: [trajectory](<../../../trajectories/automatic/happy_path/46b4ad0b-fc8a-4a35-bf84-334b1db471ca.json>)
- happy_path #5: [trajectory](<../../../trajectories/automatic/happy_path/6f5d61cd-6f28-413b-94ef-1e30b73e7229.json>)

## Comparison details

### happy_path

Configuration fingerprint: `eed2885b8088579f76bfe3213c926b3a67ef257c023391b52b1dafc3826d7054`

| Status | Route | Date | Guide | Equipment | Runs |
|---|---|---|---|---|---:|
| confirmed | PR-PNPE-2:long | 2026-11-10 | luis | rain jacket | 5 |
