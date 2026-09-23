# Telemetry and observability

The OMP extension records bounded session, context, tool and usage metadata;
Python validates and aggregates JSONL from
`<home>/telemetry/agent-performance/`. Supported event fields and historical
read-only kinds are defined in
[`brainstem/telemetry/SCHEMA.md`](../../brainstem/telemetry/SCHEMA.md).

This is passive measurement, not native task admission or a model/tool
controller. `tool_call` does not block tools or mutate host input. Provider
usage is counted only where the host supplies identifiable counters; absent
usage remains unknown, duplicate observations of the same billable response
are deduplicated, and a worker/session label grants no authority. Old
orchestrator/worker/STOP telemetry is historical evidence, not a current
producer or qualification claim.

The extension also supports bounded AutoInject context, approved skills and
Lean content, checkpoint-before-compaction, and byte-preserving RTD where
explicitly enabled. Those operations affect Brain-owned content; they do not
select a model or delegate work. Storage errors are reported through bounded
`extension_error` metadata without stopping native execution.

Verify retained behavior with `tests/test_telemetry.py`,
`tests/test_governor.py` and `brainstem/prime-extension/tests/`; actual host
insertion and native noninterference need isolated host-path evidence. The
older Sol/driver-guard deployment observations in milestone reports remain
historical and do not describe this candidate or the installed profile.
