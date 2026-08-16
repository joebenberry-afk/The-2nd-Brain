# Second Brain P3 / Lean Code Promotion Evaluation Report

**Promotion Verdict**: `HOLD SHADOW — REAL CAMPAIGN INCOMPLETE`
**Date**: 2026-08-16
**Evidence source**: outputs/reports/p3-promo-eval (validity=VALID_COMPLETE only)
**Invalidated evidence**: outputs/reports/p3-promo-eval-invalidated/ (never aggregated)

---

## Campaign State: 4 valid complete pairs / 8 valid arms

- DeepSeek/Prime stratum: 4 valid pairs
- Gemini/Antigravity stratum: 0 valid pairs
- Required for completion: 14 pairs / 28 arms

## Per-Pair Ledger

| Task | Provider | Baseline Pass | Candidate Pass | Baseline +lines | Candidate +lines | Lean state (candidate arm) | Conversation ID | Validity |
|---|---|---|---|---|---|---|---|---|
| `e01` | `deepseek` | **PASS** | **PASS** | 6 | 6 | `None` | `n/a` | `VALID_COMPLETE` |
| `e02` | `deepseek` | **PASS** | **PASS** | 2 | 1 | `None` | `n/a` | `VALID_COMPLETE` |
| `e03` | `deepseek` | **PASS** | **PASS** | 13 | 9 | `None` | `n/a` | `VALID_COMPLETE` |
| `e06` | `deepseek` | **PASS** | **PASS** | 1 | 5 | `None` | `n/a` | `VALID_COMPLETE` |

## Provider Stratification

### DeepSeek v4 Flash / Prime

- `e01`: model `deepseek/deepseek-v4-flash`, baseline PASS, candidate PASS
- `e02`: model `deepseek/deepseek-v4-flash`, baseline PASS, candidate PASS
- `e03`: model `deepseek/deepseek-v4-flash`, baseline PASS, candidate PASS
- `e06`: model `deepseek/deepseek-v4-flash`, baseline PASS, candidate PASS

### Gemini 3.7 Flash / Antigravity

- (no valid real Gemini/Antigravity pairs yet)

## Gate Evaluation

- **Correctness**: PASS {"losses": []}
- **Anti-laziness**: PASS {"provable": 3, "justified": 3}
- **STOP**: FAIL/UNPROVABLE {"notes": ["e01: no Brain stop telemetry", "e02: no Brain stop telemetry", "e03: no Brain stop telemetry", "e06: no Brain stop telemetry"]}
- **Opportunity**: FAIL/UNPROVABLE {"reduced": 2, "comparable": 4}
- **Economics (real usage only)**: FAIL/UNPROVABLE {"real_usage_arms": 0, "total_arms": 8}

## Promotion Decision

> **VERDICT: HOLD SHADOW — REAL CAMPAIGN INCOMPLETE**
>
> only 4/14 valid complete pairs exist; no synthetic or cross-provider arms count

## Economics

Only real measured metrics are reported. Provider cache semantics differ between strata and are never summed into one universal number. Cost is `UNAVAILABLE-not-inferred` unless the provider/CLI reports it.

