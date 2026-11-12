# Customer Decisions on Revised Offers Implementation Plan

> For agentic workers: Use the repository's executing-plans or subagent-driven-development skill when implementation is requested. Track steps with the checkboxes below.

**Goal:** Let Agent A interpret a customer's reply and return the decision to B for the exact offer the customer saw.

**Architecture:** Use the existing structured offer, human interrupt and peer queue. Bind the customer's response to the offer in runtime state. Give A a single tool to record and deliver its interpretation.

**Tech stack:** Python, LangChain tools, LangGraph interrupts, pytest.

**Spec:** [Technical design §4.4](../../technical-design.md#customer-decision-on-a-revised-offer).

## Global constraints

Use the same decision path in manual and automated sessions. Keep manager approval separate from customer acceptance. Preserve the customer's original words in the trajectory.

## Review focus

Exercise a free-form reply, a changed date, a superseded offer, a queue delivery failure and a duplicate tool call.

### Task 1. Bind a customer reply to the current offer

- [x] In `tests/test_substitution_safeguards.py`, add cases for ordinary questions, replies to the current structured offer and replacement by a new offer. Assert that receiving “Sounds good to me” preserves the text and response event ID without creating a consent decision. Cover both manual and simulated replies.
- [x] Run `uv run pytest tests/test_substitution_safeguards.py` and confirm the new assertions expose the existing reply-time classification.
- [x] In `app/simulation/runner.py`, update `human_reply` to retain the response event and its offer identity. Remove the regex classification. Clear the prior reply when an offer is replaced. Keep unmatched simulator clarification pending.
- [x] Rerun the focused tests and adapt existing assertions that expected consent immediately after the interrupt.

### Task 2. Record and send A's decision in one tool call

- [x] In `tests/test_substitution_safeguards.py` and `tests/test_agents.py`, test A-only tool exposure, both decisions, missing or stale reply, failed delivery, duplicate invocation and conflicting second decision. Verify ordinary peer messages cannot mark consent as returned.
- [x] Run `uv run pytest tests/test_substitution_safeguards.py tests/test_agents.py` and verify the missing tool or decision state causes the new cases to fail.
- [x] Implement `reply_with_customer_decision(decision: Literal["accepted", "declined"])` in `app/agents/tools.py`. Use the current offer and reply retained by Task 1. Use the existing bus correlation rules. Remove the implicit decision side effect from `send_to_agent`. In `app/simulation/runner.py`, link the decision and queue receipt to the reply. A failed send must leave manager approval blocked and allow retry. Repeating a successful call returns its receipt without sending twice.
- [x] Update prompts in `app/agents/factory.py`. B sends complete verified alternatives for date, route and equipment changes. A requests a missing proposal, asks with the structured offer, interprets the reply, clarifies ambiguity or requests revised terms. Rerun the focused tests.

### Task 3. Verify the conversation and its evidence

- [x] Update the scripted agents in `tests/test_integration.py` and the equipment cases in `tests/test_equipment_shortage.py`. Exercise free-form acceptance, refusal, clarification and “Yes, but on the 12th.” Assert that only an accepted current offer can reach approval. Add a guide-shortage regression where B initially supplies only prose, A requests the full offer and booking succeeds on the agreed alternative date.
- [x] In `tests/test_evaluation.py`, exercise a decision linked to the wrong customer reply and a decision sent after approval. Both must fail evaluation. Run the affected tests to establish which existing checks miss these cases.
- [x] Update `app/evaluation/checks.py` to verify the causal chain from offer through customer reply, A's decision, delivery to B and manager approval. Keep authored simulator replies distinct from the agent's decision in test fixtures.
- [x] Run `uv run pytest -q`. Then run each of `guide_unavailable`, `equipment_shortage` and `hitl_rejection` with `uv run --env-file .env python -m app.simulation --mode mock --scenario <name>`. Inspect the new trajectories for the correct offer, original reply, single decision and booking after approval.

Validation completed with 300 passing tests. Luna mock runs passed for equipment shortage (279cd408-1ff5-4d4b-9b02-56ffcff55691), manager rejection (3bcb2c49-81d0-4689-bd32-8e79900b7df7) and guide shortage (f08beb2e-d3d9-4912-baa3-53fb21dbaeef). The successful guide run used `--peer-timeout 90 --timeout 300` after a default-deadline attempt ended with `peer_timeout`. Earlier guide attempts remain available, including an immediate alternative-date selection and an attempt blocked by missing alternative-date weather. The latter prompted an explicit changed-date forecast/equipment reminder in A's prompt.
