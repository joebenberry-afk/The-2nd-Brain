# V3 S2 contract (recorded before any S2 evaluation)

Date: 2026-09-24. Parent candidate: `brain/v3-s1` @ `c273f6d` (clean). Installed runtime,
live DB, live config and installed extension stay unchanged (`qualified-m00` @ `749e9cd`).
S1's `outputs/reports/v3-s1/RESOURCE_PROFILE.frozen.json` is preserved unchanged; S2 adds to it
only by a new frozen file, never by editing it.

## Accepted timing definitions (from S1 frozen profile, not relaxed)

- Warm no-benefit incremental blocking time: **median ≤ 10 ms, p95 ≤ 50 ms**, whole turn, vs the
  inert-extension arm, OS cache warm, Brain runtime already started if the design keeps one.
- Cold incremental time to first dispatch: **p95 ≤ 100 ms**, first prompt after host start,
  includes Brain process/interpreter start, imports, config and DB open.
- The 100 ms figure is the cold budget only; it is not a warm allowance.
- User-facing overhead is reported against native; attribution against inert.

## Configurations

| Name | Code | Lean advisory | Purpose |
|---|---|---|---|
| native | — | — | user-facing baseline |
| inert | inert hooks | — | host hook-dispatch cost |
| m00 | installed 749e9cd | live (`advisory`) | unchanged comparison arm |
| candidate | S2 head | **off (intended V3 shipping setting)** | subject |
| candidate+lean | S2 head | `advisory` | configuration ablation (code vs config gain) |

The candidate's Lean setting is shipped in the candidate's own config templates/installer, so
the qualified configuration equals the deployable one. Data-access, integrity and isolation
protections are not configuration-ablated.

## Experiments and decision rules

- **Injection decision (PERF-01, RET-05):** retrieval and the decision to inject are separate.
  Pass = zero Brain-added provider-request content (system text, messages, schemas, wrappers,
  extra model calls) on every held-out no-benefit case, measured on the captured final request
  with provider token counts; AND required-memory recall on held-out memory-needing cases ≥ the
  M00 arm and ≥ 90%. No per-prompt, per-word or length/“no tools” special cases.
- **Long-prompt focus (RET-02):** cases where the full-prompt search returns (a) nothing and
  (b) an irrelevant non-empty result; imperative (no `?`) requests; mixed instructions; paths,
  symbols, error ids, appended constraints. Pass = required memory recovered, constraints kept.
- **E01 runtime:** current path vs reduced/batched one-shot path vs reused interpreter. A
  critical-path span breakdown must reconcile to within 10% of the measured added latency before
  any design is chosen. Adopt the simplest design meeting the timing budgets above. A reused
  interpreter serves memory operations only (no host-agent authority) and must pass isolation,
  identity, bounded-queue/memory, concurrency, stale-state, restart and cleanup checks.
- **E02 semantic:** corrected lexical vs small local encoder vs hybrid, same relevance,
  abstention, token, latency and RAM criteria. Encoder ships only if it improves held-out
  memory-needing recall by ≥ 5 points without reducing no-benefit abstention and stays within
  the S1 encoder budget (≤ 1024 MiB resident, no GPU, offline). Otherwise lexical ships.

## Dataset split

- `dev/`: cases usable for tuning, including the already-exposed `NB-OK-17` no-benefit prompt
  and the M00 migration-order pair (regressions, never held-out evidence).
- `heldout/`: written and hashed before any tuning run; its sha256 is recorded here when
  created and it is not opened by tuning code. Categories: self-contained direct answers,
  formatting instructions, misleading keyword overlap, short memory-dependent requests,
  project-specific questions, stale / wrong-project memories, imperative long prompts.
- Held-out results produced after any change informed by them are reported as dev results.

## Validation plan

Cheap local trials (deterministic, many repetitions) first; then the bounded live campaign with
the four main arms plus the Lean ablation, seeded interleaving, separate cold/warm, all failures
and timeouts retained. Fault injection: missing helper/interpreter, DB locked/unavailable,
checkpoint failure, malformed response, concurrent project requests. Antigravity/Hermes lifecycle,
offline and Linux: run where available, else NOT_RUN. Independent reviewer before the report.
No install, reload, push, tag or deployment claim.

## Held-out freeze

`heldout/cases.jsonl` sha256 `add744f7d057bb9bb1d6185f9c92916b17d6131c9daa0568651606beedf8bb3f` (18 cases), frozen before any S2 tuning run. `dev/cases.jsonl` holds the exposed regressions and tuning cases.
