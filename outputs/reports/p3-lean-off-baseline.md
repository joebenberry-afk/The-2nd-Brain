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
