# Phase 5 — Deploy the Exact Repaired Build Into OMP

## Deployment mechanism used

`scripts/install-prime-extension.ps1` copies the extension into
`~/.prime/agent/extensions/` for the **Prime Agent** harness. That is not
the mechanism OMP uses (confirmed in Phase 1): OMP loads the extension
directly from the repository path via `-e ./brainstem/prime-extension/src/index.ts`
with no separate install/copy step. Since OMP-first is this campaign's target
harness, the intended production deployment mechanism for OMP is direct-path
loading against the qualification worktree — there is no distinct "install"
artifact to deploy for OMP; the repository checkout itself is the deployed
build. The Prime installer script remains correct for its own (Prime-only)
target and is out of scope here.

## Tasks and evidence

1. **Runtime/state independence** — verified via explicit `--home` +
   `SECOND_BRAIN_HOME` vs the Python runtime path (`.venv/Scripts/python.exe`);
   these are three independently-settable values (`doctor`'s "identity
   coherence" line reports `state=`, `runtime=`, `python=` separately).
2. **Manifest hashes after install** — N/A (no install-copy step for OMP);
   the equivalent check is `adapter_build_fingerprint`, verified below.
3. **Build identity** — `second_brain --home <worktree> doctor`:
   ```
   [PASS] build identity — version=2.0.0-rc.1 sha=3540160caf04 (clean)
          schema=21 adapter=1cf568d9bb2c qualified_baseline=4af64affdf4f
   ```
   `sha=3540160caf04` matches `git rev-parse HEAD` on `brain/v2-omp-qualification`
   at the time of this check, `(clean)` confirms no uncommitted dirty state,
   `adapter=1cf568d9bb2c` is the current `brainstem/prime-extension/{src,types}`
   fingerprint (recomputed after the cache fix — confirms the fingerprint is
   live, not stale/cached), `qualified_baseline=4af64affdf4f` correctly still
   traces provenance to the frozen v1 P4 baseline.
4. **No accidental cwd dependency** — ran
   `second_brain --home "C:/.../.worktrees/v2-one-shot" doctor` from
   `C:/Users/assas/Documents` (a directory outside every Second Brain
   checkout) with explicit `SECOND_BRAIN_HOME` matching `--home`:
   ```
   [PASS] identity coherence — state=...v2-one-shot, runtime=...v2-one-shot, python=.../.venv/Scripts/python.exe
   [PASS] build identity — version=2.0.0-rc.1 sha=3540160caf04 (clean) schema=21 adapter=1cf568d9bb2c qualified_baseline=4af64affdf4f
   ```
   Identical SHA/schema/adapter output regardless of invocation cwd — zero
   cwd dependency. (A stray environment-level `SECOND_BRAIN_HOME` leaked from
   this session's own shell history and briefly produced a `[FAIL] identity
   coherence` diagnostic when NOT explicitly overridden — this is the doctor
   check correctly catching an env/home mismatch, not a code defect; see
   below.)
5. **No dependency on a Prime executable** — see
   `33-native-dependency-audit/NATIVE_DEPENDENCY_AUDIT.md` (already proven:
   zero Prime binary spawns anywhere in the extension).
6. **Start OMP with the intended extension** — done throughout Phases 6-9 via
   `omp -e ./brainstem/prime-extension/src/index.ts` against this exact
   worktree; every session's `OMP_SECOND_BRAIN_READY`/`autoinject_shadow_decision`
   telemetry carries this build's identity.
7. **Capture startup stdout/stderr** — every live `omp --print` invocation in
   this campaign captured stdout/stderr inline (see Phase 6-9 evidence); no
   extension error occurred on any clean startup in this campaign.

## Incidental finding: `doctor`'s identity-coherence diagnostic works as designed

While preparing this phase's cwd-independence check, a `SECOND_BRAIN_HOME`
environment variable left over from earlier session history (pointing at the
parent repository, not this worktree) was still exported in the shell.
Running `doctor --home .` (inside the worktree) WITHOUT also overriding that
stray env var correctly produced:
```
[FAIL] identity coherence — requested home=...v2-one-shot, environment home=...The-Second-Brain
```
while every other check (build identity, sha, adapter, schema) still used the
CORRECT explicit `--home` value throughout. This is the diagnostic doing
exactly its job (catching an env/home divergence) — not a product defect —
and directly demonstrates why Phase 17 (Runtime/State Separation) and the
plan's "no hidden assumption that runtime and state share one installation
root" gate matter. Unsetting the stray variable restored a clean PASS.

## Gate 5

**PASS.** OMP launches normally against this exact build; the extension
initializes; the exact SHA (`3540160caf04`) is proven via `build_identity`
independent of any install-copy step; the correct state home is proven
independent of invocation cwd; no Prime executable is needed; no extension
error occurred during any clean startup performed in this campaign.
