# Second Brain P3 / Lean Code Promotion Evaluation Report

**Promotion Verdict**: `HOLD SHADOW`
**Date**: 2026-08-16
**Evidence source**: outputs/reports/p3-promo-eval (validity=VALID_COMPLETE only)
**Invalidated evidence**: outputs/reports/p3-promo-eval-invalidated/ (never aggregated)

---

## Campaign State: 14 valid complete pairs / 28 valid arms

- DeepSeek/Prime stratum: 4 valid pairs
- Gemini/Antigravity stratum: 10 valid pairs
- Required for completion: 14 pairs / 28 arms

## Per-Pair Ledger

| Task | Provider | Baseline Pass | Candidate Pass | Baseline +lines | Candidate +lines | Lean state (candidate arm) | Conversation ID | Validity |
|---|---|---|---|---|---|---|---|---|
| `e01` | `deepseek` | **PASS** | **PASS** | 6 | 6 | `None` | `n/a` | `VALID_COMPLETE` |
| `e02` | `deepseek` | **PASS** | **PASS** | 2 | 1 | `None` | `n/a` | `VALID_COMPLETE` |
| `e03` | `deepseek` | **PASS** | **PASS** | 13 | 9 | `None` | `n/a` | `VALID_COMPLETE` |
| `e06` | `deepseek` | **PASS** | **PASS** | 1 | 5 | `None` | `n/a` | `VALID_COMPLETE` |
| `e07` | `gemini` | **PASS** | **PASS** | 5 | 5 | `ON` | `99442368-9356-4e57-bb6b-dee9d5e4aaf9` | `VALID_COMPLETE` |
| `e08` | `gemini` | **PASS** | **PASS** | 0 | 0 | `ON` | `a8c6a9b8-a5d1-469e-8148-6a254d2c50a1` | `VALID_COMPLETE` |
| `e09` | `gemini` | **PASS** | **PASS** | 0 | 0 | `ON` | `90e8ad2a-2245-45d5-8991-0199cf89f771` | `VALID_COMPLETE` |
| `e10` | `gemini` | **PASS** | **PASS** | 5 | 5 | `ON` | `7f159ac6-353b-4007-bc7d-b797fa5a78cb` | `VALID_COMPLETE` |
| `e11` | `gemini` | **PASS** | **PASS** | 1 | 1 | `ON` | `22574947-b0f1-47d6-b2c8-2e838fdb3ec5` | `VALID_COMPLETE` |
| `e12` | `gemini` | **PASS** | **PASS** | 4 | 4 | `ON` | `c0e86d0d-31b2-44e8-bad2-eb1cc5ec4628` | `VALID_COMPLETE` |
| `e13` | `gemini` | **PASS** | **PASS** | 15 | 15 | `ON` | `e5048ae4-4a75-4975-8a21-ccb18c26381e` | `VALID_COMPLETE` |
| `e14` | `gemini` | **PASS** | **PASS** | 1 | 1 | `ON` | `7394425b-749c-415f-ad29-1eb710b223f9` | `VALID_COMPLETE` |
| `e15` | `gemini` | **PASS** | **PASS** | 5 | 7 | `ON` | `cba3a9ae-dd95-4c84-ad47-7f5e321a1a17` | `VALID_COMPLETE` |
| `e16` | `gemini` | **PASS** | **PASS** | 1 | 1 | `ON` | `8210baf0-55c7-4dbf-9bfe-65e4992e1b20` | `VALID_COMPLETE` |

## Provider Stratification

### DeepSeek v4 Flash / Prime

- `e01`: model `deepseek/deepseek-v4-flash`, baseline PASS, candidate PASS
- `e02`: model `deepseek/deepseek-v4-flash`, baseline PASS, candidate PASS
- `e03`: model `deepseek/deepseek-v4-flash`, baseline PASS, candidate PASS
- `e06`: model `deepseek/deepseek-v4-flash`, baseline PASS, candidate PASS

### Gemini 3.7 Flash / Antigravity

- `e07`: model `gemini-3.7-flash-high`, conversation `99442368-9356-4e57-bb6b-dee9d5e4aaf9`
- `e08`: model `gemini-3.7-flash-high`, conversation `a8c6a9b8-a5d1-469e-8148-6a254d2c50a1`
- `e09`: model `gemini-3.7-flash-high`, conversation `90e8ad2a-2245-45d5-8991-0199cf89f771`
- `e10`: model `gemini-3.7-flash-high`, conversation `7f159ac6-353b-4007-bc7d-b797fa5a78cb`
- `e11`: model `gemini-3.7-flash-high`, conversation `22574947-b0f1-47d6-b2c8-2e838fdb3ec5`
- `e12`: model `gemini-3.7-flash-high`, conversation `c0e86d0d-31b2-44e8-bad2-eb1cc5ec4628`
- `e13`: model `gemini-3.7-flash-high`, conversation `e5048ae4-4a75-4975-8a21-ccb18c26381e`
- `e14`: model `gemini-3.7-flash-high`, conversation `7394425b-749c-415f-ad29-1eb710b223f9`
- `e15`: model `gemini-3.7-flash-high`, conversation `cba3a9ae-dd95-4c84-ad47-7f5e321a1a17`
- `e16`: model `gemini-3.7-flash-high`, conversation `8210baf0-55c7-4dbf-9bfe-65e4992e1b20`

## Gate Evaluation

- **Correctness**: PASS {"losses": []}
- **Anti-laziness**: PASS {"provable": 13, "justified": 13, "notes": ["e03: no real tool activity + diff evidence"]}
- **STOP**: FAIL/UNPROVABLE {"provable": 12, "notes": ["e01: no Stop telemetry / LC_STOP evidence", "e03: no Stop telemetry / LC_STOP evidence"]}
- **Opportunity**: FAIL/UNPROVABLE {"reduced": 2, "comparable": 14}
- **Economics (real usage only)**: PASS {"real_usage_arms": 14, "total_arms": 28}

## Promotion Decision

> **VERDICT: HOLD SHADOW**
>
> STOP gate FAIL: missing Stop telemetry evidence
> opportunity gate FAIL: candidate reduced surface on 2/14 comparable tasks

## Economics

Only real measured metrics are reported. Provider cache semantics differ between strata and are never summed into one universal number. Cost is `UNAVAILABLE-not-inferred` unless the provider/CLI reports it.

