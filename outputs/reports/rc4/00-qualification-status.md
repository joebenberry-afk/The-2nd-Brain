# RC4 Qualification Status

**Branch:** `brain/v1-rc4-genuine-proof`
**Base SHA:** `7842b68e15a95799748404e442714aa6dc580976` (RC3, verified present as a real commit in this repo before branching — `git cat-file -t` returned `commit`)

## Status

```
RC3 IMPLEMENTATION: PARTIALLY REUSABLE
RC3 TOKEN QUALIFICATION: INVALID — SYNTHETIC INPUT VALUES
RC3 ABLATIONS: INVALID — SYNTHETIC INPUT VALUES
RC3 P3/P4 REAL-USE CLAIMS: NOT RELEASE EVIDENCE
RC3 PRODUCTION QUALIFICATION: NOT RELEASE EVIDENCE
RC4 STATUS: REPAIR + GENUINE EVIDENCE COLLECTION
```

## Session scope note

This RC4 work was scoped, by explicit user decision, to **repo-local
implementation** a single Claude Code session can perform directly: no
paid model campaigns, no other-harness (Prime/Codex/AGY) live sessions.
That scope is now complete — see
[10-runtime-implementation-checkpoint.md](10-runtime-implementation-checkpoint.md)
for the full checkpoint report (`RC4_RUNTIME_IMPLEMENTATION_COMPLETE —
REAL PILOT REQUIRED`). `21-independent-handoff.md` is deferred to the end
of the full RC4 process per plan §42 — it is not written until genuine
cross-harness/paid evidence exists to hand off, which this checkpoint does
not yet include.

Completed:
- **R0** — RC3 synthetic-evidence quarantine ([01](01-rc3-evidence-disposition.md)).
- **R1** — Prime live call-graph audit from source ([02](02-prime-live-callgraph.md)).
- **R2** — RTD/Firewall reduction path confirmed live, no rebuild ([03](03-prime-rtd-firewall.md)).
- **R3** — VMem compaction-boundary bookkeeping wired; `context` handler's
  wire()-discards-return bug fixed ([04](04-prime-vmem.md)).
- **R4** — Action Cache predicate allowlist, fail-closed on unknown predicate.
- **R5** — `action-cache search`, narrowest Brain-owned execution-bypass
  layer; two silent-cache-miss bugs found and fixed ([05](05-action-cache-live.md)).
- **R6** — Prime's real tool surface captured (read-only); `setActiveTools`
  deliberately deferred (fictional catalog mismatch) ([06](06-tool-working-set-live.md)).
- **R7** — `worker-plane` CLI, the real concurrency-ceiling enforcement
  surface Prime itself doesn't expose ([07](07-worker-plane-live.md)).
- **R8** — Hybrid Retrieval cascade wiring verified against the plan
  checklist, no rebuild; one honest capability gap documented ([08](08-hybrid-retrieval-validation.md)).
- **R9** — Fresh-verifier "record" plumbing; never generates a verdict
  itself ([09](09-fresh-verifier.md)).

Not attempted (require paid/cross-harness execution — R9–R11 "live proof"
tier and everything in sections 18–29 of the recovery plan: token
campaign, ablations, dogfood, failure injection, security, backup/restore,
burn-in). See the checkpoint report for the exact first-pilot procedure.
