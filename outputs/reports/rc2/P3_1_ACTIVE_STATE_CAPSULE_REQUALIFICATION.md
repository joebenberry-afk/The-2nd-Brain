# P3.1 Active State Capsule — Final Qualification

**Verdict:** `P3.1_PARTIAL`
**Primary live harness:** Oh My Pi (OMP)
**Scope:** P3.1 only; P3.2 was not started
**Architecture:** thin OMP registration over a harness-neutral Brain capsule bridge

## Contract

The frozen contract is defined by the v4.2 implementation plan §§16–18 and §100:

- maintain per-session working-set state under the canonical session directory;
- provide `active-state.json` with the plan §17 schema;
- update at meaningful checkpoints, not every token;
- preserve objective, constraints, facts, hypotheses, decisions, files,
  verification state, open questions, and next action;
- support fresh/resumed task recovery through existing JIT, VMem, and bounded
  model-visible context paths;
- reuse existing Brain-owned state and lifecycle primitives.

## Implementation

The existing `src/second_brain/working_set.py` substrate was reused. Its schema,
validation, atomic writes, and `updated_at` semantics were not redesigned.

Added only the lifecycle bridge layers:

- `src/second_brain/capsule_runtime.py`
  - bounded `ensure_capsule` and additive `update_capsule` operations;
  - reuses `working_set.init_capsule`, `update_capsule`, and `show_capsule`;
  - returns session identity, path, SHA-256, byte count, and changed status;
  - bounds objective/next action to 512 characters and list history to eight
    items of at most 256 characters;
  - preserves prior decisions/questions instead of replacing them.
- `brainstem/prime-extension/src/active-state-mirror.ts`
  - thin subprocess transport to the Brain CLI;
  - reuses the existing `vmem hot-context` bridge for bounded rendering;
  - rejects session-mismatched rendered state;
  - supports async checkpoint writes and synchronous terminal finalization.
- `brainstem/prime-extension/src/index.ts`
  - only registers lifecycle calls at OMP `before_agent_start`,
    `session_before_compact`, and `session_shutdown`;
  - merges bounded active state into the existing AutoInject custom-message path;
  - preserves existing routing, ledger, VMem, artifact, and AutoInject behavior.
- `brainstem/prime-extension/src/sensors.ts`
  - records privacy-safe `active_state_delivery` telemetry containing only
    capsule hash/size, rendered character count, changed flag, and visibility.
- `src/second_brain/working_set.py`
  - reuses the ledger's canonical hashed internal session directory when that
    directory already exists, while preserving raw-id standalone test/CLI
    behavior. This places OMP `active-state.json` beside its `ledger.sqlite`
    and `manifest.json` without creating another identity system.

## Automated proof

Focused Python capsule/JIT/CLI/working-set tests pass, including bounded input,
additive state, no-op updates, corruption refusal, metadata hashing, CLI
round-trip, and ledger-hash directory reuse.

Focused OMP lifecycle/bridge/VMem/ledger/wiring tests:

```text
35 passed  — active-state bridge, lifecycle, and ledger tests
35 passed  — VMem bridge regression
79 passed  — OMP wiring regression
574 passed — full OMP Vitest suite (21 files)
```

```text
pytest -q                  passed (100% green)
```

Static checks:

```text
npm run typecheck       passed
ruff check src tests    passed
pyright                 0 errors, 0 warnings, 0 informations
new OMP files ESLint    passed
```

## Fresh OMP dogfood proof

Final fresh OMP host session:

```text
2026-08-24T05-22-28-604Z_01a03238-587c-7177-aaa0-3f85ecafcc47
```

Canonical ledger session directory:

```text
state/sessions/06d210d05bb96b1b51f99ab8056319c6661951c8a4c483623cf24b438622bb8d/
```

The directory contains all three required artifacts together:

```text
ledger.sqlite       present
manifest.json       present
active-state.json   present
```

The manifest binds the hashed directory to the same OMP host session. The final
capsule is 468 bytes and contains only bounded structured state:

- objective: `P3.1resume`
- decision: `reuse-existing-vmem`
- open question: `verify-restart`
- verification: `session_shutdown=normal`
- next action: `P3.1resume`

No transcript, tool output, provider payload, or raw conversation history is
stored in the capsule.

Fresh-session telemetry:

```text
telemetry/agent-performance/2026-08-24T05-22-28-604Z_01a03238-587c-7177-aaa0-3f85ecafcc47.jsonl
```

The first OMP lifecycle emitted:

```text
active_state_delivery
session = 2026-08-24T05-22-28-604Z_01a03238-587c-7177-aaa0-3f85ecafcc47
capsule_bytes = 379
rendered_chars = 48
changed = true
model_visible = true
```

The same telemetry records OMP routing selection and effective request as
`openai-codex / gpt-5.6-luna`, plus the normal OMP `before_agent_start`, provider
request, and session shutdown records.

The final SHA-256 after meaningful state update and OMP resume is:

