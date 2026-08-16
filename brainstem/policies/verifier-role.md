# Verifier Role Contract (P0-P2 amendment Phase D; §12.7, §23)

Status: ADVISORY (policy text; no hard enforcement yet — Phase D2 will wire
a fresh-verifier delegation path).

## Purpose

For consequential code changes and decisions, verification must come from a
**fresh** agent whose independence matters: it has not implemented the change
and is not invested in the implementer's narrative.

## Pipeline

```text
implementation owner -> artifacts/evidence -> fresh verifier -> driver acceptance
```

## Verifier duties

- Receives the **requirement** and the **diff/artifacts**, NOT the solver's
  narrative as ground truth.
- Answers the independence question:
  > If you did not know the original request, what problem would you infer
  > this patch was trying to solve?
  Then compares the inferred purpose against the real requirement.
- Inspects evidence quality, commands/tests actually run, and claims vs
  proof; flags unsupported claims, contradictions, scope drift, missing
  proof.
- Never merely repeats the implementer's conclusion.

## Hard rules

- **Read-only**: verifiers inspect, they do not write (shared-file safety
  §23; one writer per owned file).
- Evidence format (worker result contract): Conclusion / Evidence /
  Files-symbols / Commands-tests / Changes / Uncertainty / Next action /
  Artifacts.
- A verifier may request targeted follow-ups from the implementer instead of
  fixing anything itself.
- Freshness: use a NEW worker (or a retained verifier only when independence
  is already established) — never the implementation owner.

## When required

- Consequential code changes (edits beyond trivial), test-suite gate runs
  before acceptance, contradictory evidence, and any claim the driver cannot
  cheaply verify itself.
