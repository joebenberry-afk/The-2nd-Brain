# Second Brain V3 — OMP extension

One file, `index.ts`, with no dependency on the legacy extension, on OMP's type package or on
any OMP-version internal. It reads the Brain's precompiled views and pushes at two moments only:

| Moment | Adds | Budget |
|---|---|---|
| a session's first turn, and the first turn after compaction | the project brief (`views/<project>/brief.md`) | ≤ 600 tokens; nothing when the project has no current records |
| a failed tool call whose error matches a tested correction | that one correction, appended to the tool result | ≤ 80 tokens |

Everything else adds nothing, and nothing runs a process or a search. Host fields are read
defensively: if an OMP update renames one, the extension adds nothing instead of failing.

The Brain does not need this extension to work. Records, search and views are plain files and
the `brain` CLI, usable from any shell or agent (`brain q "<question>"`, `brain brief`).

## Install (Windows)

```powershell
pip install -e .                    # in the Brain checkout: provides `brain`
$env:SECOND_BRAIN_HOME = "<Brain checkout>"   # set it permanently for OMP too
brain views                         # compile the views (derived; rerun after pulling records)
.\scripts\install-omp-v3.ps1 -DisableLegacy   # parks the legacy extension (reversible)
```

Restart OMP. Undo: `.\scripts\uninstall-omp-v3.ps1 -RestoreLegacy`. Telemetry: one line per
push decision in `$SECOND_BRAIN_HOME/telemetry/kb-hooks.jsonl` (event, tokens, ms).
