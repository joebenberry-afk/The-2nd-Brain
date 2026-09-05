# Current-context preservation

## Defect and narrow fix

The starting `context` hook returned `previousRenderedView` on a no-breakpoint event without proving it matched the current messages. The isolated regression in `artifacts/worker-paging-before.json` reproduced loss of appended user/tool content.

The candidate removes the prior rendered-array cache. With no breakpoint the hook returns `undefined`, leaving the host's **current** message sequence untouched. At a real breakpoint, the existing pager processes the current event. No replacement cache, content fingerprint or session-keyed shadow transcript was introduced.

## Executed evidence

`artifacts/vitest-final-source.json`: **684 passed, zero failed/skipped**. Relevant named contracts include:

- `audited closeout retains appended and same-length current messages after a cached paging view`: preserves new user requirements, assistant tool calls, corresponding current tool results, and same-length replacement content.
- `test_paging_skipped_when_no_break_point` and `test_model_switch_preflight_order`: retain existing boundary/preflight behavior.
- `current-turn pin window respected`: eligible-looking recent content is not paged.
- `fail-open on a simulated vmem-list failure`, throwing-list failure, and claim failure: no replacement of original messages.
- Existing page budget, max-page cap, lost-claim race, proof-backed reprojection and double-wrap protection tests pass.
- `audited closeout retains pending correlation across native compaction events` passes for worker recovery bookkeeping; it is not claimed as live compaction/canary proof.

Removing the cross-event array eliminates that stale-view path across session and model changes as well. The model preflight and pager guardrail tests are offline behavioral evidence; no fresh native session/model-switch/compaction sequence is claimed here. Those candidate-specific integration rows remain open in `11-final-candidate-regression.md`.

No compaction durability barrier was disabled and no requirement/pin window was relaxed. Source: `brainstem/prime-extension/src/index.ts`; regression: `brainstem/prime-extension/tests/wiring.test.ts`.
