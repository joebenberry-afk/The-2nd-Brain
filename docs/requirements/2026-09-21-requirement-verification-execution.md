---
date: 2026-09-21
type: requirement
authority: current
status: accepted
scope: verification-execution
supersedes: none-additive
superseded-by: none
promoted: 2026-09-21
---

# Requirement — independent runtime verification through a constrained host capability

Owner decision, recorded 2026-09-21. Authored directly into `requirements/` by owner
decision rather than promoted from `intake/` (see the promotion log in [`README.md`](README.md)).

## The limitation being recorded

A read-only verification agent in this system **cannot currently execute anything**:
`implementation-verifier`, `reviewer` and `scout` have no shell tool, and kernel-defined
tools are not exposed to workers. Therefore:

- **Claimable today:** source-level verification, artifact auditing, evidence review,
  re-derivation of numbers from supplied material.
- **Not claimable today:** "independently runtime-verified". No agent verdict in this
  repository may assert runtime execution it did not perform, and runtime evidence produced
  by the driver is *driver* evidence, not independent verification.

This is recorded as a fact about the worker architecture, not as a defect in any one task.

## What must be built

A constrained **verification execution** capability, rather than granting read-only reviewers
unrestricted shell access. Conceptually:

```text
implementation-verifier
        │
        ▼
VerificationRunner
        ├─ run approved test command
        ├─ run type checker
        ├─ run linter
        ├─ inspect exit code
        ├─ capture stdout/stderr
        └─ report environment identity
```

The runner accepts typed requests (for example `RunVerification { workspace, executable,
args, timeout, expected_access }`) and **the host decides what is actually executable**.

### New BrainHostProtocol capabilities

| Capability | The question it answers |
|---|---|
| `verification_execution` | a designated verification agent may ask the host to run a bounded command against an exact disposable candidate |
| `verification_environment_identity` | which host, build, runtime and workspace actually ran it |
| `verification_result_attestation` | the result carries as much provenance as the host can honestly provide (see the limit below) |

### The verifier must be able to prove

the exact candidate revision · the exact executable/test · the exact working directory · the
exact result · the exact host/build.

### The verifier must remain unable to

alter the canonical Brain DB · approve its own changes · mint lifecycle authority · mutate
production · acquire a writer lease merely because it can run tests.

## Two limits to state, not paper over

1. **Attestation strength is bounded by the host's impersonation boundary.** On the measured
   host there is no impersonation boundary: extensions are not sandboxed, share one event
   bus, and any in-process code can emit a byte-identical record. `verification_result_attestation`
   therefore reduces to *"a host-generated record that a hostile in-process emitter could
   forge"* — strictly better than an agent's own claim, and not impersonation-resistant.
   `authenticated_observation_source` stays false until a real boundary exists.
2. **This capability is not a general sandbox.** It exists so that verification can execute;
   it does not make arbitrary execution safe, and it grants no approval power.

## Why it matters beyond this host

It makes verification **harness-independent**: OMP, OpenCode or another host can implement
the same verification contract differently while Brain consumes the same result type. That is
the same principle as the host bridge — host capability is data, the rules stay in the kernel
(see [`2026-09-21-decision-v3-deterministic-kernel.md`](2026-09-21-decision-v3-deterministic-kernel.md)).

## Until it exists

Jev, reviewer, scout and librarian roles keep operating normally, with their evidence type
**labelled accurately**: source-level, artifact-level, or judgment — never "runtime-verified".

## Design (proposed — not authority)

A `system-architect` pass produced the design at the owner's request and it is filed as a
**proposal** in [`../intake/2026-09-21-plan-verification-execution-design.md`](../intake/2026-09-21-plan-verification-execution-design.md).
It stays in `intake/` until promoted under the four gates there; it grants nothing on its own.
What it settles, in outline:

- **Four ownership boundaries**, so verification cannot become an approval path: an
  independent authorizer/qualification owner, a host verification runner that owns only
  verification state and its own evidence store (never writer leases or settlement state),
  the bridge, and the caller.
- **Eight authority invariants**, each with the violation it prevents and the refusal that
  enforces it: no writer lease, no canonical/DB mutation, source-preserving verification, no
  self-approval, no lifecycle authority, no production reach, no general shell authority
  (structured argv plus an admitted invocation policy — never an arbitrary command string,
  and no shell/eval/task tool handed to the verifier), and no result laundering.
- **The honest attestation ceiling on this host**: extension-only
  `verification_result_attestation` can at most be *"a host-generated record that hostile
  in-process code could forge"* — operationally better than an agent's own statement, and not
  origin evidence against another extension in the same process. Hashing detects inconsistent
  content, not a hostile emitter that recomputes hashes. Stronger provenance needs a boundary
  candidate code cannot reach (an independently controlled broker under a distinct OS
  principal, authenticating authorized scope and actual launch). `authenticated_observation_source`
  stays false until that is demonstrated — it is never redefined to mean "a host callback was
  probably the emitter".
- **A demonstration rule** before anyone may claim independent runtime verification: the
  exercises must show execution *and* the refusals (a verifier cannot mutate, cannot
  self-approve, cannot reach production), with evidence a reader would accept.

Keep `advertisement_sha256` as it is: it hashes canonical parsed JSON, not literal file bytes.
When exact reviewed serialization matters, record a separate raw artifact digest rather than
redefining the existing field.
