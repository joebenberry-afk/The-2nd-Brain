# Release remains HOLD

Draft PR:https://github.com/can1357/oh-my-pi/pull/10928. Host patch:874fe1f20bc5f906812ff52c0a6a5698a59c191e. Brain source:1099eb37b01f282365922b337a6069e31692b2cd.

## Host full-suite limitation

The complete coding-agent suite timed out after900s with58 observed failures. The first run inherited installed-extension environment; it is not a clean isolated full-suite result. A follow-up with isolated PI_CODING_AGENT_DIR and Brain observability disabled passed the context-promotion scenario but reproduced Windows EBUSY in settings-reload cleanup. No unrelated upstream test/code changes were made. Clean upstream CI/platform verification remains required; PR is a draft.

## Dispatch-binding qualification risk

Additional native producer audit: task/index.ts:866-873 emits progress.id=agentId;903-914 exposes only the primary async.jobId. Registration at1252-1255 requests id=agentId, but the manager can disambiguate collisions. The delivery contract correctly distinguishes jobId and agentId; the Brain observer deliberately requires its pending key to match jobId and never falls back to agentId or rendered text. Therefore a collision-suffixed jobId with no corresponding dispatch binding remains pending rather than being falsely attributed. The synthetic observer tests prove distinct metadata identity handling, not exhaustive native spawn binding under collisions. Before natural qualification, prove native per-dispatch job-ID binding (including batches/collisions) or obtain a reviewed contract adjustment. Do not silently broaden the minimal upstream patch or relax unknown-job rejection.

## Explicitly not executed

No default candidate deployment, patched OMP installation/restart, provider calls, natural-worker burn-in, Gate22/23, paired provider economics, whole-workflow token qualification, or v2.0.0 tag. Installed stock18.1.10 is not qualified for automatic structured receipts.

## Next prerequisites

1. Clean upstream host validation and reviewed/released structured contract.
2. Resolve/prove native collision/batch dispatch binding while retaining strict job-ID ownership.
3. In a separately authorized qualification pass, install exact host and Brain candidate, restart flag-free, verify byte-exact deployment/rollback, then perform the plan's live gates.

Local Brain offline gates are proven; they do not replace any of these production gates.
