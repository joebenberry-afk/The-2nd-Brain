# Prime v0.7.4 Flaky-Test A/B Run — Patched Candidate (non-live)

## Scope

- Worktree: `C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074`
- Commit: `af0b8e00b9f704e834787fd321065ca78281f2aa` (tag v0.7.4)
- Local patches applied: `packages/coding-agent/src/core/kernel/bootstrap.ts`, `packages/coding-agent/src/core/session-lease.ts`
- Live install `C:\Tools\prime-agent` was not touched, read, or referenced.
- No source or test file in the worktree was modified during this run.

## git status (repo root) — confirmed

```
$ git status --short   (run from C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074)
 M packages/coding-agent/src/core/kernel/bootstrap.ts
 M packages/coding-agent/src/core/session-lease.ts
```

Exactly the 2 expected modified files, nothing else.

## Command run

```
cwd: C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074\packages\coding-agent
"C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074\node_modules\.bin\vitest.cmd" --run
```

Full captured stdout+stderr: `C:\Users\assas\.prime-eperm-repro\logs\ab-074-vitest-full.log` (9185 lines).

Run executed once, to completion, no cancellation, no retries, no fixes applied.

## Result summary (verbatim from vitest)

```
 Test Files  62 failed | 253 passed | 8 skipped (323)
      Tests  330 failed | 3884 passed | 63 skipped (4277)
     Errors  14 errors
   Start at  01:24:54
     Duration  270.24s (transform 138.62s, setup 0ms, import 1590.27s, tests 2635.12s, environment 104ms)
```

**Exit code: 1**

## Failure category breakdown (330 failed tests, by first-line error text)

| Category | Count | Basis |
|---|---|---|
| RLM-depth-env-induced | 59 | error text contains `RLM recursion depth limit reached`, `RLM_MAX_DEPTH`, or an `RLM_DEPTH` value mismatch |
| assertion-mismatch | 194 | `AssertionError` / `expected ... received ...` with no filesystem/timeout/RLM-depth signature in the first lines |
| timeout | 26 | `Test timed out` / `Hook timed out` |
| EPERM | 23 | error text contains `EPERM` |
| EACCES | 14 | error text contains `EACCES` |
| ENOENT | 11 | error text contains `ENOENT` |
| other | 3 | does not match the above (spawn/process errors, one TypeError) |

### Observed environment facts backing the RLM-depth-env-induced category

