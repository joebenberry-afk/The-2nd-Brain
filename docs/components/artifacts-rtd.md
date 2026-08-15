# Artifacts / RTD (Raw Tool Data)

## Purpose
Persist exact tool output verbatim and produce deterministic distilled summaries so large results never leave context unrecoverable (plan §20-21, §101; Phase 5 shadow).

## Problem it solves
Oversized output would bloat context; lossy truncation loses evidence. Store exact bytes content-addressed, put a deterministic summary in context, keep a recovery handle.

## Responsibilities
- Python `artifacts.py`: `store_text`/`store_file` → `state/artifacts/blobs/<sha256>.bin` + `meta/<sha256>.json` `{v:1, hash, size, created_at, kind, tool, session}`; atomic (blob then meta); idempotent re-store; sha256-collision guard (never overwrite). `expand(hash_or_prefix)`: full hash or unique prefix ≥8 hex; ambiguous → BrainError listing candidates; unknown → BrainError. `list_artifacts` (newest first). Distillers (pure/deterministic): `distill_pytest` (counters, ≤10 FAILED/ERROR lines, generic fallback), `distill_git` (count + first 50 subjects), `distill_generic` (line/byte counts + head/tail); `distill(text, kind, max_chars=2000)` routes pytest/git else generic. Handles: `[brain-artifact:sha256:<hash>]` + `Full output recoverable: /brain-expand <hash[:12]>`.
- TS `rtd.ts` (shadow): decides whether a bash result would distill — size > threshold (env `SECOND_BRAIN_RTD_THRESHOLD` → `config/context.toml [rtd] threshold_chars` → default 8000) and command prefix in {pytest, git, rg, grep}; writes `rtd_shadow` (v2, additive, counts only); `SECOND_BRAIN_RTD=active` records intent; substitution NOT implemented. **SHADOW MODE ONLY.** `config/context.toml [rtd] threshold_chars` IS wired into the threshold ladder (env `SECOND_BRAIN_RTD_THRESHOLD` still overrides; other `[rtd]` keys remain informational — see `proof/reports/config-consumption.md`).

## Non-responsibilities
Never substitutes tool-result content (shadow-only); never stores content in rtd_shadow; never lossy-compresses source edit regions (plan §21).

## Inputs
Text/file bytes + kind/tool/session; bash events; RTD env vars.

## Outputs
Blob+meta files; distilled strings; handles; rtd_shadow records.

## State ownership
`state/artifacts/` (blobs immutable, meta per hash).

## Invariants
`expand` byte-identical original; distillation deterministic (created_at only in metadata); collision/corruption → BrainError, never silent overwrite; blob before meta.

## Interactions
`brainctl artifact store|expand|list`; TS appends rtd_shadow into telemetry JSONL; later phases use `/brain-expand` recovery.

## Failure behavior
Missing/unreadable input → BrainError; corrupt meta → BrainError naming path; TS failures never disturb normal telemetry.

## Verification
`tests/test_artifacts.py` (25): roundtrips, exact bytes, prefix ambiguity, idempotent re-store + collision refusal, golden distiller outputs, caps, 3 Hypothesis properties (roundtrip/determinism/prefix-never-wrong). TS `rtd.test.ts` (19: triggers, reasons, threshold parsing, privacy, eligibility-before-measurement, single-serialization proofs).

## Known limitations
Substitution unimplemented (shadow-only); no artifact retention/expiry; threshold ladder: env `SECOND_BRAIN_RTD_THRESHOLD` → `context.toml [rtd] threshold_chars` → default 8000; other `context.toml [rtd]` values are documented defaults, NOT read at runtime.

## Future extension
Active RTD substitution with expand recovery; sensory gateway; retention policy.

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #2, #10.

## Relevant tests
`tests/test_artifacts.py`; `brainstem/prime-extension/tests/rtd.test.ts`.
