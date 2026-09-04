# Gate 8 — AutoInject End-to-End Injection Proof

Build SHA: `4a93dcb` (branch `brain/v2-omp-qualification`, based on `0129e235...`)
OMP: v18.1.10, `omp.exe`, loaded via `-e ./brainstem/prime-extension/src/index.ts`
SECOND_BRAIN_HOME: `.worktrees/v2-one-shot`, mode: `SECOND_BRAIN_AUTOINJECT_MODE=active`

## Sentinel

- Memory ID: `mem-736677e29a1a`
- Title: "OMP_V2_SENTINEL project fact"
- Fact: "The canonical build artifact staging directory for this specific qualification run is named zzq-vault-7719."
- Status: curated to `current`, grade `TESTED`, scope `project`, project `second-brain`.

## Positive test — session `2026-09-04T17-20-24-842Z_01a06d6f-970a-738c-a75f-5b7a85555713`

Prompt: "What is the name of the canonical build artifact staging directory configured for this project? ..."

Telemetry proof chain (exact records):

1. `brain_retrieval_attempt`: `candidate_count:1, eligible_count:1, project_id:"second-brain"`
2. `brain_packet_delivered`: `selected_ids:["mem-736677e29a1a"], packet_tokens:144, canonical_packet_hash:"1247440f..."`
3. `autoinject_shadow_decision`: `decision:"INJECT", mode:"active", result_patch:true, handler_returned_message:true, model_visible:true, delivery_id:"del-9676cdeb5b19f4307d1e53f8"`

This proves every required stage: memory exists -> retrieval considered it -> AutoInject built a packet -> the packet was actually attached as a message (`handler_returned_message:true`, `result_patch:true` -- not merely computed).

Secondary evidence (model transcript, NOT relied on alone): the model's own reply cited `mem-736677e29a1a` and the exact "zzq-vault-7719" value verbatim, and correctly applied the packet's own advisory-authority rule to refuse asserting it as unverified fact -- proof the packet reached the model's real context, not just telemetry.

## Negative test — session `2026-09-04T17-21-20-573Z_01a06d70-70bd-72bd-b95f-f65442fc37fd`

Prompt: unrelated ("reply with exactly: NEGATIVE_TEST_UNRELATED_OK")

Telemetry: `brain_retrieval_attempt candidate_count:0`, `brain_no_injection reason:"NO_RELEVANT_MEMORY"`, `autoinject_shadow_decision decision:"NO_INJECTION"`. The sentinel was NOT injected merely because it exists.

## Gate 8 Result: PASS

Both positive relevance and negative non-relevance behavior proven live, with full telemetry chain (not mocks, not CLI-only, not model-answer-only).
