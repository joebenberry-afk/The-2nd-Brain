# Action Cache Runtime Integration

Phase R5. Confirms the Prime `tool_call` host limitation from R1, then
builds the narrowest Brain-owned layer where deterministic actions can
actually be reused — and, in doing so, found and fixed two real bugs that
made that layer non-functional even before Prime enters the picture.

## 1. Prime native bypass: confirmed capability-limited, not worked around

Per R1 ([02-prime-live-callgraph.md](02-prime-live-callgraph.md)):
`ToolCallEventResult` (`prime.d.ts:189-192`) is `{ block?: boolean; reason?:
string }` — no field to supply a result and skip execution. Re-confirmed
here, unchanged. Per the plan's explicit instruction, this is **not**
hacked around and Prime is **not** claimed to have native Action Cache
execution bypass. That claim stays capability-limited at the Prime layer.

## 2. The narrowest legitimate Brain-owned layer: `second_brain action-cache search`

New CLI subcommand, `second_brain action-cache search <pattern> [--path
DIR] [--max-matches N] [--json]`
(`src/second_brain/cli.py`: `_action_cache_search` +
`_code_search_git_tracked`), reusing existing, unmodified machinery:
`ActionCacheStore.get_or_execute()`, `ActionType.CODE_SEARCH`, and the
`git_tree_unchanged` predicate the R4 allowlist already recognizes. Any
caller — a script, another harness's tool wrapper, a human — invokes this
instead of running a raw search directly, and gets genuine execution
bypass on a cache hit: `_code_search_git_tracked` (walks `git ls-files`,
regex-matches each tracked file) does not run at all when the proof
validates.

Gated by `git_tree_hash_for(target_dir)` (extracted from
`ActionCacheStore._get_git_tree_hash` into a top-level function so the CLI
caller can compute the same proof the store will validate). When the
target isn't a git worktree, the command **does not cache at all** —it
computes directly every time — because a `None` git_tree_hash proof would
never be re-checked (see `validate_proof`: the git-tree check is skipped
entirely when `git_tree_hash is None`), so caching without one would mean
never invalidating on real content changes.

## 3. Two real bugs found by testing this integration, not asserted from code presence

Per the plan's Claude-specific discipline ("never infer execution from
code presence"), the new command was smoke-tested end to end before being
declared working — and it wasn't, twice:

### Bug 1 — `get_or_execute()` computed a different key than `store_action()`

`get_or_execute()`'s `compute_action_key()` call omitted `git_tree_hash`
and `verification_predicate`; `store_action()`'s call included both. Any
proof using either (which `git_tree_unchanged` always does) was stored
under one key and looked up under a different one — **every** call was a
permanent miss, silently. Fixed: `get_or_execute()` now passes all six
fields, matching `store_action()` exactly
(`src/second_brain/action_cache.py`).

### Bug 2 — `query()` never threaded a `cwd` through to the git-tree check

Even after Bug 1's fix, the second smoke-test run was still a miss.
Root cause: `validate_proof(self, proof, cwd=None)` has always accepted a
`cwd` parameter, but `query()` never passed one through — it always
defaulted to `cwd or self.home`, i.e. **the brain home**, regardless of
what directory the entry's `git_tree_hash` was actually computed against.
For any target outside the brain home (every real use of `action-cache
search`), the re-check ran `git rev-parse HEAD^{tree}` in the *brain home*
(not a git repo in the test/dev setup, or a different repo generally),
got `None`, compared it to the stored real hash, and always failed. Fixed:
`query()` and `get_or_execute()` both gained an optional `cwd` parameter,
threaded through to `validate_proof()`; `_action_cache_search` passes
`cwd=target_dir`. Default `cwd=None` preserves existing behavior for every
other caller (including the R4 adversarial tests, which use
`self.home`-relative proofs and still pass unchanged).

Both bugs are exactly the kind of thing that "the code compiles and the
happy-path type-checks" would never catch — they only surfaced by actually
running the command twice and observing a HIT was still reported as a
MISS.

## 4. Verification

Manual end-to-end reproduction (real `git init`/`commit`, real CLI
subprocess calls, cache entries inspected directly in the SQLite store) is
recorded above as the debugging trail, not offered as release evidence.
Formal verification:

```
.venv\Scripts\python -m ruff check src/second_brain/cli.py src/second_brain/action_cache.py tests/test_cli.py
  → All checks passed
.venv\Scripts\python -m pyright src/second_brain/cli.py src/second_brain/action_cache.py tests/test_cli.py
  → 0 errors, 0 warnings, 0 informations
.venv\Scripts\python -m pytest tests/test_cli.py tests/test_action_cache.py tests/test_action_cache_safety_proof.py -v
  → 29 passed
.venv\Scripts\python -m pytest -q   (full suite)
  → 1 pre-existing failure: tests/test_ledger.py::test_cli_concurrent_init_and_append_burst,
    a Windows filesystem-race concurrency test unrelated to any file
    touched this phase; passes in isolation (18.47s, 1 passed). Not a
    regression from this change.
```

New tests: `tests/test_cli.py`
(`test_action_cache_search_hits_on_second_call_and_misses_after_a_commit` —
proves MISS → HIT → MISS-after-commit end to end via real git repos;
`test_action_cache_search_non_git_dir_never_caches` — proves the non-git
fallback never caches).

## 5. What remains open

This is a Brain-owned, harness-agnostic CLI layer — it works today for any
caller willing to invoke `second_brain action-cache search` instead of
running a search directly. It does **not** mean Prime's own `bash`/search
tool calls are cached — Prime would need to be taught to call this command
(or something equivalent) instead of running `rg`/`grep` directly, which
is a live-pilot-era integration question, not a code change blocked on
anything found in this pass.
