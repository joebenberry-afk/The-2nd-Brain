# P3 Lean-OFF Baseline Evidence (economics capture)

Baseline definition (plan §5.7/§0A.4): P0-P2 + ACTIVE AutoInject + P3-B
instrumentation, Lean influence OFF (Lean skill is a non-routable candidate;
no runtime adapter exists yet). All numbers are LIVE host values from the
v3 telemetry records (`assistant_usage`, `provider_request_meta`,
`provider_response_meta`) — never estimated. AutoInject packet tokens are
reported separately from Lean overhead (plan §0A.7).

## Sample 0 — driver session (01a008bb, post-restart window)
assistant_usage rows=8 | input=255204 | output=4175 | cache_read=1786624 |
cache_write=0 | cost_total=$0.121123 | AutoInject packets=3 /
packet_tokens=1489

## Sample 1 — P3-C worker (01a00948, Lean-OFF real task: create+validate candidate skill)
assistant_usage rows=64 | input=46,736 | output=19,436 | cache_read=2,387,072 |
cache_write=0 | cost_total=$0.018669 | AutoInject packets=2 / packet_tokens=995
(pkt-09140130cdcf638b 362 tok/2 items; pkt-374a5df37e07f4c2 633 tok/5 items) |
tool_call=64, tool_result=63 | files touched=1 (skill) | validation ok=True

## Notes
- cache_write=0 on both samples (provider reports no cache writes for these
  turns) — recorded exactly as exposed, zero-vs-missing preserved.
- Further samples appended as P3-D/P3-E candidate and control runs complete.

## Sample 2 — P3-E eval window (34 runs, 17 tasks × 2 arms; added 2026-08-16)

Paired-eval windows (evidence: outputs/reports/p3-eval/, analysis:
p3-lean-code-gate.md). IMPORTANT: BOTH windows ran Lean-OFF — the candidate
window's SECOND_BRAIN_LEAN=advisory never reached the daemon-spawned children
(all 34 lean_kernel records mode=null, decision=omit reason=off). No Lean
effect was measured; these are the two-window Lean-OFF aggregates.

| metric | B window sum/median | C window sum/median |
|---|---|---|
| assistant_usage rows | 189/11 | 195/11 |
| input_tokens | 288,765 / 16,812 | 304,902 / 17,102 |
| output_tokens | 125,155 / 6,700 | 144,529 / 7,316 |
| cache_read_tokens | 2,960,768 / 165,376 | 3,376,256 / 167,040 |
| cache_write_tokens | 0 / 0 | 0 / 0 |
| cost_total $ | 0.0838 / 0.0047 | 0.0926 / 0.0047 |
| tool_calls | 210 | 213 |
| wall_ms | 1,318,628 / 70,004 | 1,467,109 / 75,702 |
| AutoInject packets | 51 / 3 per run | 51 / 3 per run |
| AutoInject packet_tokens | 44,591 / 2,623 | 44,591 / 2,623 |

Acceptance: 17/17 per window, 34/34 total (judge exits all 0, full sequences
run). New files across 34 runs: required deliverables only. Per-pair table:
p3-lean-code-gate.md. Marginal Lean kernel cost: NOT MEASURED (zero
injections); planning bound 865 chars ≈ 216 input tokens/turn.