The shell that launched vitest had `RLM_MAX_DEPTH=1` and `RLM_DEPTH=1` set in its process environment (this worker's own Prime Agent RLM depth-1 gate). 59 test failures reproduce that exact value in their error text, e.g.:

```
Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
AssertionError: expected { RLM_DEPTH: '1', ... } to match object { RLM_DEPTH: '0' }
```

These tests construct nested/child RLM sessions and assert depth-2+ behavior; with the ambient env pinned to depth 1/max 1 by the launching shell, the tests hit the real depth gate instead of the fixture's intended default. This is reported as observed fact from the error text and the launching shell's own env vars, not diagnosed further.

### Observed environment facts backing the EPERM category

Multiple kernel-bootstrap-related failures show:

```
Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe'
```

i.e. the test tried to unlink/replace a file inside the shared `C:\Users\assas\.prime\agent\kernel-venv` path while another process (this same machine's live Prime Agent kernel) held it. Reported as observed fact from the error text only.

### Duplicate-reported failures

13 test names appear twice in the raw FAIL stream (343 raw FAIL lines vs 330 unique failed test names); vitest's own summary line reports 330, so duplicates were collapsed to unique test identity for this report. Duplicated names: test/suite/regressions/4606-update-restart-coordinator.test.ts (x2 tests), test/kernel-bootstrap.test.ts (x3 tests), test/kernel-attach-image-skill.test.ts (x2 tests), test/daemon-supervisor-process.test.ts (x5 tests) — each of these files' failing tests reappeared in the failure stream a second time within the single run.

## Full failure list (330), grouped by file

Format: `test name — [category] — first-line error text (truncated)`

### `test/acp-rlm-subagents.test.ts` (1 failing)

- ACP mode surfaces RLM subagents > streams subagent lifecycle to an ACP client as namespaced metadata — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`

### `test/agent-session-recursion.test.ts` (49 failing)

- AgentSession rlm recursion > lets the orchestrator choose a unique subagent session name — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > falls back to listed family metadata when a controller lacks name validation — **[RLM-depth-env-induced]** — `AssertionError: expected [Function] to throw error including 'Agent name "passive-worker" is unavai…' but got 'RLM recursion depth limit reached (RL…' ; Expected: "Agent name "pass`
- AgentSession rlm recursion > reserves a running child's current name after it is renamed — **[timeout]** — `Error: Timed out waiting for condition`
- AgentSession rlm recursion > retries and releases failed retained child cleanup on the next compaction — **[RLM-depth-env-induced]** — `AssertionError: promise rejected "Error: RLM recursion depth limit reached …" instead of resolving`
- AgentSession rlm recursion > makes an orchestrator-chosen name override a custom runtime's preexisting name — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > runs a child session under a sub directory and returns an RLM-shaped result — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > resolves a spawned child handle to its published session before a roled send — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > delivers an id-addressed send while a completed child's terminal injection is pending — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > propagates pending child startup failure to an immediate roled send — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > falls through a retained failed child name to a healthy roster child — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > falls through a delete-before-startup tombstone during a roled send — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > surfaces post-admission startup failure in the parent transcript and subagent registry — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > injects exactly one cancellation notice when a child run is cancelled — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > injects exactly one notice with a preview when a child completes without replying — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > does not inject a terminal notice when a parent follow-up resets reply state after a reply — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > keeps detached deletion silent when child startup later settles — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > fully deletes a settled startup failure and frees its session name — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > releases a hosted child when its initial task fails — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > notifies the runtime host when the initial child task completes — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > projects retained child follow-up turns into parent child-update activity — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > lists a completed child with its parent-scoped messaging identity until disposal — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > disposes an inline child when setting its session name fails — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > emits updated child session names after a retained child is renamed — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > surfaces a child's recap on its snapshot once the summarizer sets it — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > runs a child agent without requiring ripgrep — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > adds child usage to the parent session aggregate — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > attributes every tool-loop turn in the admitted task to spawn usage — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > gets and persists per-chat max-depth changes without transcript messages — **[assertion-mismatch]** — `AssertionError: expected { maxDepth: 1, source: 'env' } to deeply equal { maxDepth: 1, source: 'default' } ; - Expected ; + Received ;   {`
- AgentSession rlm recursion > uses a max-depth prompt update on the next turn of the active run — **[assertion-mismatch]** — `AssertionError: expected 'You are a general purpose agent that …' to contain 'A callable 'rlm'' ; - Expected ; + Received ; - A callable 'rlm'`
- AgentSession rlm recursion > copies live max depth at spawn, keeps child overrides independent, and lets zero disable root spawning — **[RLM-depth-env-induced]** — `AssertionError: expected [Function] to throw error including 'RLM recursion depth limit reached (RL…' but got 'RLM recursion depth limit reached (RL…' ; Expected: "RLM recursion de`
- AgentSession rlm recursion > lets a stale kernel depth cap defer to the live host gate — **[assertion-mismatch]** — `AssertionError: the given combination of arguments (undefined and string) is invalid for this assertion. You can use an array, a map, an object, a set, a string, or a weakset inste`
- AgentSession rlm recursion > cancels active rlm children when the parent session is disposed — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > cancels active rlm children when the parent session is aborted — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > does not admit a child prompt when the parent is aborted while resolving the sender — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > does not cancel active rlm children when only the parent turn is interrupted — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > cancels a single rlm child run by id and reports unknown ids — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > deletes only inactive RLM children through the explicit inactive path — **[timeout]** — `Error: Timed out waiting for condition`
- AgentSession rlm recursion > releases a hosted child when completion persistence fails — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > does not let completion retention resurrect a child being deleted — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > reconciles failed-delete tracking when the detached retry succeeds — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > reserves an errored startup name while its detached failure injection settles — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > reserves a deleted queued child's name until startup settles — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > deletes a queued child without waiting for blocked startup — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > keeps late startup cleanup retryable when release and fallback delete fail — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > deletes a running direct child by name and waits for runtime cleanup — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSession rlm recursion > deletes an inactive nested RLM child through the root session — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=2, RLM_MAX_DEPTH=2)`
- AgentSession rlm recursion > cancels nested rlm child runs through the root session — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=2, RLM_MAX_DEPTH=2)`
- AgentSession rlm recursion > handles rlm calls from asyncio tasks after the scheduling cell is idle — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- AgentSession RLM session dir > does not create a /tmp dir or set RLM_SESSION_DIR for a non-persisted session — **[RLM-depth-env-induced]** — `AssertionError: expected { RLM_DEPTH: '1', …(2) } to match object { RLM_DEPTH: '0' } ; (2 matching properties omitted from actual) ; - Expected ; + Received`

### `test/agents-view-inactive-reply.test.ts` (5 failing)

- agents view reply on inactive sessions > resumes a saved session before delivering the reply — **[assertion-mismatch]** — `AssertionError: expected [ 'file:/tmp/sessions/saved-1.jsonl' ] to not include 'file:/tmp/sessions/saved-1.jsonl'`
- agents view reply on inactive sessions > does not select a resumed session after its reply target is cancelled — **[assertion-mismatch]** — `AssertionError: expected [ 'file:/tmp/sessions/saved-1.jsonl' ] to not include 'file:/tmp/sessions/saved-1.jsonl'`
- agents view reply on inactive sessions > handles 'send failure' — **[assertion-mismatch]** — `AssertionError: expected true to be false // Object.is equality ; - Expected ; + Received ; - false`
- agents view reply on inactive sessions > handles 'replacement text entered during send …' — **[assertion-mismatch]** — `AssertionError: expected true to be false // Object.is equality ; - Expected ; + Received ; - false`
- agents view slash commands > re-resolves the armed target before dispatching a view command — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ { name: 'kill', args: '' }, …(1) ] ; Received: ;   1st vi.fn() call: ;   [`

### `test/agents-view-mode.test.ts` (1 failing)

- AgentsViewMode > keeps subagent expansion across the active-to-persisted identity flip — **[assertion-mismatch]** — `AssertionError: expected 'file:C:\tmp\root.jsonl' to be 'file:/tmp/root.jsonl' // Object.is equality ; Expected: "file:/tmp/root.jsonl" ; Received: "file:C:\tmp\root.jsonl"`

### `test/agents-view-state.test.ts` (2 failing)

- agents view state > reconciles canonical paths and session ids while retaining saved search text — **[assertion-mismatch]** — `AssertionError: expected { …(6) } to match object { …(4) } ; (2 matching properties omitted from actual) ; - Expected ; + Received`
- agents view state > preserves live identity and row state when saved metadata adds a file alias — **[assertion-mismatch]** — `AssertionError: expected { saved: { …(13) }, …(4) } to match object { …(2) } ; (16 matching properties omitted from actual) ; - Expected ; + Received`

### `test/auth-flows.test.ts` (1 failing)

- ProviderAuthFlows > stores a reused Prime CLI key when Prime CLI config sync is disabled — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`

### `test/auth-storage.test.ts` (1 failing)

- AuthStorage > API key resolution > setPrimeInferenceApiKey creates Prime CLI config — **[assertion-mismatch]** — `AssertionError: expected 438 to be 384 // Object.is equality ; - Expected ; + Received ; - 384`

### `test/command-recovery-journal.test.ts` (1 failing)

- CommandRecoveryJournal > durably removes acknowledged results — **[EPERM]** — `Error: EPERM: operation not permitted, fsync`

### `test/config.test.ts` (5 failing)

- detectInstallMethod > self-update respects configured npmCommand — **[assertion-mismatch]** — `AssertionError: expected undefined to deeply equal { Object (command, args, ...) } ; - Expected: ; { ;   "args": [`
- detectInstallMethod > self-updates bun global installs from bun pm bin — **[assertion-mismatch]** — `AssertionError: expected undefined to deeply equal { command: 'bun', …(2) } ; - Expected: ; { ;   "args": [`
- detectInstallMethod > self-updates renamed bun global installs by removing the old package first — **[assertion-mismatch]** — `AssertionError: expected undefined to deeply equal { command: 'bun', …(3) } ; - Expected: ; { ;   "args": [`
- detectInstallMethod > does not self-update when npm install path is not writable — **[assertion-mismatch]** — `AssertionError: expected { Object (command, args, ...) } to be undefined ; - Expected: ; undefined ; + Received:`
- session paths > expands tilde in the session root env var — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas/prime-agent-sessions' to be 'C:\Users\assas\prime-agent-sessions' // Object.is equality ; Expected: "C:\Users\assas\prime-agent-sessions" ;`

### `test/daemon-launch.test.ts` (8 failing)

- probeRunningDaemonSessions > returns only sessions that have an activeSessionId — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- probeRunningDaemonSessions > returns an empty list when the daemon is reachable but idle — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- probeRunningDaemonSessions > leaves activeSessions undefined when reachable but the list fails — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- ensureInteractiveDaemonRunning > rejects a busy pre-session-action daemon before attach — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- ensureInteractiveDaemonRunning > does not replace a stale daemon with busy private client sessions — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- ensureInteractiveDaemonRunning > does not treat a live daemon as absent when cold startup delays the first connection — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- ensureInteractiveDaemonRunning > succeeds when the spawned child loses the race to an already-serving daemon — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- shutdownDaemonAndWait > stops a running daemon and returns true — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`

### `test/daemon-mode.test.ts` (8 failing)

- daemon mode helpers > discovers a non-resident child left running in the persisted registry — **[assertion-mismatch]** — `AssertionError: expected { …(2) } to match object { entries: [ ObjectContaining{…} ] } ; (4 matching properties omitted from actual) ; - Expected ; + Received`
- daemon mode helpers > does not retry supervisor agent-message rejections — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- daemon mode helpers > routes worker-local session renames through the supervisor — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\pa-worker-rename-rUNfSr\s`
- daemon mode helpers > does not retry permanent ambiguity errors from the supervisor — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\pa-ambiguous-p8t4YF\s`
- daemon mode helpers > reports failed passive children as errors without creating child runtimes — **[assertion-mismatch]** — `AssertionError: expected { …(2) } to match object { Object (current, entries) } ; - Expected ; + Received ;   {`
- daemon mode helpers > validates a requested passive child name before hydration — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ { name: 'sibling', depth: 1, …(3) } ] ; Received: ;   1st vi.fn() call: ;   [`
- daemon mode helpers > rehydrates a legacy passive subagent at depth one — **[assertion-mismatch]** — `AssertionError: expected 2 to be 1 // Object.is equality ; - Expected ; + Received ; - 1`
- daemon mode helpers > does not fail a deletion when the artifact dir cannot be removed — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`

### `test/daemon-supervisor-monitor.test.ts` (1 failing)

- daemon worker supervisor monitoring > limits abort admission to mutation drain — **[EACCES]** — `Error: listen EACCES: permission denied \tmp\prime-update-drain-43892-nCKpuB\supervisor.sock`

### `test/daemon-supervisor-ownership.test.ts` (1 failing)

- daemon supervisor ownership registry > disambiguates never-acquired from lost-on-disk ownership errors — **[assertion-mismatch]** — `AssertionError: expected 'Daemon supervisor generation registry…' to contain 'C:\Users\assas\AppData\Local\Temp\own…' ; Expected: "C:\Users\assas\AppData\Local\Temp\ownership-regis`

### `test/daemon-supervisor-process.test.ts` (9 failing)

- daemon supervisor resident workers > creates top-level sessions at depth zero when the supervisor inherits a child depth — **[ENOENT]** — `Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-depth-37144-d3ba3850.`
- daemon supervisor resident workers > lists, creates, and attaches passive children through their owning worker — **[ENOENT]** — `Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-passive-37144-cad2241`
- daemon supervisor resident workers > keeps client-owned workers hidden and removes them without archiving — **[ENOENT]** — `Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-owned-37144-08499521.`
- daemon supervisor resident workers > releases an adopted client-owned worker when disposal races supervisor replacement — **[other]** — `Error: Supervisor exited before becoming ready (code 1, signal null) ; stdout: ; stderr: ; (node:48024) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being se`
- daemon supervisor resident workers > delivers agent-origin messages between root siblings on separate workers — **[other]** — `Error: Supervisor exited before becoming ready (code 1, signal null) ; stdout: ; stderr: ; (node:58240) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being se`
- daemon supervisor resident workers > restarts an empty supervisor without requiring a resident worker — **[ENOENT]** — `Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-restart-37144-170f970`
- daemon supervisor resident workers > archives resident roots and cancels their heartbeats on explicit daemon shutdown — **[ENOENT]** — `Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-shutdown-37144-30d3bd`
- daemon supervisor resident workers > hosts and adopts isolated worker processes — **[ENOENT]** — `Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-smoke-37144-a298521a.`
- daemon supervisor resident workers > isolates a root, streams a chunked snapshot, and adopts the same worker after restart — **[ENOENT]** — `Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-37144-5744fd62.sock.`

### `test/daemon-supervisor-side-question.test.ts` (1 failing)

- daemon supervisor side-question routing > rejects a protocol-6 client through the supervisor socket before state exchange — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\prime-supervisor-old-client-pjB2Yd\supervisor.sock`

### `test/extensions-discovery.test.ts` (23 failing)

- extensions discovery > discovers direct .ts files in extensions/ — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) }, { …(2) } ] to have a length of +0 but got 2 ; - Expected ; + Received ; - 0`
- extensions discovery > discovers direct .js files in extensions/ — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > discovers subdirectory with index.ts — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > discovers subdirectory with index.js — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > prefers index.ts over index.js — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > discovers subdirectory with package.json pi field — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > package.json can declare multiple extensions — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) }, { …(2) } ] to have a length of +0 but got 2 ; - Expected ; + Received ; - 0`
- extensions discovery > package.json with pi field takes precedence over index.ts — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > ignores package.json without pi field, falls back to index.ts — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > handles mixed direct files and subdirectories — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) }, { …(2) }, { …(2) } ] to have a length of +0 but got 3 ; - Expected ; + Received ; - 0`
- extensions discovery > skips non-existent paths declared in package.json — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > loads extensions and registers commands — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > loads extensions and registers tools — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > handles explicitly configured paths — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > resolves dependencies from extension's own node_modules — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > registers message renderers — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > reports error when extension throws during initialization — **[assertion-mismatch]** — `AssertionError: expected 'Failed to load extension: Cannot find…' to contain 'Initialization failed!' ; Expected: "Initialization failed!" ; Received: "Failed to load extension: Ca`
- extensions discovery > reports error when extension has no default export — **[assertion-mismatch]** — `AssertionError: expected 'Failed to load extension: Cannot find…' to contain 'does not export a valid factory funct…' ; Expected: "does not export a valid factory function" ; Recei`
- extensions discovery > allows multiple extensions to register different tools — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) }, { …(2) } ] to have a length of +0 but got 2 ; - Expected ; + Received ; - 0`
- extensions discovery > loads extension with event handlers — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > loads extension with shortcuts — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > loads extension with flags — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`
- extensions discovery > loadExtensions only loads explicit paths without discovery — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1 ; - Expected ; + Received ; - 0`

### `test/extensions-input-event.test.ts` (7 failing)

- Input Event > transforms text and preserves images when omitted — **[assertion-mismatch]** — `AssertionError: expected { action: 'continue' } to deeply equal { action: 'transform', …(2) } ; - Expected ; + Received ;   {`
- Input Event > transforms and replaces images when provided — **[assertion-mismatch]** — `AssertionError: expected { action: 'continue' } to deeply equal { Object (action, text, ...) } ; - Expected ; + Received ;   {`
- Input Event > chains transforms across multiple handlers — **[assertion-mismatch]** — `AssertionError: expected { action: 'continue' } to deeply equal { action: 'transform', …(2) } ; - Expected ; + Received ;   {`
- Input Event > short-circuits on handled and skips subsequent handlers — **[assertion-mismatch]** — `AssertionError: expected { action: 'continue' } to deeply equal { action: 'handled' } ; - Expected ; + Received ;   {`
- Input Event > passes source correctly for all source types — **[assertion-mismatch]** — `AssertionError: expected undefined to be 'interactive' // Object.is equality ; - Expected: ; "interactive" ; + Received:`
- Input Event > catches handler errors and continues — **[assertion-mismatch]** — `AssertionError: expected [] to include 'boom'`
- Input Event > hasHandlers returns correct value — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`

### `test/extensions-runner.test.ts` (21 failing)

- ExtensionRunner > shortcut conflicts > warns when extension shortcut conflicts with built-in — **[assertion-mismatch]** — `AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ] ; Number of calls: 0`
- ExtensionRunner > shortcut conflicts > allows a shortcut when the reserved set no longer contains the default key — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- ExtensionRunner > shortcut conflicts > warns but allows when extension uses non-reserved built-in shortcut — **[assertion-mismatch]** — `AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ] ; Number of calls: 0`
- ExtensionRunner > shortcut conflicts > blocks shortcuts for reserved actions even when rebound — **[assertion-mismatch]** — `AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ] ; Number of calls: 0`
- ExtensionRunner > shortcut conflicts > blocks shortcuts when reserved key is also bound to non-reserved actions — **[assertion-mismatch]** — `AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ] ; Number of calls: 0`
- ExtensionRunner > shortcut conflicts > blocks shortcuts when reserved action has multiple keys — **[assertion-mismatch]** — `AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ] ; Number of calls: 0`
- ExtensionRunner > shortcut conflicts > warns but allows when non-reserved action has multiple keys — **[assertion-mismatch]** — `AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ] ; Number of calls: 0`
- ExtensionRunner > shortcut conflicts > warns when two extensions register same shortcut — **[assertion-mismatch]** — `AssertionError: expected "warn" to be called with arguments: [ Array(1) ] ; Number of calls: 0`
- ExtensionRunner > tool collection > collects tools from multiple extensions — **[assertion-mismatch]** — `AssertionError: expected +0 to be 2 // Object.is equality ; - Expected ; + Received ; - 2`
- ExtensionRunner > tool collection > keeps first tool when two extensions register the same name — **[assertion-mismatch]** — `AssertionError: expected [] to have a length of 1 but got +0 ; - Expected ; + Received ; - 1`
- ExtensionRunner > command collection > collects commands from multiple extensions — **[assertion-mismatch]** — `AssertionError: expected +0 to be 2 // Object.is equality ; - Expected ; + Received ; - 2`
- ExtensionRunner > command collection > gets command by invocation name — **[assertion-mismatch]** — `AssertionError: expected undefined to be defined`
- ExtensionRunner > command collection > suffixes duplicate extension commands in insertion order — **[assertion-mismatch]** — `AssertionError: expected [] to have a length of 2 but got +0 ; - Expected ; + Received ; - 2`
- ExtensionRunner > error handling > calls error listeners when handler throws — **[assertion-mismatch]** — `AssertionError: expected +0 to be 1 // Object.is equality ; - Expected ; + Received ; - 1`
- ExtensionRunner > message renderers > gets message renderer by type — **[assertion-mismatch]** — `AssertionError: expected undefined to be defined`
- ExtensionRunner > flags > collects flags from extensions — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- ExtensionRunner > flags > keeps first flag when two extensions register the same name — **[assertion-mismatch]** — `AssertionError: expected undefined to be 'first' // Object.is equality ; - Expected: ; "first" ; + Received:`
- ExtensionRunner > before_agent_start > keeps ctx.getSystemPrompt() in sync with chained system prompt updates — **[assertion-mismatch]** — `AssertionError: expected [ { …(2) }, { …(2) } ] to deeply equal [] ; - Expected ; + Received ; - []`
- ExtensionRunner > tool_result chaining > chains content modifications across handlers — **[assertion-mismatch]** — `AssertionError: expected undefined to be defined`
- ExtensionRunner > tool_result chaining > preserves previous modifications when later handlers return partial patches — **[assertion-mismatch]** — `AssertionError: expected undefined to deeply equal { content: [ { …(2) } ], …(2) } ; - Expected: ; { ;   "content": [`
- ExtensionRunner > hasHandlers > returns true when handlers exist for event type — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`

### `test/herdr-agent-state.test.ts` (9 failing)

- herdrAgentStateExtension > ignores events from sessions other than the one it bound to — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-ybi2ky\h.sock`
- herdrAgentStateExtension > reports lifecycle state to the herdr socket — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-6ekam2\h.sock`
- herdrAgentStateExtension > unsubscribes the shared-bus herdr:blocked listener on shutdown — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-j0vdeo\h.sock`
- herdrAgentStateExtension > reports working when the session starts mid-turn (reload) — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-t07tuz\h.sock`
- herdrAgentStateExtension > settles the retry hold when a blocked event interrupts it — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-xog344\h.sock`
- herdrAgentStateExtension > holds working through any error end until the retry grace settles — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-0n4j85\h.sock`
- herdrAgentStateExtension > sends no reports after quit release — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-wuuqn0\h.sock`
- herdrAgentStateExtension > silences a replaced instance without releasing the pane — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-g6dl09\h.sock`
- herdrAgentStateExtension > keeps seq monotonically increasing across extension instances — **[EACCES]** — `Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-ge091m\h.sock`

### `test/interactive-mode-suspend.test.ts` (2 failing)

- InteractiveMode.handleCtrlZ > keeps the process alive while suspended and restores the TUI on SIGCONT — **[other]** — `TypeError: this.showStatus is not a function`
- InteractiveMode.handleCtrlZ > cleans up the temporary handlers if suspension fails — **[assertion-mismatch]** — `AssertionError: expected a thrown error to be Error: suspend failed ; - Expected ; + Received ; - Error {`

### `test/ipython-provisioner.test.ts` (4 failing)

- IpythonKernelProvisioner > memoizes concurrent ensure() calls into one startup — **[assertion-mismatch]** — `AssertionError: expected +0 to be 1 // Object.is equality ; - Expected ; + Received ; - 1`
- IpythonKernelProvisioner > retries after a failed startup instead of caching the rejection — **[assertion-mismatch]** — `AssertionError: expected +0 to be 2 // Object.is equality ; - Expected ; + Received ; - 2`
- IpythonKernelProvisioner > prewarm() swallows the failure and the next ensure() starts fresh — **[assertion-mismatch]** — `AssertionError: expected 0 to be greater than or equal to 2`
- IpythonKernelProvisioner > waits for readyGate before starting the kernel — **[assertion-mismatch]** — `AssertionError: expected +0 to be 1 // Object.is equality ; - Expected ; + Received ; - 1`

### `test/kernel-agent-message-skill.test.ts` (6 failing)

- agent-message skill over the kernel host bridge > lists agents and sends without exposing a spoofable sender — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- agent-message skill over the kernel host bridge > emits successful broadcast receipts and leaves short errors in the result — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- agent-message skill over the kernel host bridge > rejects broadcast combined with role selectors before reaching the host — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- agent-message skill over the kernel host bridge > rejects a positional name target before reaching the host — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- agent-message skill over the kernel host bridge > does not expose a queueable delivery mode — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- agent-message skill over the kernel host bridge > captures sent messages from detached tasks after the cell is idle — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`

### `test/kernel-agent-observe-skill.test.ts` (2 failing)

- agent-observe skill over the kernel host bridge > lists agents and reads bounded recent messages — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- agent-observe skill over the kernel host bridge > validates argument types before sending to the host — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`

### `test/kernel-attach-image-skill.test.ts` (9 failing)

- attach-image skill over the kernel host bridge > loads an on-disk image into the tool result as an ImageContent block — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- attach-image skill over the kernel host bridge > compresses large attached images before storing them in the tool result — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- attach-image skill over the kernel host bridge > reports when compressed animated images are flattened to their first frame — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- attach-image skill over the kernel host bridge > uses a neutral background when compressing transparent images — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- attach-image skill over the kernel host bridge > rejects oversized pixel counts before loading an image into context — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- attach-image skill over the kernel host bridge > rejects undecodable images before emitting any attachment — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- attach-image skill over the kernel host bridge > errors without emitting an attachment when the model is not vision-capable — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- attach-image skill over the kernel host bridge > rejects a non-image file — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- attach-image skill over the kernel host bridge > fails the cell loudly when an emitted attachment exceeds the size cap — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`

### `test/kernel-rlm-heartbeat-skill.test.ts` (3 failing)

- RLM heartbeat skill over the kernel host bridge > rejects non-string delivery modes before calling the host — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`
- RLM heartbeat skill over the kernel host bridge > round-trips create, list, update, and delete through a live kernel — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- RLM heartbeat skill over the kernel host bridge > surfaces missing host handlers as Python exceptions — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`

### `test/suite/regressions/4428-remove-legacy-pi-mono-tools.test.ts` (1 failing)

- regression #4428: remove legacy pi-mono built-in tools > applies shell settings to ipython bash cells — **[EPERM]** — `Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe' ; First-time setup needs inte`

### `test/kernel-bootstrap.test.ts` (17 failing)

- kernel bootstrap > bootstraps a missing venv with uv, ipykernel, prime-agent-runtime, and default extra packages — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- kernel bootstrap > installs Python skills into the bootstrapped venv — **[timeout]** — `Error: Hook timed out in 10000ms. ; If this is a long-running hook, pass a timeout value as the last argument or configure it globally with "hookTimeout".`
- kernel bootstrap > routes bootstrap progress through the provided callback — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`
- kernel bootstrap > installs sibling Python skill dependencies with dependent editable packages — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > installs sibling Python skill dependencies when package and directory names differ — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > parses Python skill dependencies with extras — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > syncs a warm venv when a Python skill pyproject changes — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > continues when a Python skill editable install fails and retries it next startup — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > rebuilds a warm venv with legacy unhashed Python skill manifest entries — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > shares concurrent bootstrap work in one process — **[assertion-mismatch]** — `AssertionError: expected [ …(2) ] to deeply equal [ …(2) ] ; - Expected ; + Received ;   [`
- kernel bootstrap > reuses a current warm venv without invoking uv — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > rebuilds a warm venv whose recorded runtime hash no longer matches local source — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > rebuilds a warm venv with a stale rlm runtime — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > rebuilds a broken venv — **[assertion-mismatch]** — `AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality ; Expected: "C:\Users\assas\AppData\Local\Tem`
- kernel bootstrap > uses PRIME_AGENT_KERNEL_PYTHON as an override contract — **[assertion-mismatch]** — `AssertionError: promise rejected "Error: PRIME_AGENT_KERNEL_PYTHON points t…" instead of resolving`
- kernel bootstrap > allows PRIME_AGENT_KERNEL_PYTHON missing Python skill imports — **[assertion-mismatch]** — `AssertionError: promise rejected "Error: PRIME_AGENT_KERNEL_PYTHON points t…" instead of resolving`
- kernel bootstrap > rejects PRIME_AGENT_KERNEL_PYTHON missing default extra packages — **[assertion-mismatch]** — `AssertionError: expected [Function] to throw error matching /default Python packages \(yaml \(PyYA…/ but got 'PRIME_AGENT_KERNEL_PYTHON points to a…' ; - Expected: ; /default Pytho`

### `test/kernel-startup.test.ts` (1 failing)

- KernelManager startup > surfaces kernels that exit before resolving ports — **[assertion-mismatch]** — `AssertionError: expected [Function] to throw error matching /Kernel exited before resolving ports[…/ but got 'Kernel exited before resolving ports.…' ; - Expected: ; /Kernel exited`

### `test/owned-session-worker-process.test.ts` (1 failing)

- owned session worker processes > terminates the owned worker when its frontend is killed — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`

### `test/package-command-paths.test.ts` (4 failing)

- package commands > uses the current package name when the update check omits packageName — **[assertion-mismatch]** — `AssertionError: expected 1 to be undefined ; - Expected: ; undefined ; + Received:`
- package commands > installs the active package name from the update check during self-update — **[assertion-mismatch]** — `AssertionError: expected 1 to be undefined ; - Expected: ; undefined ; + Received:`
- package commands > installs the Prime Agent tarball from the update manifest during self-update — **[assertion-mismatch]** — `AssertionError: expected 1 to be undefined ; - Expected: ; undefined ; + Received:`
- package commands > fails self-update when renamed npm package installation fails — **[assertion-mismatch]** — `AssertionError: expected '\u001b[31mPrime Agent has 3 busy sess…' to contain 'exited with code 23' ; Expected: "exited with code 23" ; Received: "[31mPrime Agent has 3 busy sessio`

### `test/package-manager.test.ts` (2 failing)

- DefaultPackageManager > resolve > should resolve symlinked user and project resources once — **[assertion-mismatch]** — `AssertionError: expected { extensions: 1, skills: 36, …(2) } to deeply equal { extensions: 1, skills: 1, …(2) } ; - Expected ; + Received ;   {`
- DefaultPackageManager > source parsing > should emit progress events on install attempt — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`

### `test/package-self-update-daemon.test.ts` (2 failing)

- self-update daemon restart > defers the exact custom-socket restart to the interactive parent — **[assertion-mismatch]** — `AssertionError: expected [ Array(1) ] to deeply equal [ Array(1) ] ; - Expected ; + Received ;   [`
- self-update daemon restart > restarts the daemon only after the package update succeeds — **[assertion-mismatch]** — `AssertionError: expected -1 to be greater than 1`

### `test/refinement.test.ts` (1 failing)

- harness refinement > atomically replaces harness state without leaving temporary files — **[assertion-mismatch]** — `AssertionError: expected [ 'harness_state.json' ] to deeply equal [ Array(1) ] ; - Expected ; + Received ;   [`

### `test/resource-loader.test.ts` (4 failing)

- DefaultResourceLoader > reload > should load symlinked user and project extensions once — **[assertion-mismatch]** — `AssertionError: expected [] to have a length of 1 but got +0 ; - Expected ; + Received ; - 1`
- DefaultResourceLoader > reload > should keep both extensions loaded when command names collide — **[assertion-mismatch]** — `AssertionError: expected [] to have a length of 2 but got +0 ; - Expected ; + Received ; - 2`
- DefaultResourceLoader > extension conflict detection > should detect tool conflicts between extensions — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- DefaultResourceLoader > extension conflict detection > should prefer explicit CLI extensions over discovered extensions when commands and tools conflict — **[assertion-mismatch]** — `AssertionError: expected undefined to be 'C:\Users\assas\AppData\Local\Temp\rl-…' // Object.is equality ; - Expected: ; "C:\\Users\\assas\\AppData\\Local\\Temp\\rl-test-17872899236`

### `test/rlm-ledger.test.ts` (2 failing)

- rlm spawn ledger > replays spawn, rename, and delete records last-writer-wins — **[assertion-mismatch]** — `AssertionError: expected 438 to be 384 // Object.is equality ; - Expected ; + Received ; - 384`
- rlm spawn ledger > fails closed on byte and record bounds — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`

### `test/sdk-session-manager.test.ts` (2 failing)

- createAgentSession session manager defaults > uses agentDir for the default persisted session path — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- createAgentSession session manager defaults > derives cwd from an explicit sessionManager when cwd is omitted — **[assertion-mismatch]** — `AssertionError: expected 'You are a general purpose agent that …' to contain 'Working directory: C:\Users\assas\App…' ; - Expected ; + Received ; - Working directory: C:\Users\assa`

### `test/session-manager-flush.test.ts` (1 failing)

- SessionManager.flushNow > rewrites a cross-directory symlink target without replacing the alias — **[assertion-mismatch]** — `AssertionError: expected 438 to be 416 // Object.is equality ; - Expected ; + Received ; - 416`

### `test/telemetry.test.ts` (1 failing)

- telemetry identity and transport > creates a private stable installation ID — **[assertion-mismatch]** — `AssertionError: expected 438 to be 384 // Object.is equality ; - Expected ; + Received ; - 384`

### `test/tools-manager.test.ts` (2 failing)

- tools manager > accepts managed and PATH tools only when their version check succeeds — **[assertion-mismatch]** — `AssertionError: expected null to be '\tmp\prime-agent-tools-manager-51928\…' // Object.is equality ; - Expected: ; "\\tmp\\prime-agent-tools-manager-51928\\rg" ; + Received:`
- tools manager > validates a downloaded binary before reporting it available — **[assertion-mismatch]** — `AssertionError: expected { status: 'unavailable', …(4) } to deeply equal { status: 'available', …(1) } ; - Expected ; + Received ;   {`

### `test/tools.test.ts` (3 failing)

- Coding Agent Tools > edit tool > should include EACCES for read-only files — **[EACCES]** — `AssertionError: expected [Function] to throw error including 'Could not edit file: C:\Users\assas\A…' but got 'Could not edit file: C:\Users\assas\A…' ; Expected: "Could not edit f`
- Coding Agent Tools > edit tool > should include EACCES in diff preview for unreadable files — **[assertion-mismatch]** — `AssertionError: expected { diff: '-1 hello\n+1 world', …(1) } to deeply equal { Object (error) } ; - Expected ; + Received ;   {`
- Coding Agent Tools > bash tool > executeBash should persist full output when truncation happens by line count only — **[assertion-mismatch]** — `AssertionError: expected '' to contain '1\n2\n3' ; - Expected ; + Received ; - 1`

### `test/suite/acp-features.test.ts` (1 failing)

- ACP mode preserves prime-agent features > surfaces real goal state transitions to the ACP client — **[timeout]** — `Error: timed out waiting for the expected ACP updates`

### `test/suite/agent-session-autonomous.test.ts` (8 failing)

- AgentSession autonomous mode > runs autonomous gates before applying usage limits — **[assertion-mismatch]** — `AssertionError: expected { shouldContinue: false, …(1) } to match object { shouldContinue: false, …(1) } ; - Expected ; + Received ;   {`
- AgentSession autonomous mode > lets passing autonomous gates complete the run under verifier control — **[assertion-mismatch]** — `AssertionError: expected [ 'make the change', …(1) ] to deeply equal [ 'make the change' ] ; - Expected ; + Received ;   [`
- AgentSession autonomous mode > advances retry budget without rerunning a failed autonomous gate until the workspace changes — **[ENOENT]** — `Error: ENOENT: no such file or directory, open 'C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074\packages\coding-agent\.tmp-autonomous-gate-1787289948116-hfn8eanyu4i\v`
- AgentSession autonomous mode > reruns a failed autonomous gate when untracked file contents change — **[assertion-mismatch]** — `AssertionError: expected { role: 'user', …(2) } to be undefined ; - Expected: ; undefined ; + Received:`
- AgentSession autonomous mode > bounds captured autonomous gate output — **[assertion-mismatch]** — `AssertionError: expected '\'C:\Program\' is not recognized as a…' to contain '... [truncated]' ; - Expected ; + Received ; - ... [truncated]`
- AgentSession autonomous mode > terminates the autonomous gate process tree when the timeout expires — **[ENOENT]** — `Error: ENOENT: no such file or directory, open 'C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074\packages\coding-agent\.tmp-autonomous-process-tree-1787289989434-rsrn6`
- AgentSession autonomous mode > terminates an autonomous gate without mutating retry state when the session is aborted — **[timeout]** — `Error: Timed out waiting for process ID file: C:\Users\assas\AppData\Local\Temp\pi-suite-1787289999102-0dpqv282cjbt\gate.pid`
- AgentSession autonomous mode > records the post-failure worktree snapshot for gate rerun suppression — **[ENOENT]** — `Error: ENOENT: no such file or directory, open 'C:\Users\assas\.prime\agent\prime-upgrade-worktrees\prime-074\packages\coding-agent\.tmp-autonomous-post-snapshot-1787290016468-1sh4`

### `test/suite/agent-session-compaction.test.ts` (1 failing)

- AgentSession compaction characterization > waits for threshold-compaction autonomous continuations before finishing prompt — **[assertion-mismatch]** — `AssertionError: expected +0 to be 1 // Object.is equality ; - Expected ; + Received ; - 1`

### `test/suite/agent-session-goal.test.ts` (4 failing)

- initial goal seeding from config > seeds an active goal from initialGoal config on a fresh top-level session — **[assertion-mismatch]** — `AssertionError: expected { active: false, status: 'idle', …(3) } to match object { Object (active, status, ...) } ; (3 matching properties omitted from actual) ; - Expected ; + Rec`
- initial goal seeding from config > does not reseed after goal is cleared (idempotent restart) — **[assertion-mismatch]** — `AssertionError: expected 'idle' to be 'active' // Object.is equality ; Expected: "active" ; Received: "idle"`
- initial goal seeding from config > does not reseed after goal is completed (idempotent restart) — **[assertion-mismatch]** — `AssertionError: expected 'idle' to be 'active' // Object.is equality ; Expected: "active" ; Received: "idle"`
- initial goal seeding from config > does not reseed when branch has messages (idempotent restart after use) — **[assertion-mismatch]** — `AssertionError: expected 'idle' to be 'active' // Object.is equality ; Expected: "active" ; Received: "idle"`

### `test/suite/agent-session-queue.test.ts` (18 failing)

- AgentSession queue characterization > auto-refine 'review runs after the configured turn…' — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ …(2) ] ; Number of calls: 0`
- AgentSession queue characterization > auto-refine 'falls back to turn-interval review wh…' — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ …(2) ] ; Number of calls: 0`
- AgentSession queue characterization > auto-refine 'queued follow-up messages do not make…' — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ …(2) ] ; Number of calls: 0`
- AgentSession queue characterization > auto-refine 'compact hook does not require the tur…' — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ { reason: 'compact', …(1) }, …(1) ] ; Number of calls: 0`
- AgentSession queue characterization > auto-refine 'declined compact review preserves an …' — **[assertion-mismatch]** — `AssertionError: expected "_scheduleAutoRefine" to be called with arguments: [ 'turn_interval' ] ; Number of calls: 0`
- AgentSession queue characterization > auto-refine compact hook 'waits for planned post-compaction con…' — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- AgentSession queue characterization > auto-refine compact hook 'waits until the scheduled post-compac…' — **[assertion-mismatch]** — `AssertionError: expected "_scheduleAutoRefine" to be called with arguments: [ 'compact' ] ; Number of calls: 0`
- AgentSession queue characterization > auto-refine compact hook 'runs immediately when no post-compact…' — **[assertion-mismatch]** — `AssertionError: expected "_scheduleAutoRefine" to be called with arguments: [ 'compact' ] ; Number of calls: 0`
- AgentSession queue characterization > runs a turn-interval review after a concurrent compact review declines — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- AgentSession queue characterization > auto-refine pending review uses the in-progress guard and catches refine failures — **[assertion-mismatch]** — `AssertionError: expected "refine" to be called with arguments: [ ObjectContaining{…} ] ; Number of calls: 0`
- AgentSession queue characterization > keeps the turn counter and stamps the cooldown when an approved immediate refine fails — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ …(2) ] ; Number of calls: 0`
- AgentSession queue characterization > does not refine when a review resolves after the session is disposed — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times`
- AgentSession queue characterization > stamps the cooldown when the auto-refine review fails — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times`
- AgentSession queue characterization > auto-refine pending review respects the cooldown — **[assertion-mismatch]** — `AssertionError: expected undefined to be defined`
- AgentSession queue characterization > preserves compact auto-refine pending state when no model is selected — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- AgentSession queue characterization > auto-refine review obeys the cooldown and preserves a 'turn_interval' checkpoint — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- AgentSession queue characterization > auto-refine review obeys the cooldown and preserves a 'compact' checkpoint — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- AgentSession scheduler scenarios > S6: auto-refine reviews after real turns, defers while busy, and drops reviews on navigation — **[assertion-mismatch]** — `AssertionError: expected [] to include 'auto_one'`

### `test/suite/agent-session-refine-skill.test.ts` (1 failing)

- AgentSession refine skill host requests > registers refine.run and refine.status handlers when auto-refine is allowed — **[assertion-mismatch]** — `AssertionError: expected [ 'rlm.run', 'rlm.find_models', …(8) ] to deeply equal ArrayContaining{…} ; - Expected ; + Received ; - ArrayContaining [`

### `test/suite/agent-session-runtime.test.ts` (3 failing)

- AgentSessionRuntime characterization > copies depth across new-session parent reference edges — **[assertion-mismatch]** — `AssertionError: expected { type: 'session', version: 3, …(6) } to match object { …(2) } ; (6 matching properties omitted from actual) ; - Expected ; + Received`
- AgentSessionRuntime characterization > releases a failed child run from the inline runtime host — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- AgentSessionRuntime characterization > updates the runtime session cwd on cross-cwd session replacement — **[timeout]** — `Error: Test timed out in 30000ms. ; If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".`

### `test/suite/agent-session-serialized-refine.test.ts` (28 failing)

- Serialized auto-refine checkpoint > refines exactly once when >25 tool turns run in one loop — **[assertion-mismatch]** — `AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times`
- Serialized auto-refine checkpoint > max concurrent primary/refinement model requests is one in serialized mode — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- Serialized auto-refine checkpoint > prompt/state update visible on resumed turn after serialized refine — **[assertion-mismatch]** — `AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times`
- Serialized auto-refine checkpoint > final agent_end pending refine completes before dispose — **[assertion-mismatch]** — `AssertionError: expected "_applyRefine" to be called at least once`
- Serialized auto-refine checkpoint > never deadlocks: serialized checkpoint does not call waitForIdle or _maybeAutoRefine — **[assertion-mismatch]** — `AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times`
- Serialized autonomous continuation > autonomous tool loop continues past serialized refinement boundary with no deadlock — **[assertion-mismatch]** — `AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times`
- Serialized background planning during tools > planning overlaps a deferred tool but next model turn waits for plan+apply — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- Serialized background planning during tools > lets refine.run supersede an interval plan that ignores abort — **[assertion-mismatch]** — `AssertionError: expected +0 to be 1 // Object.is equality ; - Expected ; + Received ; - 1`
- Serialized background planning during tools > max concurrent model calls is one: planning does not start another model request — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times`
- PR #503 model persistence regression > model is preserved after serialized refine checkpoint — **[assertion-mismatch]** — `AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times`
- Serialized refine review-fix regressions > failure result stamps cooldown and does NOT retry synchronously — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times`
- Serialized refine review-fix regressions > serialized failure does not schedule interactive auto-refine at agent_end — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times`
- Serialized refine review-fix regressions > interval bg plan failure does not retry synchronously — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times`
- Serialized refine review-fix regressions > interval background plan derives instructions from review, not prepopulated — **[assertion-mismatch]** — `AssertionError: expected undefined to be defined`
- Serialized refine review-fix regressions > disposal applies ready background plan before teardown — **[assertion-mismatch]** — `AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times`
- Serialized refine review-fix regressions > services a compaction-triggered refine at the next serialized boundary — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- Serialized refine review-fix regressions > defers serialized compaction refinement even when no continuation was scheduled — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- Serialized refine review-fix regressions > defers manual compaction refinement to the serialized checkpoint — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- Serialized refine review-fix regressions > preserves a serialized compaction trigger while cooldown is active — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- Serialized refine review-fix regressions > clears a serialized compaction trigger when disposal occurs during cooldown — **[assertion-mismatch]** — `AssertionError: expected true to be false // Object.is equality ; - Expected ; + Received ; - false`
- Serialized refine review-fix regressions > continues to the interval drain after a compact trigger hits cooldown — **[assertion-mismatch]** — `AssertionError: expected true to be false // Object.is equality ; - Expected ; + Received ; - false`
- Serialized refine review-fix regressions > falls back to an interval review when compact-triggered refinement is disabled — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ ObjectContaining{…}, …(1) ] ; Number of calls: 0`
- Serialized refine review-fix regressions > clears a compact trigger after a review decides no refinement is needed — **[assertion-mismatch]** — `AssertionError: expected "vi.fn()" to be called with arguments: [ ObjectContaining{…}, …(1) ] ; Number of calls: 0`
- Serialized refine review-fix regressions > does not let a compact review failure block disposal — **[assertion-mismatch]** — `AssertionError: expected true to be false // Object.is equality ; - Expected ; + Received ; - false`
- Serialized refine event-ordering integration > real message_end/turn_end ordering: threshold planning starts and applies before next model turn — **[assertion-mismatch]** — `AssertionError: expected "_applyRefine" to be called at least once`
- P0 concurrency regressions > steering waits for interval refine and threshold compaction boundaries — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- P0 concurrency regressions > branch navigation with in-flight serialized plan: aborts signal, no apply — **[assertion-mismatch]** — `AssertionError: expected undefined to be defined`
- P0 concurrency regressions > drains a due interactive auto-refine without waiting for agent idle — **[assertion-mismatch]** — `AssertionError: expected "_maybeAutoRefine" to be called with arguments: [ 'turn_interval' ] ; Number of calls: 0`

### `test/suite/daemon-serialized-refine-process.test.ts` (1 failing)

- Real-process serializedRefine — JSON mode > daemon supervisor scrubs inherited worker env, checkpoint applies refine_complete before agent_end — **[assertion-mismatch]** — `AssertionError: expected { code: 1, signal: null, …(2) } to match object { code: +0, signal: null } ; (2 matching properties omitted from actual) ; - Expected ; + Received`

### `test/suite/daemon-serialized-refine.test.ts` (1 failing)

- Daemon-backed serializedRefine propagation > daemon session with serializedRefine=true crosses threshold and applies refine — **[assertion-mismatch]** — `AssertionError: expected 2 to be +0 // Object.is equality ; - Expected ; + Received ; - 0`

### `test/suite/serialized-refine-config-integration.test.ts` (1 failing)

- Serialized refine config integration (unit) > real autonomous loop crosses threshold and resumes with serialized refine — **[assertion-mismatch]** — `AssertionError: expected 2 to be +0 // Object.is equality ; - Expected ; + Received ; - 0`

### `test/suite/regressions/2791-fswatch-error-crash.test.ts` (1 failing)

- issue #2791 fs.watch error event crashes process > process should survive an error event on the theme FSWatcher — **[assertion-mismatch]** — `AssertionError: Child crashed (exit 1). stderr: : expected 1 to be +0 // Object.is equality ; - Expected ; + Received ; - 0`

### `test/suite/regressions/3885-subagent-runtime-host.test.ts` (2 failing)

- ENG-3885 subagent runtime host > creates explicitly modeled RLM children as tracked AgentSessionRuntime instances — **[timeout]** — `Error: Timed out waiting for condition`
- ENG-3885 subagent runtime host > preserves initial model and thinking entries for inline RLM children — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`

### `test/suite/regressions/4257-update-restart-resume.test.ts` (2 failing)

- issue #4257 update restart resume > materializes queued in-memory drafts before update restart — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`
- issue #4257 update restart resume > materializes busy in-memory drafts before update restart — **[assertion-mismatch]** — `AssertionError: expected false to be true // Object.is equality ; - Expected ; + Received ; - true`

### `test/suite/regressions/4600-supervisor-singleton.test.ts` (1 failing)

- ENG-4600 daemon supervisor ownership > unwinds real pre-bind and post-bind startup failures before retry — **[ENOENT]** — `Error: ENOENT: no such file or directory, open '\\.\pipe\prime-agent-eng-4600-33928-1787290038487'`

### `test/suite/regressions/4603-worker-recovery.test.ts` (1 failing)

- ENG-4603 worker recovery convergence > serializes shutdown admission and reclaims an unrenewed live lease — **[EPERM]** — `Error: EPERM: operation not permitted, link 'C:\Program Files\nodejs\node.exe' -> 'C:\Users\assas\AppData\Local\Temp\pi-suite-1787289925606-ae4m5pyu1kd\prime-agent'`

### `test/suite/regressions/4606-update-restart-coordinator.test.ts` (2 failing)

- ENG-4606 update restart coordinator > keeps a relative agent directory stable across coordinator cwd changes — **[assertion-mismatch]** — `AssertionError: expected { version: 1, …(9) } to match object { phase: 'skipped', …(1) } ; (14 matching properties omitted from actual) ; - Expected ; + Received`
- ENG-4606 update restart coordinator > resolves a relative custom socket before changing coordinator cwd — **[assertion-mismatch]** — `AssertionError: expected { version: 1, …(9) } to match object { phase: 'skipped', …(1) } ; (14 matching properties omitted from actual) ; - Expected ; + Received`

### `test/suite/regressions/4620-fast-mode-child-agents.test.ts` (1 failing)

- ENG-4620 fast mode child agents > passes and persists fast mode for inline RLM children — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`

### `test/suite/regressions/4620-fast-mode-settings.test.ts` (1 failing)

- ENG-4620 fast mode settings > returns the effective service tier when cycling models — **[assertion-mismatch]** — `AssertionError: expected 'deepseek-v4-flash' to be 'gpt-5.4' // Object.is equality ; Expected: "gpt-5.4" ; Received: "deepseek-v4-flash"`

### `test/suite/regressions/4649-subagent-model-selection.test.ts` (14 failing)

- ENG-4649 subagent model selection > searches a bounded authenticated catalog without advertising it — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- ENG-4649 subagent model selection > omits providers whose credentials are marked expired — **[assertion-mismatch]** — `AssertionError: expected { models: [ { …(4) }, { …(4) } ] } to deeply equal { models: [] } ; - Expected ; + Received ;   {`
- ENG-4649 subagent model selection > limits ChatGPT discovery and execution to the account model catalog — **[assertion-mismatch]** — `AssertionError: expected [ 'deepseek/deepseek-v4-flash', …(2) ] to deeply equal [ 'openai-codex/parent-model' ] ; - Expected ; + Received ;   [`
- ENG-4649 subagent model selection > does not warn when an unavailable selector is already the parent model — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- ENG-4649 subagent model selection > does not start a child after its parent is disposed during preflight — **[assertion-mismatch]** — `AssertionError: expected "getApiKeyAndHeaders" to be called once, but got 0 times`
- ENG-4649 subagent model selection > reserves an explicit child name while model validation is pending — **[RLM-depth-env-induced]** — `AssertionError: expected [Function] to throw error including 'Agent name "shared-reviewer" is unava…' but got 'RLM recursion depth limit reached (RL…' ; Expected: "Agent name "shar`
- ENG-4649 subagent model selection > runs and retains a child on an explicitly selected model — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- ENG-4649 subagent model selection > applies an explicit 'low' thinking level to the child — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- ENG-4649 subagent model selection > applies an explicit 'off' thinking level to the child — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- ENG-4649 subagent model selection > inherits the parent thinking level when no override is supplied — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- ENG-4649 subagent model selection > fails spawn when an explicit thinking level is unsupported by the resolved model — **[RLM-depth-env-induced]** — `AssertionError: expected [Function] to throw error including 'Requested thinking level "high" is no…' but got 'RLM recursion depth limit reached (RL…' ; Expected: "Requested thinki`
- ENG-4649 subagent model selection > inherits the parent model when no override is supplied — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- ENG-4649 subagent model selection > accepts a selected model authenticated by headers — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`
- ENG-4649 subagent model selection > rejects unavailable requested models at admission without fallback — **[RLM-depth-env-induced]** — `AssertionError: expected [Function] to throw error including 'is unavailable, unauthenticated, or e…' but got 'RLM recursion depth limit reached (RL…' ; Expected: "is unavailable,`

### `test/suite/regressions/4685-daemon-client-modes.test.ts` (13 failing)

- ENG-4685 daemon-backed client modes > runs host-owned autonomous gate retries through the shared completion loop — **[assertion-mismatch]** — `AssertionError: expected [ …(2) ] to have a length of 1 but got 2 ; - Expected ; + Received ; - 1`
- ENG-4685 daemon-backed client modes > launches real daemon workers for every migrated client surface — **[timeout]** — `Error: CLI timed out ; (node:56032) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set. ; (Use 'node --trace-warnings ...' to show where the warning was`
- ENG-4685 daemon-backed client modes > keeps the rollback frontend fully off the daemon path — **[timeout]** — `Error: CLI timed out ; (node:58276) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set. ; (Use 'node --trace-warnings ...' to show where the warning was`
- ENG-4685 daemon-backed client modes > loads headless runtime services only in the worker — **[timeout]** — `Error: CLI timed out ; (node:53028) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set. ; (Use 'node --trace-warnings ...' to show where the warning was`
- ENG-4685 daemon-backed client modes > drains accepted RPC commands before EOF releases the connection — **[assertion-mismatch]** — `AssertionError: expected '(node:48768) Warning: The \'NO_COLOR\…' to be '' // Object.is equality ; - Expected ; + Received ; + (node:48768) Warning: The 'NO_COLOR' env is ignored d`
- ENG-4685 daemon-backed client modes > drains accepted RPC prompt work before EOF releases the connection — **[assertion-mismatch]** — `AssertionError: expected '(node:55876) Warning: The \'NO_COLOR\…' to be '' // Object.is equality ; - Expected ; + Received ; + (node:55876) Warning: The 'NO_COLOR' env is ignored d`
- ENG-4685 daemon-backed client modes > drains accepted daemon RPC prompt work before EOF — **[timeout]** — `Error: CLI timed out ; (node:54344) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set. ; (Use 'node --trace-warnings ...' to show where the warning was`
- ENG-4685 daemon-backed client modes > drains an unterminated final RPC command before EOF — **[assertion-mismatch]** — `AssertionError: expected '(node:4476) Warning: The \'NO_COLOR\'…' to be '' // Object.is equality ; - Expected ; + Received ; + (node:4476) Warning: The 'NO_COLOR' env is ignored du`
- ENG-4685 daemon-backed client modes > returns a structured error for scalar JSON input — **[assertion-mismatch]** — `AssertionError: expected '(node:54480) Warning: The \'NO_COLOR\…' to be '' // Object.is equality ; - Expected ; + Received ; + (node:54480) Warning: The 'NO_COLOR' env is ignored d`
- ENG-4685 daemon-backed client modes > cancels pending extension dialogs on RPC EOF — **[assertion-mismatch]** — `AssertionError: expected '(node:35116) Warning: The \'NO_COLOR\…' to be '' // Object.is equality ; - Expected ; + Received ; + (node:35116) Warning: The 'NO_COLOR' env is ignored d`
- ENG-4685 daemon-backed client modes > preserves prompt acknowledgements before events and repeated prompts — **[assertion-mismatch]** — `AssertionError: expected '(node:46696) Warning: The \'NO_COLOR\…' to be '' // Object.is equality ; - Expected ; + Received ; + (node:46696) Warning: The 'NO_COLOR' env is ignored d`
- ENG-4685 daemon-backed client modes > preserves RPC trimming and omitted-value encoding — **[assertion-mismatch]** — `AssertionError: expected '(node:50604) Warning: The \'NO_COLOR\…' to be '' // Object.is equality ; - Expected ; + Received ; + (node:50604) Warning: The 'NO_COLOR' env is ignored d`
- ENG-4685 daemon-backed client modes > exposes daemon schedules, heartbeats, messaging, and observation — **[assertion-mismatch]** — `AssertionError: expected '(node:50240) Warning: The \'NO_COLOR\…' to be '' // Object.is equality ; - Expected ; + Received ; + (node:50240) Warning: The 'NO_COLOR' env is ignored d`

### `test/suite/regressions/617-subagent-terminal-agent-message.test.ts` (1 failing)

- #617 subagent terminal agent messages > falls back to an injected notice when the agent message cannot be delivered — **[RLM-depth-env-induced]** — `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)`

## Notes

- Test run was executed exactly once. No failing test was retried, and no test or source file was edited to make a failure pass, per instructions.
- Only the 2 already-qualified patches (bootstrap.ts, session-lease.ts) were present in the worktree; no additional patch was applied.
- The categorization above is derived strictly from the literal error text vitest printed (first 1-4 lines of each failure block); no further root-cause diagnosis was performed.
- Full raw stdout+stderr log (9185 lines): `C:\Users\assas\.prime-eperm-repro\logs\ab-074-vitest-full.log`
