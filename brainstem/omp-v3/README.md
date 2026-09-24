# Second Brain V3 — OMP extension and cutover runbook

One file, `index.ts`, with no dependency on the legacy extension, on OMP's type package or on
any OMP-version internal. It reads the Brain's precompiled views and pushes at two moments only:

| Moment | Adds | Budget |
|---|---|---|
| a session's first turn, and the first turn after compaction | the project brief (`views/<project>/brief.md`) | ≤ 600 tokens; nothing when the project has no current records |
| a failed tool call whose error matches a tested correction | that one correction, appended to the tool result | ≤ 80 tokens |

Everything else adds nothing, and nothing runs a process or a search. Host fields are read
defensively: if an OMP update renames one, the extension adds nothing instead of failing. It also
appends each tool result to `state/kb-events/` (local, Brain-owned format) so `brain capture` can
propose learnings without parsing OMP transcripts.

The Brain does not need this extension to work. Records, search and views are plain files and
the `brain` CLI, usable from any shell or agent (`brain q "<question>"`, `brain brief`).

## 1. Install (Windows, in the Brain checkout)

```powershell
git status                                      # commit or stash local changes first
git fetch origin
git switch claude/new-session-nro2r6            # the V3 branch (or the branch it was merged into)
$env:PYTHONHOME = $null; $env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pip install -e .   # provides brain.exe in .venv\Scripts
[Environment]::SetEnvironmentVariable("SECOND_BRAIN_HOME", (Get-Location).Path, "User")
$env:SECOND_BRAIN_HOME = (Get-Location).Path
# memories added on this machine since the V3 snapshot (existing records are skipped):
.venv\Scripts\brain.exe convert --from-db db\brain.sqlite --legacy-home .
.venv\Scripts\brain.exe doctor                  # expect: errors (0)
.venv\Scripts\brain.exe views                   # compile briefs and correction tables
.\scripts\install-omp-v3.ps1 -DisableLegacy     # parks the legacy extension (reversible)
```

Restart OMP.

## 2. Verify in the first sessions

1. Start OMP in the Brain checkout. The first turn should carry the brief (hidden custom
   message `brain.v3.brief`); later turns add nothing.
2. `Get-Content $env:SECOND_BRAIN_HOME\telemetry\kb-hooks.jsonl -Tail 5` — one `brief` line per
   session with `tokens` (≤ 600) and `ms`; `correction` lines only after failed tool calls.
3. Trigger a known error (e.g. run bare `python` with a broken `PYTHONHOME`): the failed tool
   result should end with `Brain correction (advisory): … [mem-b67de5057f76]`.
4. After a few sessions: `brain review` — the inbox shows proposed gotchas from failed-then-fixed
   commands; `brain accept <id>` / `brain reject <id> --reason …`; promote the good ones with
   `brain promote <id> --reason …` (needs evidence).
5. Across machines: `brain sync` commits `records/` and `projects/`, pulls, rebuilds, pushes.
   `records/private/` never leaves the machine.

## 3. Live comparison (qualification)

```powershell
python scripts\v3_value_suite.py --out outputs\reports\v3-agent-experience\value\v3 `
  --reps 3 --arms native,v3 --seed 20260924 --model deepseek/deepseek-flash --thinking low
```

The pass rule is the suite's own (memory tasks: net reduction in tokens or tool calls with
correctness not below native; no-benefit tasks: no increase). Keep the report under
`outputs/reports/`.

## 4. Rollback

```powershell
.\scripts\uninstall-omp-v3.ps1 -RestoreLegacy
```

Restart OMP. Records stay in `records/`; nothing in the legacy store was changed by V3.

## 5. Retiring the legacy runtime

Only after the live comparison passes and V3 has run in daily use without a rollback: archive the
legacy modules listed in the redesign (§5) under `second_brain/legacy/`, remove their CLI
registrations, keep their tests runnable on demand, and delete them one release later. Until
then the legacy runtime and `memory/` stay untouched so rollback is always one command.
