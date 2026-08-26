# Task 4 report: archive-first retirement and restore

## Status
Complete. Final closure round removes the self-declared `runtime:`/`verification:`/`telemetry:` evidence-ref acceptance branch entirely — for `_BROKEN_CONDITION_CODES`, only `audit:`-bound refs (matching a real `audit_findings` entry) and `evaluation:`/`eval:`-bound refs (matching the persisted `evaluation_id` and current content hash) remain acceptable concrete evidence; a same-payload self-declared `evidence_id` can no longer substitute for independent evidence. Earlier rounds hardened legacy ROI schema migration, source-bound concrete broken-condition evidence, malformed counterfactual handling (including invalid UTF-8 and boolean totals), per-skill recommendation scoping, canonical Radar/promotion/counterfactual references, demotion governance validation with bounded normalized versions, stale freshness evidence, stale-evidence authorization rejection, and malformed version fail-closed handling.

## Files
- `src/second_brain/gardener.py`
  - Persists archive destination, retirement reason, and production-safety evidence in authorized records.
  - Removes the self-declared `runtime:`/`verification:`/`telemetry:` evidence-ref acceptance branch and the now-unused `_CONCRETE_EVIDENCE_PREFIXES` constant; only `audit:`- and `evaluation:`/`eval:`-bound refs remain acceptable for `_BROKEN_CONDITION_CODES`.
  - Copies the complete skill tree to staging, verifies every archived byte and `SKILL.md` lifecycle hash, persists a bounded retirement record, then atomically moves the source into a quarantine location outside lifecycle directories.
  - Adds idempotent additive migration for legacy ROI ledger columns and fail-closed malformed P3.13 records.
  - Restores verified archives to the previous lifecycle directory without overwriting an existing artifact.
  - Rejects stale/invalid authorizations and active retirements lacking explicit production-safety approval, concrete issue evidence, or demotion promotion-governance evidence.
  - Delegates all non-archive actions without content or lifecycle mutation.
- `tests/test_p3_15_skill_gardener.py`
  - Added focused coverage for operation ordering, complete retirement record fields, copy/hash/record failures, archive overlap, quarantine-root collision, byte-identical restore, restore collision refusal, authorization replay refusal, incomplete-record refusal, source-removal recovery, missing-gate rejection, marker-only/arbitrary/source-unbound broken-evidence rejection, legacy ledger migration, malformed counterfactual evidence with direct unavailable measurement assertions, forged and valid canonical demotion governance, stale freshness authorization rejection, active safety gating, delegated non-mutation, genuine evaluation-bound rebinding of every broken-condition marker-only site (dead_skill via a real missing-required-section audit finding; false_trigger/scope_too_broad/scope_too_narrow/model_specific_quirk via evaluation-record binding), self-declared-evidence-id rejection, and mixed real-audit/fabricated-verification ref lists failing closed as a whole.

## Tests
- `.venv/Scripts/python.exe -m pytest tests/test_p3_15_skill_gardener.py -q` — **57 passed**
- `.venv/Scripts/python.exe -m ruff check src/second_brain/gardener.py tests/test_p3_15_skill_gardener.py` — passed
- `.venv/Scripts/python.exe -m ruff format --check src/second_brain/gardener.py tests/test_p3_15_skill_gardener.py` — passed
- `.venv/Scripts/python.exe -m pyright src/second_brain/gardener.py tests/test_p3_15_skill_gardener.py` — 0 errors, 0 warnings, 0 informations

## Commit
`216b6cb feat(gardener): add archive retirement`; `0db28d3 fix(gardener): close retirement replay gaps`; `a33fbe7 fix(gardener): recover failed source removal`; `825db11 fix(gardener): quarantine source atomically`; `bbcdeaa fix(gardener): reject quarantine collisions`; `dc91628 style(gardener): satisfy focused Ruff gate`; `1179ff0 fix(gardener): narrow archive types`; `ccecccc fix(gardener): require retirement gate refs`; `591f2c3 style(gardener): format gate regression`; `480a97f fix(gardener): harden evidence composition`; `f450d95 fix(gardener): close evidence edge cases`; `32cafb6 fix(gardener): validate canonical promotion evidence`; `6ff947a fix(gardener): bound promotion versions`; `312f325 fix(gardener): require concrete breakage evidence`; `2960a3d fix(gardener): bind breakage evidence`; `1c86c5a fix(gardener): reject self-declared runtime/verification/telemetry evidence`

## Concerns
- Focused `pyright` passed with 0 errors, 0 warnings, and 0 informations.
- Focused `ruff check` passed; focused `ruff format --check` reports both files already formatted; focused `pyright` passed with 0 errors, 0 warnings, and 0 informations.
- Project-wide suites remain intentionally skipped per Task 4 scope.
- Source mutation uses an atomic same-volume quarantine move after the archive and retirement record are durable; simulated partial-delete behavior cannot affect the source path, and restore remains byte-identical.
- Consumed authorizations are durably marked after successful source mutation; an in-progress marker is reset when source removal fails, allowing safe retry. In-progress authorizations reject replay if post-removal marker persistence itself fails.
- The rebound `test_stale_broken_and_superseded_refs_are_bounded` `broken`/`false_trigger` case uses a short genuine evaluation ref rather than a >256-char one: after this fix, `_evidence_refs` truncates any ref to 256 chars *before* the `evaluation:`/`audit:` verification check runs, so a truncated identifier can never equal the untruncated stored `evaluation_id`/`audit_findings` entry — a >256-char audit:/evaluation:-bound ref is structurally unverifiable by design. The original ref (`verification:broken`, 20 chars) never exercised truncation either; only the `superseded` case in that test exercises real 256-char bounding. No behavior gap, just noting the analysis.
- P3.1–P3.14 and Lean HOLD_SHADOW were not touched; only `_explicit_condition`'s broken-condition evidence-ref verification changed.
