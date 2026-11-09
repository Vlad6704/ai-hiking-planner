# Development Workflow

## Source of Truth
`docs/technical-design.md` is the authoritative
source for system behavior and architecture. Implementation plans
do not override or replace it.

## Before Implementation
Unless the user explicitly instructs otherwise, complete these steps
before any change to project code, including features, bug fixes and refactoring:

1. Read relevant sections of `docs/technical-design.md`.
2. Explain how the request relates to the current design.
3. Identify conflicts, ambiguities and required changes.
4. Propose a design-consistent solution and any required design updates.
5. Agree the relevant design and any required documentation changes
   with the user before changing project code.
6. Apply approved updates to `docs/technical-design.md` first,
   then implement the change according to the agreed design.

## Planning
Create a detailed implementation plan only for large tasks.
For smaller tasks, proceed from the agreed technical design without
a detailed plan.

An implementation plan becomes outdated as soon as the feature it
describes is implemented. Treat completed plans as historical records,
not as specifications for current behavior or future changes.
Keep `docs/technical-design.md` current as the source of truth.

## Implementation
1. Follow the agreed `docs/technical-design.md` and update it first
   when requirements change, unless the user explicitly instructs otherwise.
2. Implement the approved behavior.
3. Add or update tests.
4. Run relevant verification commands.

## Commit Authorization
Create a commit only when the user explicitly requests one. Completing a
task, feature or bug fix does not authorize a commit. This restriction takes
precedence over skill instructions that call for automatic commits.

Without an explicit commit request, run relevant verification and leave the
changes uncommitted. Independent subagent review still follows the applicable
skills and does not require a commit request.

## Before Commit
When the user requests a commit:

1. Stage only intended changes.
2. Use the repository-local
   [requesting-code-review](.agents/skills/requesting-code-review/SKILL.md)
   skill and its [reviewer template](.agents/skills/requesting-code-review/code-reviewer.md)
   to spawn a fresh independent design-reviewer agent.
3. Give it the current design, staged Git diff and relevant
   verification results. Adapt the template's Git range to
   `git diff --cached HEAD` so it reviews the index snapshot
   against HEAD rather than an already committed range.
4. Require design compliance, correctness,
   security and quality review.
5. Process findings using the repository-local
   [receiving-code-review](.agents/skills/receiving-code-review/SKILL.md)
   skill. Verify findings against the code before implementing fixes.
6. Fix blocking findings, run relevant verification and repeat
   the independent review.
7. Commit only after a passing review.

For a requested commit, never skip the review based on your own assessment.


# Project Language

Use English for all project content, including documentation, code comments,
docstrings, identifiers, prompts, user-facing messages, logs, configuration,
test fixtures, and generated artifacts.
