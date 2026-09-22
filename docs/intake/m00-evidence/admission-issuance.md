# M00.3 #4 — admission-issuer route: reproduction and blocker analysis

**Subject:** candidate worktree `.worktrees/m00.3-producer-guard`.
**Production activation: NOT PERFORMED.** Disposable Brain home under the OS temp dir; no canonical
state touched. Credential values are redacted in the retained evidence.

## 1. The mandated first step, executed: can a caller obtain authority and use it?

The mandate asks: *"Reproduce the admission-to-completion chain in disposable state: can an agent
request admission, receive a usable callback credential, and certify completion?"* **Yes.**

Evidence (`setup.json`, `probe-before.json`, `accept.json`, `probe-after.json` in this directory),
produced by `tests/fixtures/omp_replay_state.py` running as an ordinary child process:

| Step | Observation |
| --- | --- |
| `setup --intent mutating` (the `worker_context` admission path) | returns `"callback_token": "<issued>"` **in the response to the caller**, together with `attempt_id`, `packet_sha256`, `worktree_id`; the created attempt is `WORKING`, ownership `held`, digest present, 0 attempt results |
| `accept` (the `worker_result` completion path) with that token | `status: completed`, `result_sha256` written; probe afterwards: state `COMPLETED`, 1 attempt result, same digest, `logical_outcome: completed` |

So the credential that `_require_terminal_authority` requires is minted **and handed to the same
caller** that created the attempt. Nothing in the chain binds that caller to a trusted host.

## 2. Mechanism, stated against the code

- `omp_adapter._prepare_worker_context` (the `worker_context` operation) calls
  `worker_protocol.admit_worker_attempt` and then copies `registration["callback_token"]` into its
  response: `if "callback_token" in registration: response["callback_token"] = registration["callback_token"]`.
- `worker_protocol.register_attempt` mints the token exactly for `access_intent == "mutating"` and
  stores only its sha256 digest, so the Brain cannot re-issue or compare plaintext later — but it does
  disclose the plaintext once, to whoever asked for admission.
- The only gate in front of that is a **payload-declared** role: `role = _text(payload.get("role")) or
  "driver"` then `if role not in contracts.COORDINATOR_ROLES: raise ...`. Any caller can send
  `"role": "driver"`. Mutating concurrency is additionally guarded by writer leases
  (`WORKTREE_WRITER_BUSY`), which is exclusion between writers, not authentication of the issuer.
- The consumer-side guard (#3) is therefore real but partial: it proves *an attempt-scoped credential
  was presented*, not that the presenter was entitled to obtain it.

## 3. Can this be closed with a candidate-local mechanism?

The candidate and the agent that could abuse it run as the **same OS user** in the same session: the
extension shells out to the CLI exactly the way an agent's shell tool does. Every candidate-local
channel I can construct — a file, an environment variable, a pipe, a per-session secret, a
private-looking JSON record, a function only the host "should" call — is readable or invocable by any
process with that identity, so none of them authenticates the *caller*; they only relocate the secret.

The mandate's own boundary is explicit: no permanent service, no second authority store, no
machine-wide accounts/permissions, and no elevation. Under that constraint the enforceable part is
smaller than the claim:

- **Enforceable now (candidate-local):** keep issuance attempt-scoped (already true), keep plaintext
  disclosure single-shot (already true), require the credential on every authority-bearing transition
  (already true since #3), and treat `role` as **not** an authorization (it currently reads as one).
- **Not enforceable without an external capability:** authenticating the *issuer* — i.e. proving that
  the process asking for admission is the trusted host rather than any process with the same OS
  identity. That needs either OS-identity separation (separate account / ACLs / elevation) or a
  trusted channel the agent cannot reach, both of which the mandate forbids adding here.

**Exact blocker, isolated:** *there is no trusted channel or OS-identity boundary between the host
extension and an agent-controlled process in this environment; consequently admission issuance cannot
be authenticated against the agent.* `WORKTREE_WRITER_BUSY` remains exclusion-only, and `actor_trust`
labels or an approved-looking record must not be treated as authority.

## 4. Consequence for the candidate's claims

- #3 stays what it is: attempt-credential enforcement for the demonstrated terminal-write scope. It is
  **not** no-self-approval.
- The `ADM` register row stays `OPEN`; this record narrows it to the issuer-authentication blocker
  above rather than a general "issuance is unguarded".
- The forged read-only completion finding (`#3-R.3`) is a **separate** gap: it needs no issuance at
  all, because read-only attempts are minted nothing and their terminal evidence is decided by journal
  fields. Closing issuance would not close it.
- Per the mandate, this boundary is recorded as a partial external blocker and the campaign continues
  with work that does not depend on it; the boundary must **not** be described as satisfied by any
  weaker mechanism.

## 5. What is genuinely demonstrable today

The chain that a candidate can demonstrate end-to-end is:

`host extension (source factory) → real bridge → CLI → omp_adapter → worker_protocol` with
attempt-scoped authority enforced on every terminal write, refusals that leave durable state
untouched, and journal-based replay that grants no authority (see
`outputs/reports/m00.3-replay-authority-20260922/REPORT.md`). The issuer side of that chain is
authorized by *possession of the session's CLI*, which is the boundary this record leaves open.
