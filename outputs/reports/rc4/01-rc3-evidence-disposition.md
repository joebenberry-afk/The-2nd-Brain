# RC3 Evidence Disposition

Phase R0. Every item below was checked directly against the RC3 source at
`7842b68e15a95799748404e442714aa6dc580976`, not against RC3's own report
claims. RC3 evidence is **not deleted** — this classifies it so it cannot
contaminate RC4 release conclusions.

## Classification key

- `INVALID_RELEASE_EVIDENCE_SYNTHETIC` — generated/hard-coded, not captured
  from real execution; cannot support a release claim.
- `VALID_COMPONENT_TEST` — real code exercising real modules; proves the
  component works, not that a live host/provider session produced the numbers.
- `VALID_IMPLEMENTATION_EVIDENCE` — real source-code change, reusable as-is.
- `SUPPLEMENTAL_ONLY` — human-readable narrative derived from the above; useful
  context, not proof.

## Invalid release evidence (confirmed by direct inspection)

### `scripts/run_rc3_token_campaign.py` — `INVALID_RELEASE_EVIDENCE_SYNTHETIC`

Lines 19–31 hard-code `tokens_off` / `tokens_on` per task (e.g. `"P-01", ...,
"tokens_off": 1250, "tokens_on": 210`) for all 13 task pairs. Line 64 selects
between these two constants based on `mode` instead of invoking any model.
Lines 93/109/152 fabricate provider run IDs with
`f"run-{p_id}-{mode}-001"` / `f"run-abl-{a_name}-001"` — the exact forbidden
pattern this recovery plan names (`run-P-01-off-001`). No provider or harness
is invoked anywhere in the file. Everything downstream of this script
(`outputs/reports/rc3/11-token-campaign-method.md`,
`12-token-campaign-results.md`, `13-feature-ablations.md`, and the `raw/`
files they cite) inherits the same disposition.

### `scripts/run_rc3_p3_p4_production.py` — `INVALID_RELEASE_EVIDENCE_SYNTHETIC`

- Line 54: `usage.json` written as a literal
  `{"input_tokens": 210, "output_tokens": 60, "total_tokens": 270}` — never
  read from a provider/host response.
- Line 80 (and further down in the file): a second hand-written `usage.json`
  for the P4 arm.
- Lines 33–37: `radar_events` is a hand-typed 3-item list fed to
  `ImprovementRadar.analyze_events()` — not telemetry captured from a real
  session, so any "repeated pattern" the radar reports was seeded by the
  script author, not discovered.
- Line 41: `ledger.record_usage(..., tokens_invested=80, tokens_saved=500,
  ...)` — a manually chosen ROI number, not a measured delta between paired
  runs.
- Line 72: `fingerprint_store.record_bottleneck(...)` called directly with
  author-chosen fields — not derived from captured runtime telemetry.

`outputs/reports/rc3/14-p3-real-use.md`, `15-p4-real-use.md`,
`16-production-qualification.md`, and `17-burn-in.md` inherit this
disposition: they are real component exercises of real modules
(`ImprovementRadar`, `SkillROILedger`, `SkillGardener`, `GoalStore`,
`LocalHeartbeatEngine`, `BottleneckFingerprintStore`, `create_backup` /
`restore_backup`) — the modules genuinely run — but the *inputs* were
authored, not observed, so the outputs cannot stand as dogfood/production
evidence. Reclassified `VALID_COMPONENT_TEST` for the module-level exercise;
`INVALID_RELEASE_EVIDENCE_SYNTHETIC` for any release/token/ROI claim drawn
from their output.

### Manual security assertions

RC3 report content asserting scan results without a captured raw scanner
invocation in `outputs/reports/rc3/raw/` falls under
`INSUFFICIENT_PROVENANCE` — carried forward as unproven, not re-asserted.

## Retained as implementation/component evidence

- `VALID_IMPLEMENTATION_EVIDENCE`: `src/second_brain/action_cache.py`,
  `src/second_brain/vmem.py`, `src/second_brain/firewall.py`,
  `src/second_brain/tool_working_set.py`, `src/second_brain/working_set.py`,
  Hybrid Retrieval / AutoInject wiring
  (`brainstem/prime-extension/src/autoinject.ts`,
  `src/second_brain/autoinject.py`), Delta Sync, Repository Intelligence,
  Improvement Radar, Skill ROI/Gardener, Handoff, Goals, Heartbeat,
  Fingerprints, existing adapters, ledger, Token Governor, RTD, Lean Code,
  verification machinery — per §5 of the recovery plan. Reused unmodified
  except `action_cache.py` (see below).
- `VALID_COMPONENT_TEST`: `tests/test_action_cache.py`,
  `tests/test_action_cache_safety_proof.py` (pre-existing adversarial suite;
  extended this pass, not replaced).

## F4 — Action Cache predicate safety (repaired this pass)

Confirmed by direct read of RC3 `src/second_brain/action_cache.py:344`:

```python
return proof.verification_predicate != "reject_always"
```

Any unrecognized predicate string passed validation. Fixed on this branch:
explicit allowlist `KNOWN_VERIFICATION_PREDICATES` (file-scope constant),
unknown predicate now returns `False` (fail closed). Three adversarial tests
added: unrecognized predicate, the literal `"reject_always"` string, and a
sanity check that the allowlisted default still hits. Full suite (17 tests)
passes; `ruff` and `pyright` clean. See
[00-qualification-status.md](00-qualification-status.md) for the exact
verification commands run.

## Not yet classified

Cross-harness (`outputs/reports/rc3/10-cross-harness-live.md`), fresh
verifier (`09-independent-verifier-live.md`), Prime firewall/VMem/tool
working set/worker plane live-proof reports (`02`–`08`) require the same
direct-source-vs-claim audit this report gave the token/P3/P4 scripts. That
audit is out of scope for this repo-only pass — see
[00-qualification-status.md](00-qualification-status.md) for what remains.
