---
date: 2026-09-21
type: decision
authority: current
status: accepted
scope: v3-architecture
supersedes: none-additive
superseded-by: none
promoted: 2026-09-21
---

# Decision — adopt a small deterministic kernel for v3

Owner decision, recorded 2026-09-21 (D-6). Authored directly into `requirements/` by owner
decision rather than promoted from `intake/`; see the promotion log in
[`README.md`](README.md).

## The decision

Second Brain v3 extracts a **small deterministic kernel** from the existing Brain and keeps
the rest as services around it. This is an **extraction/refactor, not a rewrite**: existing
Brain modules are reused, and nothing here authorizes starting over.

```text
                 Second Brain
                      │
         ┌────────────┴────────────┐
         │                         │
 Deterministic Kernel          Services
         │                         │
 lifecycle invariants          retrieval
 capability policy             memory
 authority rules               telemetry
 state transitions             skills
 protocol validation           orchestration
         │
         └──────────┬──────────────┘
                    │
             Host Protocol v1
                    │
             thin OMP adapter
```

The kernel must stay **small enough to reason about exhaustively**: if a rule cannot be
enumerated and tested in full, it does not belong in the kernel.

## In the kernel

- capability negotiation;
- authority and provenance validation;
- worker lifecycle transitions;
- writer ownership;
- settlement and release invariants;
- protocol parsing and validation;
- ledger transition rules;
- project and worktree identity contracts.

## Not in the kernel

Retrieval algorithms, embeddings, prompt construction, ranking heuristics, Jev, model
routing, OMP field names, UI, and research agents. These are services: they may fail, be
replaced or be experimented with without changing what the system guarantees.

## Why, given OMP 18.2.8

The host-bridge work measured what a host can actually attest: on stock 18.2.8 the bridge may
advertise only `execution_binding` and `cancellation_observation`; settlement, cleanup,
complete census and authenticated observation are absent, and there is no impersonation
boundary at all (see
[`../../outputs/reports/host-bridge-v1-20260921/AUTHENTICATED-SOURCE-FINDINGS.md`](../../outputs/reports/host-bridge-v1-20260921/AUTHENTICATED-SOURCE-FINDINGS.md)).
A harness-independent system therefore cannot be built by trusting a host more; it has to be
built by making the *rules* small, explicit and host-neutral — kernel semantics — while
treating host capability as data. The same argument is why the kernel cannot absorb things
that vary by host or by model: field names, routing and prompt shape belong to the adapters.

## Consequences

- The kernel is the only place that may mint or release writer ownership, decide a lifecycle
  transition, or validate authority; adapters translate, services advise.
- A new host is supported by implementing Host Protocol v1, never by changing kernel rules.
- Kernel growth requires an explicit decision with an owner, because the whole premise is
  that its rule set stays enumerable.
