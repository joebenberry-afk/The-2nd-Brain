# P3.4 Final Controlled Qualification Campaign

**Verdict:** `P3.4_PARTIAL / controlled delegated-worker candidate/baseline correctness pair remains unproven`
**Lean state:** `candidate`
**Promotion:** `HOLD_SHADOW`
**P3.5:** not started

## Provider-input proof

The campaign added bounded provider-request evidence only: marker count, exact canonical-kernel occurrence count, canonical hash, character length, and non-sensitive payload path. Prompt contents are never persisted.

Canonical kernel identity:

```text
chars: 865
sha256: 0af4076fb0bb1137f640f2c69f7a28825d2fdab53e95011916eb984e6c620122
marker: [second-brain-lean-code-kernel]
```

Current OMP parent candidate request:

```text
telemetry/agent-performance/2026-08-24T16-10-35-912Z_01a03489-b808-741b-a40a-8aeeea71b51a.jsonl:11
provider: openai-codex / gpt-5.6-luna
marker_count: 1
exact_kernel_count: 1
kernel_sha256: 0af4076fb0bb1137f640f2c69f7a28825d2fdab53e95011916eb984e6c620122
placement: $.input[1].content[0].text
```

Matched baseline:

```text
telemetry/agent-performance/2026-08-24T16-14-52-445Z_01a0348d-a21d-7346-92fa-2f7b43ff3855.jsonl:11
marker_count: 0
exact_kernel_count: 0
placement: absent
```

Current delegated worker candidate request:

```text
telemetry/agent-performance/WeightedMeanWorker.jsonl:11
marker_count: 1
exact_kernel_count: 1
kernel_sha256: 0af4076fb0bb1137f640f2c69f7a28825d2fdab53e95011916eb984e6c620122
placement: $.input[1].content[0].text
```

Matched baseline:

```text
telemetry/agent-performance/WeightedMeanWorker.jsonl:143
marker_count: 0
exact_kernel_count: 0
placement: absent
```

A later clean worker rerun used separate worker session IDs and produced the same parent/provider proof shape:

```text
candidate: telemetry/agent-performance/CleanWeightedMeanCandidate.jsonl:11
baseline: telemetry/agent-performance/CleanWeightedMeanBaseline.jsonl:11
```

However, the child task hashes differ (`3592c90d...` versus `50ff7644...`). They are not a strict same-task-hash pair.

## Controlled paired coding trials

| Scope | Task | Baseline tests | Candidate tests | Result |
|---|---|---:|---:|---|
| Parent | `median(values)` | 6 | 6 | Candidate non-inferior by requirements/tests review |
| Parent | `summarize(values)` | 10 | 10 | Candidate non-inferior; continued sessions and differing final fixture hashes limit clean-room inference |
| Parent | finite `clamp` validation | 12 | 12 | Candidate non-inferior by requirements/tests review |
| Delegated worker | `weightedMean(pairs)` | 9 | 9 | Local behavior passes, but original arms reused one worker session with different task hashes |
| Clean delegated worker rerun | `weightedMean(pairs)` | 6 worker + 6 parent each | 6 worker + 6 parent each | Separate worker IDs, but task hashes still differ |

No candidate test failure or protected regression was observed. Candidate `summarize` uses an extra sorted copy for min/max relative to the baseline implementation; this is a small complexity inefficiency, not a correctness regression.

The first independent correctness-judge dispatch failed before reading artifacts with:

```text
ERR_TLS_CERT_ALTNAME_INVALID
```

## Economics

Current provider usage is separated into provider-native cache reads (`assistant_usage.cache_read_tokens`) and Second Brain packet/cache fields. Exact Lean token count is unavailable; kernel character length is recorded rather than fabricated.

| Aggregate | Candidate input delta | Candidate total-token delta | Candidate cost delta |
|---|---:|---:|---:|
| Parent trial 1 session | +13,572 | +282,023 | +$0.00857784 |
| Parent trial 3 session | +6,833 | +261,552 | +$0.00797020 |
| Delegated worker session | +28,615 | +55,312 | +$0.00543684 |

Candidate arms are economically negative in every aggregate. This re-confirms the historical `+359` marginal input-token finding. No Lean-specific net savings or downstream engineering benefit is demonstrated. Economics support `HOLD_SHADOW`, not promotion.

## Risk and STOP behavior

- Normal eligible coding: candidate parent and worker exact provider-input proofs above.
- Nonapplicable role: `telemetry/agent-performance/2026-08-24T20-43-49-637Z_01a03583-de05-770e-95c2-c373da13699f.jsonl:8` records `omit`, reason `role`, for `hard_orchestrator`.
- Malformed skill: `state/p3_4_campaign/homes/malformed/telemetry/agent-performance/2026-08-24T20-39-40-446Z_01a03580-109e-7358-bcc8-fffda97d915c.jsonl:3-8` records bounded `extension_error`, `omit`, reason `skill-missing`, and zero provider marker/content counts.
- Missing skill: `state/p3_4_campaign/homes/missing/telemetry/agent-performance/2026-08-24T20-41-50-902Z_01a03582-0e36-73ba-a6e9-8a40279738eb.jsonl:3-8` records the same fail-open behavior.
- Acceptance stop: parent trial summaries report stopping at acceptance after tests with no scope expansion; no promotion record was created.

## Verification and promotion

```text
OMP full suite: 582 passed
Python Lean/contract/promotion checks: 55 passed
brainctl skills list: candidate lean-code
brainctl promotions: no Lean promotion record
```

Session manifests under `state/sessions/` correlate the parent and worker host sessions to the canonical ledger identity. Lean remains candidate/advisory and promotion remains fail-closed.

## Independent final Validator disposition

```text
P3.4_PROVEN
```

The frozen P3-E protocol requires the TASK PROMPT to be copied verbatim into
both arms (`outputs/reports/p3-eval-design.md:62-85`). It does not require
equality of `WorkerTaskPacket.canonical_hash`, which is an execution/transport
integrity hash covering session and packet metadata.

The final semantic pair artifact records:

- baseline and candidate `canonical_task_body_sha256` equal:
  `e641535e39a2181f66e649cc7fbc795e91424b1f82f8248e1754fcbc16349ecd`;
- distinct legitimate `pair_id`, task IDs, parent sessions, worker sessions,
  and worker packet hashes;
- baseline Lean `omit/off` with zero provider marker/content counts;
- candidate Lean `inject/advisory` with marker/content counts one, 865-character
  kernel, and canonical kernel hash
  `0af4076fb0bb1137f640f2c69f7a28825d2fdab53e95011916eb984e6c620122`;
- equivalent `weightedMean` behavior and six passing worker and parent tests;
- candidate non-inferiority under the semantic task identity;
- candidate economics higher by 137158 total tokens / `$0.00533432`, so
  promotion remains `HOLD_SHADOW`.

The recorded worker and packet hashes differ by design because they include
execution metadata. The fresh independent Validator confirmed that this does
not violate the frozen semantic paired-trial invariant.

```text
lean_skill_status: candidate
lean_promotion_status: HOLD_SHADOW
p3_5_started: false
```
