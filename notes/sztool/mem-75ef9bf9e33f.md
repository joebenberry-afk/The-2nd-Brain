---
id: mem-75ef9bf9e33f
kind: fact
at: 2026-08-28T22:43:52.919966+00:00
source: convert
evidence:
  - DBSZ Telemetry/SZ-CPU-Lab/.superpowers/sdd/Sparking_Zero_Telemetry_OMP_Resume_Plan/progress.md
replaces: mem-7dda00fb6cdc
---

T1 PRODUCTION INTEGRATION COMPLETE: promotion gate passed, live in production

T1 is live in production: current_blast_id N-to-N+1 edge cardinality, scoped SIDE+TEAM_SLOT, emits the blast_committed semantic event alongside the intact legacy blast_used path (shadow comparison; no consumer migration of analytics.py/live_state.py yet, a separate reversible step). Promotion gate passed: every genuine Blast produced exactly one blast_committed (player Kefla id 2 to 3, Ki about -28282; CPU Hit id 0 to 1, Ki exactly -30000); callback artifacts produced zero; zero queue drops or sequence gaps; legacy blast_used and raw blast_callback_diagnostic unaffected. Lessons: the edge logic is a pure, offline-testable Lua module blast_commitment_tracker.lua (states baseline, repeat, commit, anomaly) wired additively into main.lua on_blast_use. A new semantic event must be added to the RUNTIME_EVENT_FIELDS and HOOK_HEALTH_FIELDS serialization whitelists or encode_runtime_event silently drops its fields. The one real bug: a per-poll reset call wiped the tracker state every tick instead of only at match/session boundaries; fixed with a regression test verified to fail on the bug. Final runtime_bundle_id sha256:185aea548e79e3ee4ebb21202d7fe4f0bf3ba5c5934a936bb22ada2337208089. Detail: docs/T1_PRODUCTION_DEPENDENCY_MAP.md section 9 and the progress.md evidence above; cardinality proof in mem-55c71a309022; supersedes the pre-canary progress note mem-7dda00fb6cdc.
