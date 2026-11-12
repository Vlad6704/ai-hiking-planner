# Equipment shortage implementation plan

Design: [Technical design](../../technical-design.md).

1. Add equipment_shortage with unavailable jackets, available ponchos and scripted customer answers.
2. Implement the B → A → customer substitution decision and enforce availability and consent before manager approval. Share this flow with manager-requested substitutions.
3. Exercise acceptance and refusal through the actual graph. Verify no booking or manager approval for a declined substitute.
