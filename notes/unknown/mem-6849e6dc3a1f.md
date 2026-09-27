---
id: mem-6849e6dc3a1f
kind: fact
at: 2026-09-21T10:17:49.033128+00:00
source: convert
evidence:
  - crates/scaler-core/src/governor.rs@0f42619e99ce (repo C:\Users\assas\Documents\BasicUpscaler\The Basic Upscaler)
  - docs/gates/SLICE-F-BOUND-VALIDATION.md@8a891f1772bd (repo C:\Users\assas\Documents\BasicUpscaler\The Basic Upscaler)
---

GovernorSnapshot.last_action reported the per-tick decision and was cleared by l

GovernorSnapshot.last_action reported the per-tick decision and was cleared by later no-action ticks, so the F-bounds soak artifact could not show which governor action had been applied (actions_taken=1 together with last_action=none); the snapshot now reports the applied action plus last_action_reason, and the documented repro reproduces PASS_BOUNDED with last_action=prefer_bilinear.
