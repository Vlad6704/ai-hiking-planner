# Graceful Failure Completion Implementation Plan

Source of truth: technical-design.md §8.1 Category D and §9 completion.

- [x] Add explicit exhausted-retry information to tool errors and instructions for B to stop repeating the failed operation and return failure to A, with A submitting the failed trip result. Test exhausted and recovered calls, and failed-result customer text with internal details retained.
- [x] Add bounded runtime final notification after agent cleanup for deadlock, timeout and exhausted step budget. Reserve terminal recording capacity. Cover verified booking, uncertain booking, no booking, already delivered message and notification failure. Preserve error verdict and causal evidence. Exercise browser/console compatibility.
- [x] Run focused and full tests. Run happy_path, equipment_shortage and guide_unavailable concurrently with inventory timeout probability 1, and check final customer delivery and absence of fabricated bookings. Record actual model-run results and limitations.

Model verification by root: happy_path (cfc28db7-323f-4e58-a542-dffcdfe440b8), equipment_shortage (a9acd515-33aa-42a8-84d8-7450871a0043), and guide_unavailable (a07a6178-d1b4-4ab1-af58-3c8a005fdc2b) ran concurrently with inventory timeout probability 1. Each delivered one generic failed-trip message, recorded three timeouts and zero bookings, and ended without a runtime error. Authored success-case evaluators correctly report failure because no booking was confirmed.

Final verification: `uv run pytest -q` passed 336 tests (13 existing dependency deprecation warnings). Focused lifecycle tests cover deadlock, timeout and step-limit delivery, finite event allowance, verified/uncertain booking state, failed notification, suppression of duplicate delivery, and generic browser error text. Scoped `git diff --check` passed. No commit or independent review was performed.
