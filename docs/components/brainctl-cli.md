# brainctl (Python Control CLI)

## Purpose
Single user/automation entry point for all Brain operations (plan §82).

## Problem it solves
One stable command surface instead of ad-hoc scripts.

## Responsibilities
- `argparse` CLI; `--home` accepted before or after the subcommand (SUPPRESS default so leaf defaults don't clobber it).
- Commands (handlers dict in `main()`): `init` (refuses non-empty non-Brain unless `--force`; layout + seed + git init + migrate), `doctor`, `status`; `project add|list|status|detach`; `backup`; `restore`; `telemetry report|validate`; `capsule init|update|show`; `requirements add|evidence|status|show|check`; `read-ledger record|show`; `context compile`; `artifact store|expand|list` (store reads stdin or --path, prints handle + distilled + hint; expand writes raw bytes); `scout` (--no-agent, --model, --ext, --output).
- `BrainError` → `brainctl: error: ...` on stderr, exit 2.

## Non-responsibilities
No auto-behavior/daemon/background work; formatting and dispatch only.

## Inputs
argv; stdin (artifact store); `SECOND_BRAIN_HOME`.

## Outputs
Reports/files; exit codes (0 ok, 1 command failure, 2 BrainError/refusal).

## State ownership
None (delegates to subsystems).

## Invariants
All state mutation happens in subsystems; `--home` works after subcommands.

## Interactions
Wires all subsystems; bootstrap.ps1 calls `python -m second_brain init|doctor`; brainctl.cmd is the sanitized launcher.

## Failure behavior
BrainError → stderr + exit 2; init refuses unsafe dirs; doctor exits 1 when unhealthy; scout returns agent rc.

## Verification
`tests/test_cli.py` (7): init→doctor→status flow, init refusal, project add/list/status, backup/restore CLI, unknown project, --home placement; full suite (165 tests) covers every wrapped subsystem.

## Known limitations
No completion/help polish; `artifact expand` writes binary to stdout (Windows console caveats); no interactive mode.

## Future extension
Phases 7+ add capture/recall/memory/skills/sleep/immune/benchmark commands (plan §82); shell completion.

## Relevant decisions
`decisions/global/2026-08-14-build-decisions.md` #2.

## Relevant tests
`tests/test_cli.py` + each subsystem's test file.
