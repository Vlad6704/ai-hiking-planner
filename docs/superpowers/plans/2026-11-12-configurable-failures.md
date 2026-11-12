# Configurable Mock Failures Implementation Plan

Design authority: technical-design.md §8.2. Use existing FailureSchedule.

- [x] Add a validated mock timeout override and shared application helper. Test probability boundaries, unsupported tools, fixture precedence and isolation. Persist effective rules and seed in trace metadata.
- [x] Add CLI failure-tool/timeout-probability options. Require both, reject real mode and invalid values before execution. Preserve seed and parallel behavior. Add CLI regression tests.
- [x] Add browser selector, percentage and seed controls in session conditions. Expose supported tools through config, validate StartRequest, reject real-mode overrides, lock fields during a session and retain selected values in snapshots. Test API behavior and session isolation.
- [x] Document CLI example and UI usage in README. Run focused tests and full pytest. Verify transient timeout retry recovery and exhausted attempts producing a controlled failure through existing graph entry points. Record actual evidence, including limitations.

Verification: 321 tests passed, including seeded per-attempt reproducibility and isolation, CLI validation, browser API rejection/round-trip, actual-graph retry recovery and controlled exhausted failure. Browser JavaScript syntax passed via Node vm.Script. Visual browser rendering was not inspected. Paid Luna runs performed by root confirmed inventory p=0.3 seed=1 recovered after one timeout and booked (813774e5-d599-4ada-9d48-f35baafa8ea2); weather p=1 with no fallback ended with a delivered failed trip and no reservation (b18024db-ceb3-4d7c-bcbd-0b4558052f6a). The latter repeated seven forecast operations (21 attempts) before terminating, so bounded per-operation retries do not eliminate repeated agent-level requests.
