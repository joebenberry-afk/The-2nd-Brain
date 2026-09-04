# Phase 18 — Backup and Restore Under Real OMP State

## Setup

State backed up after 40+ real OMP sessions accumulated across this entire
campaign: 13+ real sentinel memories (`memory/semantic/mem-*.md`, including
every Phase 8/9/10/16 sentinel), decisions/experiences/engrams/skills/
constitution/config directories, and the live `db/brain.sqlite`.

## Backup

```
brainctl backup --note "phase18-qualification-backup-test"
-> backups/backup-20260904-192019-343696/
```

`manifest.json` (format 2) records:
- **Runtime identity**: `version: 2.0.0-rc.1`, `git_sha: bbbb327...` (HEAD at backup time).
- **DB reference**: `{"file":"brain.sqlite","sha256":"046cb875...","schema_version":21}`.
- **Per-file SHA-256 hashes** for every canonical file — verified: all
  sentinel memories from this campaign present with correct hashes
  (`mem-736677e29a1a.md`, `mem-697f82879357.md`, `mem-38d87196587e.md`,
  `mem-74dda20ea9e8.md`, `mem-633f43de8534.md`, `mem-2e45e55dec46.md`, etc).
- **Explicit scope model**: `canonical_paths` (memory/experiences/decisions/
  projects/skills/engrams/constitution/config) vs. three exclusion
  categories — `derived` (db/state/telemetry/plasticity/sleep — rebuildable,
  matching this repo's own AGENTS.md canonical-vs-derived rule), `runtime`
  (backups/logs/outputs — self-referential, avoids backup-of-backups), and
  `external_reference` (brainstem/src/scripts/tests/templates — git-tracked
  source code, not Brain data). `db` is `.venv`-adjacent but backed up
  separately via its own hash-verified reference despite being categorized
  "derived" — a deliberate convenience copy, not the canonical source of
  truth for schema state (migrations are).

## Mutation + restore (isolated copy, live state never touched)

Copied the full canonical tree (`memory`, `experiences`, `decisions`,
`projects`, `skills`, `engrams`, `constitution`, `config`, `db`, `VERSION`)
to an isolated scratch directory. Two destructive mutations:
1. **Content corruption**: overwrote `mem-736677e29a1a.md` with garbage text.
2. **Deletion**: removed `mem-697f82879357.md` entirely.

```
brainctl --home <scratch> restore backups/backup-20260904-192019-343696 --force
-> Restored from backups\backup-20260904-192019-343696 into <scratch>
```

**Byte-exact verification** (SHA-256 comparison, original vs. restored):
- Corrupted file: **match = True**.
- Deleted file: **match = True** (fully recreated).
- `PRAGMA integrity_check` on the restored `db/brain.sqlite`: `ok`.

## Start OMP against the restored state (usability proof)

```
SECOND_BRAIN_HOME=<scratch> omp --print -e ./brainstem/prime-extension/src/index.ts \
  "What is the canonical build artifact staging directory configured for this project?"
```

The agent used its own `grep`/`glob`/`read` tools to locate and read the
restored `memory/semantic/mem-736677e29a1a.md` directly, correctly cited it
by id and title, and correctly flagged the memory's claim as
unverified/advisory (matching Phase 8's original proof exactly) — the
restored canonical data is genuinely present, correct, and usable, not
merely byte-identical on disk.

Second Brain's own AutoInject bridge did **not** fire in this run
(`extension_error: "ledger mirror: context paging failed: no brain venv
(vmem list unavailable)"`) because the scratch directory has no `.venv` —
correctly and by design: a Python virtualenv is a build/dependency artifact
tied to `SECOND_BRAIN_PYTHON` (Phase 17's separate runtime axis), never
part of `canonical_paths`/backup scope, and its absence produced an
observable, fail-open error rather than a crash or wrong-project guess.
This is the expected, documented separation, not a restore defect: a full
production restore additionally requires a runtime install alongside the
restored data, exactly as Phase 17 established runtime and state are
independently configured.

## Gate 18

**PASS.** Restore recovered a bootable, coherent, byte-exact Second Brain
state (both a corrupted file and a fully deleted file were correctly
recovered, DB integrity confirmed) that a live OMP session could genuinely
read and reason over correctly — not merely files that hash correctly.