```text
ed6abdb39fcccc0b539750927a3a6e6e9fbf48e2fc4efb0db58c9f5fb59ac60c
```

The command output and filesystem check report 468 bytes. The telemetry
`active_state_delivery` record for the resumed OMP process carries the same
final hash and size.

## Meaningful update and resumed-session proof

A meaningful update added a decision and open question through the existing
capsule CLI. The existing VMem renderer then returned, for the same host
session:

```text
[SECOND_BRAIN_HOT_CONTEXT]
Objective: P3.1probe4
Active Decisions: reuse-existing-vmem
Blockers/Questions: verify-restart
```

The existing JIT compiler produced:

```text
outputs/context-capsules/2026-08-24T05-22-28-604Z_01a03238-587c-7177-aaa0-3f85ecafcc47-resumep31.md
```

Its active-state section contains the same objective, decision, open question,
verification state, next action, and hashed session source paths.

OMP was then resumed against the same host session. The same telemetry file
contains a second `session_start`, a second `active_state_delivery` with
`capsule_bytes=468` and `rendered_chars=121`, a second provider request, and a
second `session_shutdown`. The resumed capsule readback preserves the decision,
open question, and prior shutdown verification.

## Independent Validator readback

Independent read-only Validator verdict:

```text
P3.1_PROVEN
```

The Validator independently confirmed the same hashed session directory,
capsule schema and 468-byte bound, exact capsule hash, two active-state
delivery records across the original and resumed OMP lifecycle, shutdown and
restart identity correlation, JIT/VMem state exposure, and absence of a
parallel state system. No blocker remained.

## Safety and boundary proof

- Atomic writes remain the existing temp-file plus `os.replace` path in
  `working_set.py`.
- Capsule size and input fields are bounded by the neutral bridge.
- No full transcript is copied; telemetry stores hashes/counts only.
- `active-state-mirror.ts` rejects VMem output whose session identity differs
  from the current OMP host session.
- OMP state is stored in the ledger's canonical hashed session directory; no
  parallel OMP-native memory, context, ledger, telemetry, routing, or identity
  system was introduced.
- Existing P0–P2 and OMP routing behavior remains covered by the full OMP suite
  and the Python regression/static checks.
- No P3.2 implementation or qualification was started.

## Primary interactive OMP compaction handoff

The repeated `/compact` refusal was traced to the probe process having an
independent OMP context history. No further child-agent compaction attempt is
allowed for this proof.

The canonical primary interactive host session is:

```text
host session:
2026-08-24T05-12-05-023Z_01a0322e-d49f-74a1-9084-5e7129e7457d

hashed ledger/session directory:
state/sessions/6d5a4971da6400081c4dc915056bc8a8ea6e3f052ac87438ddeebf735ef267e6/

manifest:
state/sessions/6d5a4971da6400081c4dc915056bc8a8ea6e3f052ac87438ddeebf735ef267e6/manifest.json

telemetry:
telemetry/agent-performance/2026-08-24T05-12-05-023Z_01a0322e-d49f-74a1-9084-5e7129e7457d.jsonl
```

The canonical `active-state.json` is prepared beside the ledger and manifest:

```text
sha256 = 3f85e83742672cc4f48f0be181e9f83913a30c4074f036d7fb0f9cea2287e776
bytes  = 487

objective = P3.1-PRIMARY-COMPACT-20260824
decision  = PRIMARY-SESSION-PRECOMPACTION
question  = VERIFY-POST-COMPACT-STATE
next      = USER-ISSUE-MANUAL-COMPACT
verification = {}
```

Telemetry baseline was recorded before the manual boundary:

```text
sha256 = dd7a61d2f125b61be73f978270d0ddecef287511595fb9c3cf47b43cbb4fff29
bytes  = 47638
```

The baseline contains no `session_before_compact` record. This is intentional:
the primary OMP host must emit that event; it must not be synthesized by this
agent or a child process.

## Manual boundary verification

The user reported that `/compact` completed in the primary interactive OMP
session. Fresh repository evidence does not contain the required host-side
boundary records:

```text
primary telemetry sha256 = dd7a61d2f125b61be73f978270d0ddecef287511595fb9c3cf47b43cbb4fff29
primary telemetry bytes  = 47638
primary capsule sha256   = 3f85e83742672cc4f48f0be181e9f83913a30c4074f036d7fb0f9cea2287e776
primary capsule bytes    = 487
```

The canonical capsule remains pre-compaction state:

```text
verification = {}
next_action  = USER-ISSUE-MANUAL-COMPACT
```

The primary telemetry has no `session_before_compact`, `session_compact`,
`active_state_delivery`, or `vmem_compact_prep` record after the recorded
baseline. The canonical ledger has no compaction event rows. Therefore the
reported action cannot be correlated to the prepared capsule/session identity,
and the six required post-compaction checks cannot be claimed as proven.

No child-agent `/compact` was attempted. No P3.2 implementation or
qualification was started.

## Current disposition

```text
P3.1_PARTIAL_PRIMARY_COMPACTION_UNCORRELATED
```
