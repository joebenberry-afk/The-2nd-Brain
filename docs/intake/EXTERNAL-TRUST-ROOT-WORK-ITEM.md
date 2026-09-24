# External trust-root work item (opened 2026-09-24)

**Status:** OPEN — external precondition. Not M00 implementation work.
**Origin:** the owner accepted the issuer-dependent items at the M00 boundary
(`M00-CAMPAIGN-REGISTER.md`, "M00 boundary decision"). M00 is recorded as
`M00_CODE_QUALIFIED / EXTERNAL_TRUST_ROOT_PENDING`.
**Demonstrated so far:** nothing. No independent approval, protected custody or
cryptographic signing exists or has been demonstrated.

## Requirement

Provide one independent trust root: an issuer whose authority the agent cannot
write, forge or obtain. The agent has everything available to the same OS user —
its files, environment, config, registry, credential stores that user can read,
any interactive terminal it can drive, and every process it can launch. An issuer
reachable through any of those fails this requirement, whatever it is named.

## Consumers waiting on it (all fail closed today)

| Capability | Seam in the candidate | Behavior until the issuer exists |
|---|---|---|
| Approval-bearing / CRITICAL completion | `verify.APPROVAL_ATTESTATION_ISSUERS`, `verify.approval_attested` | gate stays `required`, `completion_allowed=false` |
| VERIFIED memory issuance | `semantic.VERIFIED_ATTESTATION_ISSUERS`, `semantic.verified_attested` (write: `_require_verified_attestation`; read: `effective_evidence_grade`, `grade_attestation`) | refused; stored VERIFIED counts as at most TESTED |
| Policy-authority promotion | `semantic.AUTHORITY_ATTESTATION_ISSUERS`, `semantic.authority_attested` (`_validate_origin`, `effective_authority_ceiling`, `authority_attestation`) | ceiling always `advisory`; the policy lane admits nothing |
| Authoritative model-success records | `cli.cmd_models` `record`; the removed write in `verify.evaluate_accuracy_gate` | refused; needs an authenticated runtime model identity |
| Protected skill approval | `frontier.frontier_review` / `skills.approved_content` | unprotected same-user review record, bound to exact bytes (SEC-SKILL-01 residual) |
| Protected extension-install approval | `scripts/install-prime-extension.ps1`, deployment manifest tool | operator-invoked and byte-verified; no approval binding (FSUPD-01 residual) |
| Ledger signing | `ledger` envelope chain / `ledger_meta` | unkeyed tamper-evidence (SEC-INTEGRITY-01 residual) |

The three registries are empty in shipped code. They cannot be selected by
environment, config, CLI flag, model setting or import side effect. Registering
an issuer is a security change reviewed against this item. It is never a
configuration switch.

## Acceptance criteria for any future issuer

1. **Separation proof:** an adversarial test running as the agent's OS user, with
   full access to the repository, the Brain home and the environment, cannot
   produce an attestation that any consumer above accepts. This must be
   demonstrated, not argued.
2. **Binding:** each attestation names its exact subject — memory id and version,
   gate id and evidence-set hash, skill artifact sha256, install manifest
   digest, or ledger range — and cannot be replayed onto another subject.
3. **Revocation and expiry:** withdrawn or expired authority stops being
   effective without rewriting historical rows.
4. **Custody record:** where the key or credential lives, who can use it, and
   how it is rotated and recovered. No secret value may enter this repository.
5. **Fail-closed stays the default:** an unavailable, malformed or erroring
   issuer resolves to "no authority", as the current validators do.
6. **Independent review** of the issuer and of each consumer it re-enables,
   one capability at a time. Each re-enable is a separate change with its own
   tests.

## Candidate directions (not decisions)

A signing key held outside the agent's reach — a hardware token requiring
physical presence, a separate OS principal the agent cannot become, or a
remote signing service with out-of-band human approval — with the Brain
verifying signatures against a pinned public key. Choosing one is an owner
decision within this work item.

## Out of scope

Weakening any current refusal to restore functionality, rebuilding
orchestration or worker authority, and machine-wide account or permission
changes without explicit owner authorization.
