# Claude Project Bootstrap

@AGENTS.md
@docs/integrations/claude/LEAN_CODE_KERNEL.md

This repository **is** Second Brain — not a project consuming it. The
Second Brain Client Contract in the global CLAUDE.md still applies (fail
closed on empirical uncertainty, candidate-only writes, evidence over
summaries), but there is no separate `project_id` to resolve and no remote
Brain to query: `AGENTS.md` above is the full local contract.

Read [`docs/integrations/claude/EXISTING_PRIMITIVES.md`](docs/integrations/claude/EXISTING_PRIMITIVES.md)
before adding any Claude-facing adapter code — it maps what already exists
(memory, retrieval, telemetry, ledger, Lean Code, evidence) so it isn't
rebuilt.

## Cloud sessions (Claude Code on the web)

`.claude/settings.json` runs `scripts/cloud-session-setup.sh` at session start.
In the cloud it builds `.venv`, installs the Prime extension's `node_modules`,
sets `SECOND_BRAIN_HOME` to this checkout and loads the memory corpus from
`scripts/cloud_corpus_seed.json`; locally it does nothing. The seed is a
snapshot of the live Brain — refresh it on the Windows machine with
`python scripts/cloud_corpus.py export` and commit. Use `.venv/bin/python`
there — the `PYTHONHOME` gotcha and the `.venv\Scripts\` paths in `AGENTS.md`
are Windows-only.

The cloud VM has no OMP host, installed extension or live canonical Brain, so
live `omp` runs and installed-runtime checks must run on the Windows machine.

On Linux these tests fail for platform reasons and pass on Windows — do not
"fix" them by weakening assertions:
- `tests/test_antigravity_adapter.py` — fixtures use `C:\work\…` repo paths.
- `tests/test_prime_installer.py` — runs the `.ps1` installers via `powershell`.
- `tests/test_p3_campaign_harness.py::test_do_nothing_agent_cannot_produce_valid_arm`
  — executes a fake `.cmd` agent.
- `tests/test_release_history.py::test_sealed_approval_records_still_bind_their_own_bytes`
  — sealed digests cover the Windows (CRLF) working-copy bytes.
- `tests/test_repository_intelligence_live.py` — a real Linux defect: the
  incremental index skips a file whose mtime is within 1 ms of the stored one
  without hashing it, and Linux timestamps can be that coarse.

The current V3 baseline is
`docs/intake/Second_Brain_V3_Requirements_2026-09-24/` (start at `START_V3.md`).
