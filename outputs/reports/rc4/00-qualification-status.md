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

This RC4 pass was scoped, by explicit user decision, to **repo-only phases**
that a single Claude Code session can perform directly: no paid model
campaigns, no other-harness (Prime/Codex/AGY) live sessions. Those phases
remain open — see [21-independent-handoff.md](21-independent-handoff.md) for
what still requires genuine cross-harness execution before external
qualification can proceed.

Completed this pass:
- **Phase R0** — RC3 synthetic-evidence quarantine and disposition
  ([01-rc3-evidence-disposition.md](01-rc3-evidence-disposition.md)).
- **Phase R1** — actual Prime live call-graph audit from source, not RC3
  report claims ([02-prime-live-callgraph.md](02-prime-live-callgraph.md)).
- **Phase R4** — Action Cache proof-safety repair (explicit predicate
  allowlist; unknown predicate now fails closed). See
  [`src/second_brain/action_cache.py`](../../../src/second_brain/action_cache.py)
  and the adversarial tests added to
  [`tests/test_action_cache_safety_proof.py`](../../../tests/test_action_cache_safety_proof.py).
  Verified: `pytest tests/test_action_cache_safety_proof.py tests/test_action_cache.py`
  → 17 passed. `ruff check` and `pyright` clean on both files.

Not attempted this pass (require paid/cross-harness execution or additional
scoped sessions): R2 (Firewall/RTD unification), R3 (VMem context
integration — live proof), R5 (Action Cache Prime integration), R6 (Tool
Working Set live control), R7 (Worker Plane live spawn control), R8 (Hybrid
Retrieval verification), R9–R11 and everything in sections 18–29 of the
recovery plan (token campaign, ablations, dogfood, failure injection,
security, backup/restore, burn-in).
