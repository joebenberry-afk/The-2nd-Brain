# Second Brain OMP extension

Candidate-only extension for memory, context, approved skills, continuity, and
passive telemetry. The native host owns agent creation, model selection, tool
permissions, cancellation, retries, completion, and STOP. This extension does
not classify a coordinator, dispatch workers, reserve agent budgets, or patch
the host. Old `orchestration.toml` values and controller environment variables
do not reactivate those behaviors.

## Retained behavior

- Session/header correlation, project isolation, active-state and ledger mirror,
  checkpoint-before-compaction, and context paging/recovery.
- AutoInject retrieval: `shadow` records a decision without model-visible
  content; `advisory`/`active` may add a bounded low-authority context packet.
  Source content and project identifiers never grant execution authority.
- Approved skill visibility/Lean kernel consumption, subject to the canonical
  approval and exact-byte rules. No model allowlist appoints an agent role.
- Reversible Tool Distillation preserves eligible raw results before replacing
  model-visible content; a failed preservation path leaves the original result.
- Provider request/response and usage observations record the host's actual
  identity and supported counters. Missing usage remains unknown. No model
  choice, tool block, or agent-spend cap is inferred from those records.

`tool_call` observes bounded metadata and optional reread hints; it does not
block native tools. `before_agent_start` composes approved Brain context with
the host prompt without a coordinator contract. `session_shutdown` flushes the
retained active state and telemetry. The precise JSONL fields and historical
read-only kinds are in [`../telemetry/SCHEMA.md`](../telemetry/SCHEMA.md).

## Candidate identity and isolation

`SECOND_BRAIN_HOME` selects a Brain home; `SECOND_BRAIN_PYTHON` selects the
runtime. Set both explicitly for isolated qualification, clear inherited
`PYTHONHOME`/`PYTHONPATH`, and confirm the imported source belongs to the
candidate. A running extension is bound to the home/runtime it loaded until
restart or `/reload`; changing an environment variable mid-session is not a
safe retarget. `brainctl doctor --home <home>` reports the selected identity.

A native child is a separate context recipient. Shared knowledge may be read by
several agents, but one child's delivery acknowledgment cannot be borrowed by
another. Native `task`/`hub` output is observational, not a Brain settlement
receipt. No legacy worker-context or model-routing request may create state;
explicit retired requests return `ORCHESTRATION_REMOVED` or
`MODEL_ROUTING_REMOVED` through the Python transport.

## Develop and install

Run `bunx tsc --noEmit`, `bunx eslint src tests`, and `bunx vitest run` from this
directory. These are candidate checks, not proof of an installed host path.

`scripts/install-prime-extension.ps1` copies flat `src/*.ts` and
`types/*.d.ts` into an explicitly selected extension directory, with a
pre-install backup. `scripts/uninstall-prime-extension.ps1` requires that
backup path for byte-exact restore. Neither script installs a patched OMP host.
`scripts/generate_omp_deployment_manifest.py` can snapshot and compare an
extension-only disposable candidate; its output is **not** protected approval
or production authorization. The current production installation is not
changed by repository edits. Applicable approval, executable-trust, and
rollback findings remain open until independently qualified.
