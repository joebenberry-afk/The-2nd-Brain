# Phase 21 — Latency Qualification

All percentiles computed from real telemetry accumulated across this
entire campaign: **74 live OMP session telemetry files, 78 AutoInject
decision samples, 136-175 provider/routing round-trips, 65-67 full
sessions** — not a synthetic microbenchmark.

## Second Brain local processing (AutoInject bridge, `autoinject_shadow_decision.latency_ms`)

| n | median | p90 | p95 | max | min |
|---|---|---|---|---|---|
| 78 | 532ms | 807ms | 944ms | 1559ms | 0ms* |

*0ms samples are cache hits (Phase 9) — correctly near-instant, no spawn.

## OMP/model latency (provider request -> response round-trip)

| n | median | p90 | p95 | max | min |
|---|---|---|---|---|---|
| 175 | 1032ms | 2546ms | 2765ms | 6521ms | 681ms |

## Routing bridge (invocation -> response; includes its own provider call, same order of magnitude as the model latency above by design — routing is itself a routed model call)

| n | median | p90 | p95 | max | min |
|---|---|---|---|---|---|
| 136 | 1035ms | 2487ms | 2757ms | 5637ms | 737ms |

## Full session wall-clock (`session_start` -> `session_shutdown`, outliers >5min excluded — one 93-minute idle `hub`-managed test session dropped, N/A to steady-state latency)

| n | median | p90 | p95 | max | min |
|---|---|---|---|---|---|
| 65 | 15.8s | 44.0s | 56.7s | 83.6s | 1.8s |

## Decomposing the local-processing 532ms median (direct measurement, isolated)

| Component | Measured (median of 3 runs) | Share of AutoInject latency |
|---|---|---|
| Raw Python interpreter bootstrap (`python -c "pass"`) | ~78ms | ~15% |
| `second_brain` package import + argparse (`-m second_brain autoinject shadow` with an empty task, no real work) | ~242ms total (so **~164ms** import overhead beyond bare bootstrap) | ~31% |
| Actual retrieval/business logic (remainder: 532ms total AutoInject latency minus the ~242ms fixed CLI-startup floor) | ~290ms | ~55% |

**If latency is dominated by repeatedly launching Python processes**: partially
yes — the fixed CLI-startup floor (~242ms, of which ~78ms is unavoidable
interpreter bootstrap and ~164ms is `second_brain`'s own import graph) is a
**real, identified, non-trivial floor** on every single AutoInject/routing/
visibility/worker-context/worker-result bridge call, since each is an
independent process spawn (no persistent daemon). This floor is roughly
half of the median 532ms AutoInject latency and is paid on **every**
`before_agent_start`, not amortized.

## Open, honestly-unresolved gap

Phase 20's W1 paired test showed a **6.5s wall-clock difference** between A
(no extension, 3.99s) and B (extension loaded, 10.53s) for a single trivial
turn — far larger than the ~532ms AutoInject bridge latency plus routing's
own provider round-trip would explain in isolation. The bridge-level
telemetry above accounts for roughly 0.5-1.5s of that gap; the remainder is
most likely OMP's own one-time extension-loading/discovery cost for a
`-e <path>` external extension file (not present in the `--no-extensions`
control at all) plus the additional model round-trip that routing itself
performs (routing's own provider call, ~1s median, is genuinely separate
from and in addition to the main turn's provider call). This gap is
reported rather than hidden: no single measured component fully explains
it, and averaging model-response time together with local overhead (which
this report deliberately does NOT do) would have hidden exactly this kind
of discrepancy.

## Pathological-regression check

No pathological regression found: the p95/max local-processing latencies
(944ms/1559ms) remain well under one second at p95 and under two seconds at
max, and every single live session in this entire campaign (70+ sessions)
completed and returned a response — no observed hang, timeout-without-
recovery, or runaway retry loop attributable to Second Brain's own bridges.
