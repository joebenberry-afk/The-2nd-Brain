# Prime v0.7.3 Flaky-Test A/B Run — Worker Report (isolated, non-live)

## Scope / non-tampering confirmation

- Worktree: `C:\Users\assas\.prime-074-compat\throwaway-073` (commit `61131b2d195ba7a67a4ce8ac60bb10cecae07b67`, tag `v0.7.3`)
- `C:\Tools\prime-agent` (live install) was never read, cd'd into, or referenced.
- No source file in the worktree was modified during this task.
- No additional patch was applied.

## Step 2 — `git status --short` (repo root)

```
 M packages/coding-agent/src/core/kernel/bootstrap.ts
 M packages/coding-agent/src/core/session-lease.ts
```

Confirmed: exactly the 2 expected modified files (bootstrap.ts, session-lease.ts), nothing else. Working tree is otherwise clean.

## Step 3 — Command run

```
cd "C:\Users\assas\.prime-074-compat\throwaway-073\packages\coding-agent"
"C:\Users\assas\.prime-074-compat\throwaway-073\node_modules\.bin\vitest.cmd" --run
```

Full stdout+stderr captured to:
`C:\Users\assas\.prime-eperm-repro\logs\ab-073-vitest-full.log`

Run was allowed to complete (no cancellation). No failed tests were retried; no test/source file was edited.

## Step 4 — Results

**Exact exit code:** `1`

**Vitest summary line (verbatim from log):**
```
 Test Files  63 failed | 252 passed | 8 skipped (323)
      Tests  323 failed | 3868 passed | 61 skipped (4252)
     Errors  14 errors
   Start at  01:24:54
   Duration  261.89s (transform 132.99s, setup 0ms, import 1535.18s, tests 2568.96s, environment 74ms)
```

- Total test files run: 63 failed + 252 passed + 8 skipped = **323 files** (of 4252 total test count reported)
- Total tests: **323 failed / 3868 passed / 61 skipped** (4252 total)
- 14 additional unhandled errors (uncaught exceptions / unhandled rejections) were reported separately from the 323 failed-test count; see 'Unhandled Errors' section of the log (mostly `listen EACCES` on Windows named-pipe/socket paths and one `RLM recursion depth limit reached` unhandled rejection).

### Failure categorization (heuristic, from error text only)

| Category | Count |
|---|---|
| assertion/logic | 203 |
| env-config (RLM_MAX_DEPTH=1 depth limit) | 55 |
| timeout | 36 |
| EPERM/EACCES/filesystem | 29 |

Notes on categorization method: category assigned by scanning each failure's printed error/stack block for keywords: `EPERM`/`EACCES` → filesystem; `timed out`/`timeout` → timeout; `RLM_MAX_DEPTH`/`recursion depth limit` → env-config; otherwise → assertion/logic (needs review). This is a text-pattern classification only, not root-cause analysis.

- **env-config (RLM_MAX_DEPTH=1 depth limit), 55 failures**: all show `Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)` thrown from `AgentSession._startRlmChildRun` (`src/core/agent-session.ts:9767`), either directly or as the cause of a downstream assertion mismatch. This matches the daemon's `RLM_MAX_DEPTH=1` environment constraint noted in this run's environment; these tests appear to expect a deeper recursion allowance than the current process env provides.
- **timeout, 36 failures**: `Error: Test timed out in Nms` or `Timed out waiting for condition` (vitest `testTimeout` or an in-test `waitFor` polling helper). Concentrated in `test/kernel-bootstrap.test.ts` (all 3 failures there are 30000ms timeouts) and `test/agent-session-recursion.test.ts`.
- **EPERM/EACCES/filesystem, 29 failures**: `EACCES`/`EPERM` on `listen`/socket/pipe paths (e.g. `listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\pa-launch-...\d.sock`) and related filesystem/IPC errors, concentrated in daemon/socket tests (`test/daemon-launch.test.ts`, `test/daemon-mode.test.ts`, `test/daemon-supervisor-process.test.ts`).
- **assertion/logic (needs review), 203 failures**: standard `AssertionError`/`expected ... to ...` mismatches with no timeout/EPERM/RLM-depth keyword in the printed block. This is the largest bucket; per-file concentration (`test/agent-session-recursion.test.ts` 49, `test/suite/agent-session-serialized-refine.test.ts` 28, `test/extensions-discovery.test.ts` 23, `test/extensions-runner.test.ts` 21, `test/suite/agent-session-queue.test.ts` 18) suggests a shared fixture/setup issue in those suites rather than 203 independent bugs, but this run does not attempt further root-cause diagnosis per task scope (no fixes, no reruns).

### Top files by failure count

| File | Failures |
|---|---|
| `test/agent-session-recursion.test.ts` | 49 |
| `test/suite/agent-session-serialized-refine.test.ts` | 28 |
| `test/extensions-discovery.test.ts` | 23 |
| `test/extensions-runner.test.ts` | 21 |
| `test/suite/agent-session-queue.test.ts` | 18 |
| `test/kernel-bootstrap.test.ts` | 17 |
| `test/suite/regressions/4685-daemon-client-modes.test.ts` | 13 |
| `test/suite/regressions/4649-subagent-model-selection.test.ts` | 10 |
| `test/herdr-agent-state.test.ts` | 9 |
| `test/kernel-attach-image-skill.test.ts` | 9 |
| `test/daemon-launch.test.ts` | 8 |
| `test/daemon-mode.test.ts` | 8 |
| `test/daemon-supervisor-process.test.ts` | 8 |
| `test/suite/agent-session-autonomous.test.ts` | 8 |
| `test/extensions-input-event.test.ts` | 7 |

## Full list of failed tests (file : test name : category : first error line)

All 323 unique failing tests, in the order vitest reported them. Category is the heuristic bucket above; error text is the first non-empty line of the printed error for that failure (truncated as vitest truncates it).

1. `test/acp-rlm-subagents.test.ts` — ACP mode surfaces RLM subagents > streams subagent lifecycle to an ACP client as namespaced metadata
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
2. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > lets the orchestrator choose a unique subagent session name
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
3. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > falls back to listed family metadata when a controller lacks name validation
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: AssertionError: expected [Function] to throw error including 'Agent name "passive-worker" is unavai…' but got 'RLM recursion depth limit reached (RL…'
4. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > reserves a running child's current name after it is renamed
   - category: timeout
   - error: Error: Timed out waiting for condition
5. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > retries and releases failed retained child cleanup on the next compaction
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: AssertionError: promise rejected "Error: RLM recursion depth limit reached …" instead of resolving
6. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > makes an orchestrator-chosen name override a custom runtime's preexisting name
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
7. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > runs a child session under a sub directory and returns an RLM-shaped result
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
8. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > resolves a spawned child handle to its published session before a roled send
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
9. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > delivers an id-addressed send while a completed child's terminal injection is pending
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
10. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > propagates pending child startup failure to an immediate roled send
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
11. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > falls through a retained failed child name to a healthy roster child
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
12. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > falls through a delete-before-startup tombstone during a roled send
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
13. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > surfaces post-admission startup failure in the parent transcript and subagent registry
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
14. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > injects exactly one cancellation notice when a child run is cancelled
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
15. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > injects exactly one notice with a preview when a child completes without replying
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
16. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > does not inject a terminal notice when a parent follow-up resets reply state after a reply
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
17. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > keeps detached deletion silent when child startup later settles
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
18. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > fully deletes a settled startup failure and frees its session name
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
19. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > releases a hosted child when its initial task fails
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
20. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > notifies the runtime host when the initial child task completes
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
21. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > projects retained child follow-up turns into parent child-update activity
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
22. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > lists a completed child with its parent-scoped messaging identity until disposal
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
23. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > disposes an inline child when setting its session name fails
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
24. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > emits updated child session names after a retained child is renamed
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
25. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > surfaces a child's recap on its snapshot once the summarizer sets it
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
26. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > runs a child agent without requiring ripgrep
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
27. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > adds child usage to the parent session aggregate
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
28. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > attributes every tool-loop turn in the admitted task to spawn usage
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
29. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > gets and persists per-chat max-depth changes without transcript messages
   - category: assertion/logic
   - error: AssertionError: expected { maxDepth: 1, source: 'env' } to deeply equal { maxDepth: 1, source: 'default' }
30. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > uses a max-depth prompt update on the next turn of the active run
   - category: assertion/logic
   - error: AssertionError: expected 'You are a general purpose agent that …' to contain 'A callable `rlm`'
31. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > copies live max depth at spawn, keeps child overrides independent, and lets zero disable root spawning
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: AssertionError: expected [Function] to throw error including 'RLM recursion depth limit reached (RL…' but got 'RLM recursion depth limit reached (RL…'
32. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > lets a stale kernel depth cap defer to the live host gate
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: AssertionError: the given combination of arguments (undefined and string) is invalid for this assertion. You can use an array, a map, an object, a set, a string, or a weakset instead of a string
33. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > cancels active rlm children when the parent session is disposed
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
34. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > cancels active rlm children when the parent session is aborted
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
35. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > does not admit a child prompt when the parent is aborted while resolving the sender
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
36. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > does not cancel active rlm children when only the parent turn is interrupted
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
37. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > cancels a single rlm child run by id and reports unknown ids
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
38. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > deletes only inactive RLM children through the explicit inactive path
   - category: timeout
   - error: Error: Timed out waiting for condition
39. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > releases a hosted child when completion persistence fails
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
40. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > does not let completion retention resurrect a child being deleted
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
41. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > reconciles failed-delete tracking when the detached retry succeeds
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
42. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > reserves an errored startup name while its detached failure injection settles
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
43. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > reserves a deleted queued child's name until startup settles
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
44. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > deletes a queued child without waiting for blocked startup
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
45. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > keeps late startup cleanup retryable when release and fallback delete fail
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
46. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > deletes a running direct child by name and waits for runtime cleanup
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
47. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > deletes an inactive nested RLM child through the root session
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=2, RLM_MAX_DEPTH=2)
48. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > cancels nested rlm child runs through the root session
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=2, RLM_MAX_DEPTH=2)
49. `test/agent-session-recursion.test.ts` — AgentSession rlm recursion > handles rlm calls from asyncio tasks after the scheduling cell is idle
   - category: EPERM/EACCES/filesystem
   - error: Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe'
50. `test/agent-session-recursion.test.ts` — AgentSession RLM session dir > does not create a /tmp dir or set RLM_SESSION_DIR for a non-persisted session
   - category: assertion/logic
   - error: AssertionError: expected { RLM_DEPTH: '1', …(2) } to match object { RLM_DEPTH: '0' }
51. `test/agents-view-inactive-reply.test.ts` — agents view reply on inactive sessions > resumes a saved session before delivering the reply
   - category: assertion/logic
   - error: AssertionError: expected [ 'file:/tmp/sessions/saved-1.jsonl' ] to not include 'file:/tmp/sessions/saved-1.jsonl'
52. `test/agents-view-inactive-reply.test.ts` — agents view reply on inactive sessions > does not select a resumed session after its reply target is cancelled
   - category: assertion/logic
   - error: AssertionError: expected [ 'file:/tmp/sessions/saved-1.jsonl' ] to not include 'file:/tmp/sessions/saved-1.jsonl'
53. `test/agents-view-inactive-reply.test.ts` — agents view reply on inactive sessions > handles 'send failure'
   - category: assertion/logic
   - error: 
54. `test/agents-view-inactive-reply.test.ts` — agents view reply on inactive sessions > handles 'replacement text entered during send …'
   - category: assertion/logic
   - error: AssertionError: expected true to be false // Object.is equality
55. `test/agents-view-inactive-reply.test.ts` — agents view slash commands > re-resolves the armed target before dispatching a view command
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called with arguments: [ { name: 'kill', args: '' }, …(1) ]
56. `test/agents-view-mode.test.ts` — AgentsViewMode > keeps subagent expansion across the active-to-persisted identity flip
   - category: assertion/logic
   - error: AssertionError: expected 'file:C:\tmp\root.jsonl' to be 'file:/tmp/root.jsonl' // Object.is equality
57. `test/agents-view-state.test.ts` — agents view state > reconciles canonical paths and session ids while retaining saved search text
   - category: assertion/logic
   - error: AssertionError: expected { …(6) } to match object { …(4) }
58. `test/agents-view-state.test.ts` — agents view state > preserves live identity and row state when saved metadata adds a file alias
   - category: assertion/logic
   - error: AssertionError: expected { saved: { …(13) }, …(4) } to match object { …(2) }
59. `test/auth-flows.test.ts` — ProviderAuthFlows > stores a reused Prime CLI key when Prime CLI config sync is disabled
   - category: timeout
   - error: Error: Test timed out in 30000ms.
60. `test/auth-storage.test.ts` — AuthStorage > API key resolution > setPrimeInferenceApiKey creates Prime CLI config
   - category: assertion/logic
   - error: AssertionError: expected 438 to be 384 // Object.is equality
61. `test/command-recovery-journal.test.ts` — CommandRecoveryJournal > durably removes acknowledged results
   - category: EPERM/EACCES/filesystem
   - error: Error: EPERM: operation not permitted, fsync
62. `test/config.test.ts` — detectInstallMethod > self-update respects configured npmCommand
   - category: assertion/logic
   - error: AssertionError: expected undefined to deeply equal { Object (command, args, ...) }
63. `test/config.test.ts` — detectInstallMethod > self-updates bun global installs from bun pm bin
   - category: assertion/logic
   - error: AssertionError: expected undefined to deeply equal { command: 'bun', …(2) }
64. `test/config.test.ts` — detectInstallMethod > self-updates renamed bun global installs by removing the old package first
   - category: assertion/logic
   - error: AssertionError: expected undefined to deeply equal { command: 'bun', …(3) }
65. `test/config.test.ts` — detectInstallMethod > does not self-update when npm install path is not writable
   - category: assertion/logic
   - error: AssertionError: expected { Object (command, args, ...) } to be undefined
66. `test/config.test.ts` — session paths > expands tilde in the session root env var
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas/prime-agent-sessions' to be 'C:\Users\assas\prime-agent-sessions' // Object.is equality
67. `test/daemon-launch.test.ts` — probeRunningDaemonSessions > returns only sessions that have an activeSessionId
   - category: timeout
   - error: Error: Test timed out in 30000ms.
68. `test/daemon-launch.test.ts` — probeRunningDaemonSessions > returns an empty list when the daemon is reachable but idle
   - category: timeout
   - error: Error: Test timed out in 30000ms.
69. `test/daemon-launch.test.ts` — probeRunningDaemonSessions > leaves activeSessions undefined when reachable but the list fails
   - category: timeout
   - error: Error: Test timed out in 30000ms.
70. `test/daemon-launch.test.ts` — ensureInteractiveDaemonRunning > rejects a busy pre-session-action daemon before attach
   - category: timeout
   - error: Error: Test timed out in 30000ms.
71. `test/daemon-launch.test.ts` — ensureInteractiveDaemonRunning > does not replace a stale daemon with busy private client sessions
   - category: timeout
   - error: Error: Test timed out in 30000ms.
72. `test/daemon-launch.test.ts` — ensureInteractiveDaemonRunning > does not treat a live daemon as absent when cold startup delays the first connection
   - category: timeout
   - error: Error: Test timed out in 30000ms.
73. `test/daemon-launch.test.ts` — ensureInteractiveDaemonRunning > succeeds when the spawned child loses the race to an already-serving daemon
   - category: timeout
   - error: Error: Test timed out in 30000ms.
74. `test/daemon-launch.test.ts` — shutdownDaemonAndWait > stops a running daemon and returns true
   - category: timeout
   - error: Error: Test timed out in 30000ms.
75. `test/daemon-mode.test.ts` — daemon mode helpers > discovers a non-resident child left running in the persisted registry
   - category: assertion/logic
   - error: AssertionError: expected { …(2) } to match object { entries: [ ObjectContaining{…} ] }
76. `test/daemon-mode.test.ts` — daemon mode helpers > does not retry supervisor agent-message rejections
   - category: timeout
   - error: Error: Test timed out in 30000ms.
77. `test/daemon-mode.test.ts` — daemon mode helpers > routes worker-local session renames through the supervisor
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\pa-worker-rename-nsEbex\s
78. `test/daemon-mode.test.ts` — daemon mode helpers > does not retry permanent ambiguity errors from the supervisor
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\pa-ambiguous-6W3fst\s
79. `test/daemon-mode.test.ts` — daemon mode helpers > reports failed passive children as errors without creating child runtimes
   - category: assertion/logic
   - error: AssertionError: expected { …(2) } to match object { Object (current, entries) }
80. `test/daemon-mode.test.ts` — daemon mode helpers > validates a requested passive child name before hydration
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called with arguments: [ { name: 'sibling', depth: 1, …(3) } ]
81. `test/daemon-mode.test.ts` — daemon mode helpers > rehydrates a legacy passive subagent at depth one
   - category: assertion/logic
   - error: AssertionError: expected 2 to be 1 // Object.is equality
82. `test/daemon-mode.test.ts` — daemon mode helpers > does not fail a deletion when the artifact dir cannot be removed
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
83. `test/daemon-supervisor-monitor.test.ts` — daemon worker supervisor monitoring > limits abort admission to mutation drain
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied \tmp\prime-update-drain-44132-rXB3rN\supervisor.sock
84. `test/daemon-supervisor-ownership.test.ts` — daemon supervisor ownership registry > disambiguates never-acquired from lost-on-disk ownership errors
   - category: assertion/logic
   - error: AssertionError: expected 'Daemon supervisor generation registry…' to contain 'C:\Users\assas\AppData\Local\Temp\own…'
85. `test/daemon-supervisor-process.test.ts` — daemon supervisor resident workers > lists, creates, and attaches passive children through their owning worker
   - category: timeout
   - error: Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-passive-26604-a0a05055.sock. Socket: C:\Users\assas\AppData\Local\Temp\prime-supervisor-passive-26604-a0a05055.sock. Daemon log: C:\Users\assas\.prime\agent\logs\prime-supervisor-passive-26604-a0a05055.sock.a3363cc4.log.
86. `test/daemon-supervisor-process.test.ts` — daemon supervisor resident workers > keeps client-owned workers hidden and removes them without archiving
   - category: timeout
   - error: Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-owned-26604-83840c82.sock. Socket: C:\Users\assas\AppData\Local\Temp\prime-supervisor-owned-26604-83840c82.sock. Daemon log: C:\Users\assas\.prime\agent\logs\prime-supervisor-owned-26604-83840c82.sock.d4c119e4.log.
87. `test/daemon-supervisor-process.test.ts` — daemon supervisor resident workers > releases an adopted client-owned worker when disposal races supervisor replacement
   - category: timeout
   - error: Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-owned-adopt-26604-e70dd6bb.sock. Socket: C:\Users\assas\AppData\Local\Temp\prime-supervisor-owned-adopt-26604-e70dd6bb.sock. Daemon log: C:\Users\assas\.prime\agent\logs\prime-supervisor-owned-adopt-26604-e70dd6bb.sock.b0512a28.log.
88. `test/daemon-supervisor-process.test.ts` — daemon supervisor resident workers > delivers agent-origin messages between root siblings on separate workers
   - category: EPERM/EACCES/filesystem
   - error: Error: Supervisor exited before becoming ready (code 1, signal null)
89. `test/daemon-supervisor-process.test.ts` — daemon supervisor resident workers > restarts an empty supervisor without requiring a resident worker
   - category: EPERM/EACCES/filesystem
   - error: Error: Supervisor exited before becoming ready (code 1, signal null)
90. `test/daemon-supervisor-process.test.ts` — daemon supervisor resident workers > archives resident roots and cancels their heartbeats on explicit daemon shutdown
   - category: EPERM/EACCES/filesystem
   - error: Error: Supervisor exited before becoming ready (code 1, signal null)
91. `test/daemon-supervisor-process.test.ts` — daemon supervisor resident workers > hosts and adopts isolated worker processes
   - category: timeout
   - error: Error: Timed out waiting for supervisor: Error: Failed to connect to the Prime Agent daemon: connect ENOENT C:\Users\assas\AppData\Local\Temp\prime-supervisor-smoke-26604-53be1911.sock. Socket: C:\Users\assas\AppData\Local\Temp\prime-supervisor-smoke-26604-53be1911.sock. Daemon log: C:\Users\assas\.prime\agent\logs\prime-supervisor-smoke-26604-53be1911.sock.fb8d0305.log.
92. `test/daemon-supervisor-process.test.ts` — daemon supervisor resident workers > isolates a root, streams a chunked snapshot, and adopts the same worker after restart
   - category: EPERM/EACCES/filesystem
   - error: Error: Supervisor exited before becoming ready (code 1, signal null)
93. `test/daemon-supervisor-side-question.test.ts` — daemon supervisor side-question routing > rejects a protocol-6 client through the supervisor socket before state exchange
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\prime-supervisor-old-client-wyTNEe\supervisor.sock
94. `test/extensions-discovery.test.ts` — extensions discovery > discovers direct .ts files in extensions/
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) }, { …(2) } ] to have a length of +0 but got 2
95. `test/extensions-discovery.test.ts` — extensions discovery > discovers direct .js files in extensions/
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
96. `test/extensions-discovery.test.ts` — extensions discovery > discovers subdirectory with index.ts
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
97. `test/extensions-discovery.test.ts` — extensions discovery > discovers subdirectory with index.js
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
98. `test/extensions-discovery.test.ts` — extensions discovery > prefers index.ts over index.js
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
99. `test/extensions-discovery.test.ts` — extensions discovery > discovers subdirectory with package.json pi field
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
100. `test/extensions-discovery.test.ts` — extensions discovery > package.json can declare multiple extensions
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) }, { …(2) } ] to have a length of +0 but got 2
101. `test/extensions-discovery.test.ts` — extensions discovery > package.json with pi field takes precedence over index.ts
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
102. `test/extensions-discovery.test.ts` — extensions discovery > ignores package.json without pi field, falls back to index.ts
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
103. `test/extensions-discovery.test.ts` — extensions discovery > handles mixed direct files and subdirectories
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) }, { …(2) }, { …(2) } ] to have a length of +0 but got 3
104. `test/extensions-discovery.test.ts` — extensions discovery > skips non-existent paths declared in package.json
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
105. `test/extensions-discovery.test.ts` — extensions discovery > loads extensions and registers commands
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
106. `test/extensions-discovery.test.ts` — extensions discovery > loads extensions and registers tools
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
107. `test/extensions-discovery.test.ts` — extensions discovery > handles explicitly configured paths
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
108. `test/extensions-discovery.test.ts` — extensions discovery > resolves dependencies from extension's own node_modules
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
109. `test/extensions-discovery.test.ts` — extensions discovery > registers message renderers
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
110. `test/extensions-discovery.test.ts` — extensions discovery > reports error when extension throws during initialization
   - category: assertion/logic
   - error: AssertionError: expected 'Failed to load extension: Cannot find…' to contain 'Initialization failed!'
111. `test/extensions-discovery.test.ts` — extensions discovery > reports error when extension has no default export
   - category: assertion/logic
   - error: AssertionError: expected 'Failed to load extension: Cannot find…' to contain 'does not export a valid factory funct…'
112. `test/extensions-discovery.test.ts` — extensions discovery > allows multiple extensions to register different tools
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) }, { …(2) } ] to have a length of +0 but got 2
113. `test/extensions-discovery.test.ts` — extensions discovery > loads extension with event handlers
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
114. `test/extensions-discovery.test.ts` — extensions discovery > loads extension with shortcuts
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
115. `test/extensions-discovery.test.ts` — extensions discovery > loads extension with flags
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
116. `test/extensions-discovery.test.ts` — extensions discovery > loadExtensions only loads explicit paths without discovery
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) } ] to have a length of +0 but got 1
117. `test/extensions-input-event.test.ts` — Input Event > transforms text and preserves images when omitted
   - category: assertion/logic
   - error: AssertionError: expected { action: 'continue' } to deeply equal { action: 'transform', …(2) }
118. `test/extensions-input-event.test.ts` — Input Event > transforms and replaces images when provided
   - category: assertion/logic
   - error: AssertionError: expected { action: 'continue' } to deeply equal { Object (action, text, ...) }
119. `test/extensions-input-event.test.ts` — Input Event > chains transforms across multiple handlers
   - category: assertion/logic
   - error: AssertionError: expected { action: 'continue' } to deeply equal { action: 'transform', …(2) }
120. `test/extensions-input-event.test.ts` — Input Event > short-circuits on handled and skips subsequent handlers
   - category: assertion/logic
   - error: AssertionError: expected { action: 'continue' } to deeply equal { action: 'handled' }
121. `test/extensions-input-event.test.ts` — Input Event > passes source correctly for all source types
   - category: assertion/logic
   - error: AssertionError: expected undefined to be 'interactive' // Object.is equality
122. `test/extensions-input-event.test.ts` — Input Event > catches handler errors and continues
   - category: assertion/logic
   - error: AssertionError: expected [] to include 'boom'
123. `test/extensions-input-event.test.ts` — Input Event > hasHandlers returns correct value
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
124. `test/extensions-runner.test.ts` — ExtensionRunner > shortcut conflicts > warns when extension shortcut conflicts with built-in
   - category: assertion/logic
   - error: AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ]
125. `test/extensions-runner.test.ts` — ExtensionRunner > shortcut conflicts > allows a shortcut when the reserved set no longer contains the default key
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
126. `test/extensions-runner.test.ts` — ExtensionRunner > shortcut conflicts > warns but allows when extension uses non-reserved built-in shortcut
   - category: assertion/logic
   - error: AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ]
127. `test/extensions-runner.test.ts` — ExtensionRunner > shortcut conflicts > blocks shortcuts for reserved actions even when rebound
   - category: assertion/logic
   - error: AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ]
128. `test/extensions-runner.test.ts` — ExtensionRunner > shortcut conflicts > blocks shortcuts when reserved key is also bound to non-reserved actions
   - category: assertion/logic
   - error: AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ]
129. `test/extensions-runner.test.ts` — ExtensionRunner > shortcut conflicts > blocks shortcuts when reserved action has multiple keys
   - category: assertion/logic
   - error: AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ]
130. `test/extensions-runner.test.ts` — ExtensionRunner > shortcut conflicts > warns but allows when non-reserved action has multiple keys
   - category: assertion/logic
   - error: AssertionError: expected "warn" to be called with arguments: [ StringContaining{…} ]
131. `test/extensions-runner.test.ts` — ExtensionRunner > shortcut conflicts > warns when two extensions register same shortcut
   - category: assertion/logic
   - error: AssertionError: expected "warn" to be called with arguments: [ Array(1) ]
132. `test/extensions-runner.test.ts` — ExtensionRunner > tool collection > collects tools from multiple extensions
   - category: assertion/logic
   - error: AssertionError: expected +0 to be 2 // Object.is equality
133. `test/extensions-runner.test.ts` — ExtensionRunner > tool collection > keeps first tool when two extensions register the same name
   - category: assertion/logic
   - error: AssertionError: expected [] to have a length of 1 but got +0
134. `test/extensions-runner.test.ts` — ExtensionRunner > command collection > collects commands from multiple extensions
   - category: assertion/logic
   - error: AssertionError: expected +0 to be 2 // Object.is equality
135. `test/extensions-runner.test.ts` — ExtensionRunner > command collection > gets command by invocation name
   - category: assertion/logic
   - error: AssertionError: expected undefined to be defined
136. `test/extensions-runner.test.ts` — ExtensionRunner > command collection > suffixes duplicate extension commands in insertion order
   - category: assertion/logic
   - error: AssertionError: expected [] to have a length of 2 but got +0
137. `test/extensions-runner.test.ts` — ExtensionRunner > error handling > calls error listeners when handler throws
   - category: assertion/logic
   - error: AssertionError: expected +0 to be 1 // Object.is equality
138. `test/extensions-runner.test.ts` — ExtensionRunner > message renderers > gets message renderer by type
   - category: assertion/logic
   - error: AssertionError: expected undefined to be defined
139. `test/extensions-runner.test.ts` — ExtensionRunner > flags > collects flags from extensions
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
140. `test/extensions-runner.test.ts` — ExtensionRunner > flags > keeps first flag when two extensions register the same name
   - category: assertion/logic
   - error: AssertionError: expected undefined to be 'first' // Object.is equality
141. `test/extensions-runner.test.ts` — ExtensionRunner > before_agent_start > keeps ctx.getSystemPrompt() in sync with chained system prompt updates
   - category: assertion/logic
   - error: AssertionError: expected [ { …(2) }, { …(2) } ] to deeply equal []
142. `test/extensions-runner.test.ts` — ExtensionRunner > tool_result chaining > chains content modifications across handlers
   - category: assertion/logic
   - error: AssertionError: expected undefined to be defined
143. `test/extensions-runner.test.ts` — ExtensionRunner > tool_result chaining > preserves previous modifications when later handlers return partial patches
   - category: assertion/logic
   - error: AssertionError: expected undefined to deeply equal { content: [ { …(2) } ], …(2) }
144. `test/extensions-runner.test.ts` — ExtensionRunner > hasHandlers > returns true when handlers exist for event type
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
145. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > ignores events from sessions other than the one it bound to
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-ebgn3f\h.sock
146. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > reports lifecycle state to the herdr socket
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-2y20bl\h.sock
147. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > unsubscribes the shared-bus herdr:blocked listener on shutdown
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-s79hd2\h.sock
148. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > reports working when the session starts mid-turn (reload)
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-7i0olf\h.sock
149. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > settles the retry hold when a blocked event interrupts it
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-0mxbn4\h.sock
150. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > holds working through any error end until the retry grace settles
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-uegkso\h.sock
151. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > sends no reports after quit release
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-ihldud\h.sock
152. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > silences a replaced instance without releasing the pane
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-z7unsi\h.sock
153. `test/herdr-agent-state.test.ts` — herdrAgentStateExtension > keeps seq monotonically increasing across extension instances
   - category: EPERM/EACCES/filesystem
   - error: Error: listen EACCES: permission denied C:\Users\assas\AppData\Local\Temp\hrd-8y8ih7\h.sock
154. `test/interactive-mode-suspend.test.ts` — InteractiveMode.handleCtrlZ > keeps the process alive while suspended and restores the TUI on SIGCONT
   - category: assertion/logic
   - error: TypeError: this.showStatus is not a function
155. `test/interactive-mode-suspend.test.ts` — InteractiveMode.handleCtrlZ > cleans up the temporary handlers if suspension fails
   - category: assertion/logic
   - error: AssertionError: expected a thrown error to be Error: suspend failed
156. `test/ipython-provisioner.test.ts` — IpythonKernelProvisioner > memoizes concurrent ensure() calls into one startup
   - category: assertion/logic
   - error: AssertionError: expected +0 to be 1 // Object.is equality
157. `test/ipython-provisioner.test.ts` — IpythonKernelProvisioner > retries after a failed startup instead of caching the rejection
   - category: assertion/logic
   - error: AssertionError: expected +0 to be 2 // Object.is equality
158. `test/ipython-provisioner.test.ts` — IpythonKernelProvisioner > prewarm() swallows the failure and the next ensure() starts fresh
   - category: assertion/logic
   - error: AssertionError: expected 0 to be greater than or equal to 2
159. `test/ipython-provisioner.test.ts` — IpythonKernelProvisioner > waits for readyGate before starting the kernel
   - category: assertion/logic
   - error: AssertionError: expected +0 to be 1 // Object.is equality
160. `test/kernel-agent-message-skill.test.ts` — agent-message skill over the kernel host bridge > lists agents and sends without exposing a spoofable sender
   - category: assertion/logic
   - error: 
161. `test/kernel-agent-message-skill.test.ts` — agent-message skill over the kernel host bridge > emits successful broadcast receipts and leaves short errors in the result
   - category: assertion/logic
   - error: 
162. `test/kernel-agent-message-skill.test.ts` — agent-message skill over the kernel host bridge > rejects broadcast combined with role selectors before reaching the host
   - category: assertion/logic
   - error: 
163. `test/kernel-agent-message-skill.test.ts` — agent-message skill over the kernel host bridge > rejects a positional name target before reaching the host
   - category: assertion/logic
   - error: 
164. `test/kernel-agent-message-skill.test.ts` — agent-message skill over the kernel host bridge > does not expose a queueable delivery mode
   - category: assertion/logic
   - error: 
165. `test/kernel-agent-message-skill.test.ts` — agent-message skill over the kernel host bridge > captures sent messages from detached tasks after the cell is idle
   - category: assertion/logic
   - error: 
166. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > loads an on-disk image into the tool result as an ImageContent block
   - category: assertion/logic
   - error: 
167. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > compresses large attached images before storing them in the tool result
   - category: assertion/logic
   - error: 
168. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > reports when compressed animated images are flattened to their first frame
   - category: assertion/logic
   - error: 
169. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > uses a neutral background when compressing transparent images
   - category: assertion/logic
   - error: 
170. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > rejects oversized pixel counts before loading an image into context
   - category: assertion/logic
   - error: 
171. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > rejects undecodable images before emitting any attachment
   - category: assertion/logic
   - error: 
172. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > errors without emitting an attachment when the model is not vision-capable
   - category: assertion/logic
   - error: 
173. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > rejects a non-image file
   - category: assertion/logic
   - error: 
174. `test/kernel-attach-image-skill.test.ts` — attach-image skill over the kernel host bridge > fails the cell loudly when an emitted attachment exceeds the size cap
   - category: assertion/logic
   - error: 
175. `test/kernel-rlm-heartbeat-skill.test.ts` — RLM heartbeat skill over the kernel host bridge > round-trips create, list, update, and delete through a live kernel
   - category: assertion/logic
   - error: 
176. `test/kernel-rlm-heartbeat-skill.test.ts` — RLM heartbeat skill over the kernel host bridge > surfaces missing host handlers as Python exceptions
   - category: assertion/logic
   - error: 
177. `test/kernel-rlm-heartbeat-skill.test.ts` — RLM heartbeat skill over the kernel host bridge > rejects non-string delivery modes before calling the host
   - category: assertion/logic
   - error: 
178. `test/suite/regressions/4428-remove-legacy-pi-mono-tools.test.ts` — regression #4428: remove legacy pi-mono built-in tools > applies shell settings to ipython bash cells
   - category: EPERM/EACCES/filesystem
   - error: Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe'
179. `test/kernel-agent-observe-skill.test.ts` — agent-observe skill over the kernel host bridge > lists agents and reads bounded recent messages
   - category: timeout
   - error: Error: Test timed out in 30000ms.
180. `test/kernel-agent-observe-skill.test.ts` — agent-observe skill over the kernel host bridge > validates argument types before sending to the host
   - category: EPERM/EACCES/filesystem
   - error: Error: Failed to set up the Python kernel runtime. EPERM: operation not permitted, unlink 'C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe'
181. `test/kernel-bootstrap.test.ts` — kernel bootstrap > bootstraps a missing venv with uv, ipykernel, prime-agent-runtime, and default extra packages
   - category: timeout
   - error: Error: Test timed out in 30000ms.
182. `test/kernel-bootstrap.test.ts` — kernel bootstrap > routes bootstrap progress through the provided callback
   - category: timeout
   - error: Error: Test timed out in 30000ms.
183. `test/kernel-bootstrap.test.ts` — kernel bootstrap > installs Python skills into the bootstrapped venv
   - category: timeout
   - error: Error: Test timed out in 30000ms.
184. `test/kernel-bootstrap.test.ts` — kernel bootstrap > installs sibling Python skill dependencies with dependent editable packages
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
185. `test/kernel-bootstrap.test.ts` — kernel bootstrap > installs sibling Python skill dependencies when package and directory names differ
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
186. `test/kernel-bootstrap.test.ts` — kernel bootstrap > parses Python skill dependencies with extras
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
187. `test/kernel-bootstrap.test.ts` — kernel bootstrap > syncs a warm venv when a Python skill pyproject changes
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
188. `test/kernel-bootstrap.test.ts` — kernel bootstrap > continues when a Python skill editable install fails and retries it next startup
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
189. `test/kernel-bootstrap.test.ts` — kernel bootstrap > rebuilds a warm venv with legacy unhashed Python skill manifest entries
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
190. `test/kernel-bootstrap.test.ts` — kernel bootstrap > shares concurrent bootstrap work in one process
   - category: assertion/logic
   - error: AssertionError: expected [ …(2) ] to deeply equal [ …(2) ]
191. `test/kernel-bootstrap.test.ts` — kernel bootstrap > reuses a current warm venv without invoking uv
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
192. `test/kernel-bootstrap.test.ts` — kernel bootstrap > rebuilds a warm venv whose recorded runtime hash no longer matches local source
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
193. `test/kernel-bootstrap.test.ts` — kernel bootstrap > rebuilds a warm venv with a stale rlm runtime
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
194. `test/kernel-bootstrap.test.ts` — kernel bootstrap > rebuilds a broken venv
   - category: assertion/logic
   - error: AssertionError: expected 'C:\Users\assas\AppData\Local\Temp\pri…' to be 'C:\Users\assas\AppData\Local\Temp\pri…' // Object.is equality
195. `test/kernel-bootstrap.test.ts` — kernel bootstrap > uses PRIME_AGENT_KERNEL_PYTHON as an override contract
   - category: assertion/logic
   - error: AssertionError: promise rejected "Error: PRIME_AGENT_KERNEL_PYTHON points t…" instead of resolving
196. `test/kernel-bootstrap.test.ts` — kernel bootstrap > allows PRIME_AGENT_KERNEL_PYTHON missing Python skill imports
   - category: assertion/logic
   - error: AssertionError: promise rejected "Error: PRIME_AGENT_KERNEL_PYTHON points t…" instead of resolving
197. `test/kernel-bootstrap.test.ts` — kernel bootstrap > rejects PRIME_AGENT_KERNEL_PYTHON missing default extra packages
   - category: assertion/logic
   - error: AssertionError: expected [Function] to throw error matching /default Python packages \(yaml \(PyYA…/ but got 'PRIME_AGENT_KERNEL_PYTHON points to a…'
198. `test/kernel-startup.test.ts` — KernelManager startup > surfaces kernels that exit before resolving ports
   - category: EPERM/EACCES/filesystem
   - error: AssertionError: expected [Function] to throw error matching /Kernel exited before resolving ports[…/ but got 'Kernel exited before resolving ports.…'
199. `test/owned-session-worker-process.test.ts` — owned session worker processes > terminates the owned worker when its frontend is killed
   - category: timeout
   - error: AssertionError: expected false to be true // Object.is equality
200. `test/package-command-paths.test.ts` — package commands > uses the current package name when the update check omits packageName
   - category: assertion/logic
   - error: AssertionError: expected 1 to be undefined
201. `test/package-command-paths.test.ts` — package commands > installs the active package name from the update check during self-update
   - category: assertion/logic
   - error: AssertionError: expected 1 to be undefined
202. `test/package-command-paths.test.ts` — package commands > installs the Prime Agent tarball from the update manifest during self-update
   - category: assertion/logic
   - error: AssertionError: expected 1 to be undefined
203. `test/package-command-paths.test.ts` — package commands > fails self-update when renamed npm package installation fails
   - category: assertion/logic
   - error: AssertionError: expected '\u001b[31mPrime Agent has 3 busy sess…' to contain 'exited with code 23'
204. `test/package-manager.test.ts` — DefaultPackageManager > resolve > should resolve symlinked user and project resources once
   - category: assertion/logic
   - error: AssertionError: expected { extensions: 1, skills: 36, …(2) } to deeply equal { extensions: 1, skills: 1, …(2) }
205. `test/package-manager.test.ts` — DefaultPackageManager > source parsing > should emit progress events on install attempt
   - category: timeout
   - error: Error: Test timed out in 30000ms.
206. `test/package-self-update-daemon.test.ts` — self-update daemon restart > restarts the daemon only after the package update succeeds
   - category: assertion/logic
   - error: AssertionError: expected 438 to be 384 // Object.is equality
207. `test/refinement.test.ts` — harness refinement > atomically replaces harness state without leaving temporary files
   - category: assertion/logic
   - error: AssertionError: expected [ 'harness_state.json' ] to deeply equal [ Array(1) ]
208. `test/resource-loader.test.ts` — DefaultResourceLoader > reload > should load symlinked user and project extensions once
   - category: assertion/logic
   - error: AssertionError: expected [] to have a length of 1 but got +0
209. `test/resource-loader.test.ts` — DefaultResourceLoader > reload > should keep both extensions loaded when command names collide
   - category: assertion/logic
   - error: AssertionError: expected [] to have a length of 2 but got +0
210. `test/resource-loader.test.ts` — DefaultResourceLoader > extension conflict detection > should detect tool conflicts between extensions
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
211. `test/resource-loader.test.ts` — DefaultResourceLoader > extension conflict detection > should prefer explicit CLI extensions over discovered extensions when commands and tools conflict
   - category: assertion/logic
   - error: AssertionError: expected undefined to be 'C:\Users\assas\AppData\Local\Temp\rl-…' // Object.is equality
212. `test/rlm-ledger.test.ts` — rlm spawn ledger > replays spawn, rename, and delete records last-writer-wins
   - category: assertion/logic
   - error: AssertionError: expected 438 to be 384 // Object.is equality
213. `test/rlm-ledger.test.ts` — rlm spawn ledger > fails closed on byte and record bounds
   - category: timeout
   - error: Error: Test timed out in 30000ms.
214. `test/sdk-session-manager.test.ts` — createAgentSession session manager defaults > uses agentDir for the default persisted session path
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
215. `test/sdk-session-manager.test.ts` — createAgentSession session manager defaults > derives cwd from an explicit sessionManager when cwd is omitted
   - category: assertion/logic
   - error: AssertionError: expected 'You are a general purpose agent that …' to contain 'Working directory: C:\Users\assas\App…'
216. `test/session-manager-flush.test.ts` — SessionManager.flushNow > rewrites a cross-directory symlink target without replacing the alias
   - category: assertion/logic
   - error: AssertionError: expected 438 to be 416 // Object.is equality
217. `test/telemetry.test.ts` — telemetry identity and transport > creates a private stable installation ID
   - category: assertion/logic
   - error: AssertionError: expected 438 to be 384 // Object.is equality
218. `test/tools-manager.test.ts` — tools manager > accepts managed and PATH tools only when their version check succeeds
   - category: assertion/logic
   - error: AssertionError: expected null to be '\tmp\prime-agent-tools-manager-40136\…' // Object.is equality
219. `test/tools-manager.test.ts` — tools manager > validates a downloaded binary before reporting it available
   - category: assertion/logic
   - error: AssertionError: expected { status: 'unavailable', …(4) } to deeply equal { status: 'available', …(1) }
220. `test/tools.test.ts` — Coding Agent Tools > edit tool > should include EACCES for read-only files
   - category: EPERM/EACCES/filesystem
   - error: AssertionError: expected [Function] to throw error including 'Could not edit file: C:\Users\assas\A…' but got 'Could not edit file: C:\Users\assas\A…'
221. `test/tools.test.ts` — Coding Agent Tools > edit tool > should include EACCES in diff preview for unreadable files
   - category: EPERM/EACCES/filesystem
   - error: AssertionError: expected { diff: '-1 hello\n+1 world', …(1) } to deeply equal { Object (error) }
222. `test/suite/acp-features.test.ts` — ACP mode preserves prime-agent features > surfaces real goal state transitions to the ACP client
   - category: timeout
   - error: Error: timed out waiting for the expected ACP updates
223. `test/suite/agent-session-autonomous.test.ts` — AgentSession autonomous mode > runs autonomous gates before applying usage limits
   - category: assertion/logic
   - error: AssertionError: expected { shouldContinue: false, …(1) } to match object { shouldContinue: false, …(1) }
224. `test/suite/agent-session-autonomous.test.ts` — AgentSession autonomous mode > lets passing autonomous gates complete the run under verifier control
   - category: assertion/logic
   - error: AssertionError: expected [ 'make the change', …(1) ] to deeply equal [ 'make the change' ]
225. `test/suite/agent-session-autonomous.test.ts` — AgentSession autonomous mode > advances retry budget without rerunning a failed autonomous gate until the workspace changes
   - category: EPERM/EACCES/filesystem
   - error: Error: ENOENT: no such file or directory, open 'C:\Users\assas\.prime-074-compat\throwaway-073\packages\coding-agent\.tmp-autonomous-gate-1787289948042-38p7wj354wf\verification\public_feedback_scores.jsonl'
226. `test/suite/agent-session-autonomous.test.ts` — AgentSession autonomous mode > reruns a failed autonomous gate when untracked file contents change
   - category: assertion/logic
   - error: AssertionError: expected { role: 'user', …(2) } to be undefined
227. `test/suite/agent-session-autonomous.test.ts` — AgentSession autonomous mode > bounds captured autonomous gate output
   - category: assertion/logic
   - error: AssertionError: expected '\'C:\Program\' is not recognized as a…' to contain '... [truncated]'
228. `test/suite/agent-session-autonomous.test.ts` — AgentSession autonomous mode > terminates the autonomous gate process tree when the timeout expires
   - category: EPERM/EACCES/filesystem
   - error: Error: ENOENT: no such file or directory, open 'C:\Users\assas\.prime-074-compat\throwaway-073\packages\coding-agent\.tmp-autonomous-process-tree-1787289990502-ff2zllkeo9\descendant.pid'
229. `test/suite/agent-session-autonomous.test.ts` — AgentSession autonomous mode > terminates an autonomous gate without mutating retry state when the session is aborted
   - category: timeout
   - error: Error: Timed out waiting for process ID file: C:\Users\assas\AppData\Local\Temp\pi-suite-1787289999627-yw7wao5952i\gate.pid
230. `test/suite/agent-session-autonomous.test.ts` — AgentSession autonomous mode > records the post-failure worktree snapshot for gate rerun suppression
   - category: EPERM/EACCES/filesystem
   - error: Error: ENOENT: no such file or directory, open 'C:\Users\assas\.prime-074-compat\throwaway-073\packages\coding-agent\.tmp-autonomous-post-snapshot-1787290016833-bvmakq0cevi\generated.txt'
231. `test/suite/agent-session-compaction-continuation.test.ts` — compaction continuation > e2e: an active goal keeps continuing after a successful threshold compaction
   - category: assertion/logic
   - error: AssertionError: expected 3 to be +0 // Object.is equality
232. `test/suite/agent-session-compaction.test.ts` — AgentSession compaction characterization > waits for threshold-compaction autonomous continuations before finishing prompt
   - category: assertion/logic
   - error: AssertionError: expected +0 to be 1 // Object.is equality
233. `test/suite/agent-session-goal.test.ts` — initial goal seeding from config > seeds an active goal from initialGoal config on a fresh top-level session
   - category: assertion/logic
   - error: AssertionError: expected { active: false, status: 'idle', …(3) } to match object { Object (active, status, ...) }
234. `test/suite/agent-session-goal.test.ts` — initial goal seeding from config > does not reseed after goal is cleared (idempotent restart)
   - category: assertion/logic
   - error: AssertionError: expected 'idle' to be 'active' // Object.is equality
235. `test/suite/agent-session-goal.test.ts` — initial goal seeding from config > does not reseed after goal is completed (idempotent restart)
   - category: assertion/logic
   - error: AssertionError: expected 'idle' to be 'active' // Object.is equality
236. `test/suite/agent-session-goal.test.ts` — initial goal seeding from config > does not reseed when branch has messages (idempotent restart after use)
   - category: assertion/logic
   - error: AssertionError: expected 'idle' to be 'active' // Object.is equality
237. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine 'review runs after the configured turn…'
   - category: assertion/logic
   - error: 
238. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine 'falls back to turn-interval review wh…'
   - category: assertion/logic
   - error: 
239. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine 'queued follow-up messages do not make…'
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called with arguments: [ …(2) ]
240. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine 'compact hook does not require the tur…'
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called with arguments: [ { reason: 'compact', …(1) }, …(1) ]
241. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine 'declined compact review preserves an …'
   - category: assertion/logic
   - error: AssertionError: expected "_scheduleAutoRefine" to be called with arguments: [ 'turn_interval' ]
242. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine compact hook 'waits for planned post-compaction con…'
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
243. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine compact hook 'waits until the scheduled post-compac…'
   - category: assertion/logic
   - error: 
244. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine compact hook 'runs immediately when no post-compact…'
   - category: assertion/logic
   - error: AssertionError: expected "_scheduleAutoRefine" to be called with arguments: [ 'compact' ]
245. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > runs a turn-interval review after a concurrent compact review declines
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
246. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine pending review uses the in-progress guard and catches refine failures
   - category: assertion/logic
   - error: AssertionError: expected "refine" to be called with arguments: [ ObjectContaining{…} ]
247. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > keeps the turn counter and stamps the cooldown when an approved immediate refine fails
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called with arguments: [ …(2) ]
248. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > does not refine when a review resolves after the session is disposed
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times
249. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > stamps the cooldown when the auto-refine review fails
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times
250. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine pending review respects the cooldown
   - category: assertion/logic
   - error: AssertionError: expected undefined to be defined
251. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > preserves compact auto-refine pending state when no model is selected
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
252. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine review obeys the cooldown and preserves a 'turn_interval' checkpoint
   - category: assertion/logic
   - error: 
253. `test/suite/agent-session-queue.test.ts` — AgentSession queue characterization > auto-refine review obeys the cooldown and preserves a 'compact' checkpoint
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
254. `test/suite/agent-session-queue.test.ts` — AgentSession scheduler scenarios > S6: auto-refine reviews after real turns, defers while busy, and drops reviews on navigation
   - category: assertion/logic
   - error: AssertionError: expected [] to include 'auto_one'
255. `test/suite/agent-session-refine-skill.test.ts` — AgentSession refine skill host requests > registers refine.run and refine.status handlers when auto-refine is allowed
   - category: assertion/logic
   - error: AssertionError: expected [ 'rlm.run', 'rlm.find_models', …(8) ] to deeply equal ArrayContaining{…}
256. `test/suite/agent-session-runtime.test.ts` — AgentSessionRuntime characterization > copies depth across new-session parent reference edges
   - category: assertion/logic
   - error: AssertionError: expected { type: 'session', version: 3, …(6) } to match object { …(2) }
257. `test/suite/agent-session-runtime.test.ts` — AgentSessionRuntime characterization > releases a failed child run from the inline runtime host
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
258. `test/suite/agent-session-serialized-refine.test.ts` — Serialized auto-refine checkpoint > refines exactly once when >25 tool turns run in one loop
   - category: assertion/logic
   - error: AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times
259. `test/suite/agent-session-serialized-refine.test.ts` — Serialized auto-refine checkpoint > max concurrent primary/refinement model requests is one in serialized mode
   - category: timeout
   - error: AssertionError: expected false to be true // Object.is equality
260. `test/suite/agent-session-serialized-refine.test.ts` — Serialized auto-refine checkpoint > prompt/state update visible on resumed turn after serialized refine
   - category: assertion/logic
   - error: AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times
261. `test/suite/agent-session-serialized-refine.test.ts` — Serialized auto-refine checkpoint > final agent_end pending refine completes before dispose
   - category: assertion/logic
   - error: AssertionError: expected "_applyRefine" to be called at least once
262. `test/suite/agent-session-serialized-refine.test.ts` — Serialized auto-refine checkpoint > never deadlocks: serialized checkpoint does not call waitForIdle or _maybeAutoRefine
   - category: assertion/logic
   - error: AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times
263. `test/suite/agent-session-serialized-refine.test.ts` — Serialized autonomous continuation > autonomous tool loop continues past serialized refinement boundary with no deadlock
   - category: assertion/logic
   - error: AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times
264. `test/suite/agent-session-serialized-refine.test.ts` — Serialized background planning during tools > planning overlaps a deferred tool but next model turn waits for plan+apply
   - category: timeout
   - error: AssertionError: expected false to be true // Object.is equality
265. `test/suite/agent-session-serialized-refine.test.ts` — Serialized background planning during tools > lets refine.run supersede an interval plan that ignores abort
   - category: timeout
   - error: AssertionError: expected +0 to be 1 // Object.is equality
266. `test/suite/agent-session-serialized-refine.test.ts` — Serialized background planning during tools > max concurrent model calls is one: planning does not start another model request
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times
267. `test/suite/agent-session-serialized-refine.test.ts` — PR #503 model persistence regression > model is preserved after serialized refine checkpoint
   - category: assertion/logic
   - error: AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times
268. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > failure result stamps cooldown and does NOT retry synchronously
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times
269. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > serialized failure does not schedule interactive auto-refine at agent_end
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times
270. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > interval bg plan failure does not retry synchronously
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times
271. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > interval background plan derives instructions from review, not prepopulated
   - category: assertion/logic
   - error: AssertionError: expected undefined to be defined
272. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > disposal applies ready background plan before teardown
   - category: assertion/logic
   - error: AssertionError: expected "_applyRefine" to be called 1 times, but got 0 times
273. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > services a compaction-triggered refine at the next serialized boundary
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
274. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > defers serialized compaction refinement even when no continuation was scheduled
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
275. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > defers manual compaction refinement to the serialized checkpoint
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
276. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > preserves a serialized compaction trigger while cooldown is active
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
277. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > clears a serialized compaction trigger when disposal occurs during cooldown
   - category: assertion/logic
   - error: AssertionError: expected true to be false // Object.is equality
278. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > continues to the interval drain after a compact trigger hits cooldown
   - category: assertion/logic
   - error: AssertionError: expected true to be false // Object.is equality
279. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > falls back to an interval review when compact-triggered refinement is disabled
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called with arguments: [ ObjectContaining{…}, …(1) ]
280. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > clears a compact trigger after a review decides no refinement is needed
   - category: assertion/logic
   - error: AssertionError: expected "vi.fn()" to be called with arguments: [ ObjectContaining{…}, …(1) ]
281. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine review-fix regressions > does not let a compact review failure block disposal
   - category: assertion/logic
   - error: AssertionError: expected true to be false // Object.is equality
282. `test/suite/agent-session-serialized-refine.test.ts` — Serialized refine event-ordering integration > real message_end/turn_end ordering: threshold planning starts and applies before next model turn
   - category: assertion/logic
   - error: AssertionError: expected "_applyRefine" to be called at least once
283. `test/suite/agent-session-serialized-refine.test.ts` — P0 concurrency regressions > steering waits for interval refine and threshold compaction boundaries
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
284. `test/suite/agent-session-serialized-refine.test.ts` — P0 concurrency regressions > branch navigation with in-flight serialized plan: aborts signal, no apply
   - category: timeout
   - error: AssertionError: expected undefined to be defined
285. `test/suite/agent-session-serialized-refine.test.ts` — P0 concurrency regressions > drains a due interactive auto-refine without waiting for agent idle
   - category: assertion/logic
   - error: AssertionError: expected "_maybeAutoRefine" to be called with arguments: [ 'turn_interval' ]
286. `test/suite/daemon-serialized-refine-process.test.ts` — Real-process serializedRefine — JSON mode > daemon supervisor scrubs inherited worker env, checkpoint applies refine_complete before agent_end
   - category: timeout
   - error: AssertionError: expected { code: 1, signal: null, …(2) } to match object { code: +0, signal: null }
287. `test/suite/daemon-serialized-refine.test.ts` — Daemon-backed serializedRefine propagation > daemon session with serializedRefine=true crosses threshold and applies refine
   - category: assertion/logic
   - error: AssertionError: expected 2 to be +0 // Object.is equality
288. `test/suite/serialized-refine-config-integration.test.ts` — Serialized refine config integration (unit) > real autonomous loop crosses threshold and resumes with serialized refine
   - category: assertion/logic
   - error: AssertionError: expected 2 to be +0 // Object.is equality
289. `test/suite/regressions/2791-fswatch-error-crash.test.ts` — issue #2791 fs.watch error event crashes process > process should survive an error event on the theme FSWatcher
   - category: assertion/logic
   - error: AssertionError: Child crashed (exit 1). stderr: : expected 1 to be +0 // Object.is equality
290. `test/suite/regressions/3885-subagent-runtime-host.test.ts` — ENG-3885 subagent runtime host > creates explicitly modeled RLM children as tracked AgentSessionRuntime instances
   - category: timeout
   - error: Error: Timed out waiting for condition
291. `test/suite/regressions/3885-subagent-runtime-host.test.ts` — ENG-3885 subagent runtime host > preserves initial model and thinking entries for inline RLM children
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
292. `test/suite/regressions/4257-update-restart-resume.test.ts` — issue #4257 update restart resume > materializes queued in-memory drafts before update restart
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
293. `test/suite/regressions/4257-update-restart-resume.test.ts` — issue #4257 update restart resume > materializes busy in-memory drafts before update restart
   - category: assertion/logic
   - error: AssertionError: expected false to be true // Object.is equality
294. `test/suite/regressions/4600-supervisor-singleton.test.ts` — ENG-4600 daemon supervisor ownership > unwinds real pre-bind and post-bind startup failures before retry
   - category: EPERM/EACCES/filesystem
   - error: Error: ENOENT: no such file or directory, open '\\.\pipe\prime-agent-eng-4600-31488-1787290038479'
295. `test/suite/regressions/4603-worker-recovery.test.ts` — ENG-4603 worker recovery convergence > serializes shutdown admission and reclaims an unrenewed live lease
   - category: EPERM/EACCES/filesystem
   - error: Error: EPERM: operation not permitted, link 'C:\Program Files\nodejs\node.exe' -> 'C:\Users\assas\AppData\Local\Temp\pi-suite-1787289925501-nlrz3a2fo0r\prime-agent'
296. `test/suite/regressions/4606-update-restart-coordinator.test.ts` — ENG-4606 update restart coordinator > keeps a relative agent directory stable across coordinator cwd changes
   - category: timeout
   - error: Error: Test timed out in 30000ms.
297. `test/suite/regressions/4606-update-restart-coordinator.test.ts` — ENG-4606 update restart coordinator > resolves a relative custom socket before changing coordinator cwd
   - category: assertion/logic
   - error: AssertionError: expected { version: 1, …(9) } to match object { phase: 'skipped', …(1) }
298. `test/suite/regressions/4620-fast-mode-child-agents.test.ts` — ENG-4620 fast mode child agents > passes and persists fast mode for inline RLM children
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
299. `test/suite/regressions/4620-fast-mode-settings.test.ts` — ENG-4620 fast mode settings > returns the effective service tier when cycling models
   - category: assertion/logic
   - error: AssertionError: expected 'deepseek-v4-flash' to be 'gpt-5.4' // Object.is equality
300. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > searches a bounded authenticated catalog without advertising it
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
301. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > omits providers whose credentials are marked expired
   - category: assertion/logic
   - error: AssertionError: expected { models: [ { …(4) }, { …(4) } ] } to deeply equal { models: [] }
302. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > limits ChatGPT discovery and execution to the account model catalog
   - category: assertion/logic
   - error: AssertionError: expected [ 'deepseek/deepseek-v4-flash', …(2) ] to deeply equal [ 'openai-codex/parent-model' ]
303. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > does not warn when an unavailable selector is already the parent model
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
304. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > does not start a child after its parent is disposed during preflight
   - category: assertion/logic
   - error: AssertionError: expected "getApiKeyAndHeaders" to be called once, but got 0 times
305. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > reserves an explicit child name while model validation is pending
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: AssertionError: expected [Function] to throw error including 'Agent name "shared-reviewer" is unava…' but got 'RLM recursion depth limit reached (RL…'
306. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > runs and retains a child on an explicitly selected model
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
307. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > inherits the parent model when no override is supplied
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
308. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > accepts a selected model authenticated by headers
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)
309. `test/suite/regressions/4649-subagent-model-selection.test.ts` — ENG-4649 subagent model selection > rejects unavailable requested models at admission without fallback
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: AssertionError: expected [Function] to throw error including 'is unavailable, unauthenticated, or e…' but got 'RLM recursion depth limit reached (RL…'
310. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > runs host-owned autonomous gate retries through the shared completion loop
   - category: assertion/logic
   - error: AssertionError: expected [ …(2) ] to have a length of 1 but got 2
311. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > launches real daemon workers for every migrated client surface
   - category: timeout
   - error: Error: CLI timed out
312. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > keeps the rollback frontend fully off the daemon path
   - category: timeout
   - error: Error: CLI timed out
313. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > loads headless runtime services only in the worker
   - category: timeout
   - error: Error: CLI timed out
314. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > drains accepted RPC commands before EOF releases the connection
   - category: assertion/logic
   - error: AssertionError: expected '(node:50584) Warning: The \'NO_COLOR\…' to be '' // Object.is equality
315. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > drains accepted RPC prompt work before EOF releases the connection
   - category: assertion/logic
   - error: AssertionError: expected '(node:17952) Warning: The \'NO_COLOR\…' to be '' // Object.is equality
316. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > drains accepted daemon RPC prompt work before EOF
   - category: timeout
   - error: Error: CLI timed out
317. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > drains an unterminated final RPC command before EOF
   - category: assertion/logic
   - error: AssertionError: expected '(node:56684) Warning: The \'NO_COLOR\…' to be '' // Object.is equality
318. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > returns a structured error for scalar JSON input
   - category: assertion/logic
   - error: AssertionError: expected '(node:8068) Warning: The \'NO_COLOR\'…' to be '' // Object.is equality
319. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > cancels pending extension dialogs on RPC EOF
   - category: assertion/logic
   - error: AssertionError: expected '(node:56304) Warning: The \'NO_COLOR\…' to be '' // Object.is equality
320. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > preserves prompt acknowledgements before events and repeated prompts
   - category: assertion/logic
   - error: AssertionError: expected '(node:50260) Warning: The \'NO_COLOR\…' to be '' // Object.is equality
321. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > preserves RPC trimming and omitted-value encoding
   - category: assertion/logic
   - error: AssertionError: expected '(node:52500) Warning: The \'NO_COLOR\…' to be '' // Object.is equality
322. `test/suite/regressions/4685-daemon-client-modes.test.ts` — ENG-4685 daemon-backed client modes > exposes daemon schedules, heartbeats, messaging, and observation
   - category: assertion/logic
   - error: AssertionError: expected '(node:30708) Warning: The \'NO_COLOR\…' to be '' // Object.is equality
323. `test/suite/regressions/617-subagent-terminal-agent-message.test.ts` — #617 subagent terminal agent messages > falls back to an injected notice when the agent message cannot be delivered
   - category: env-config (RLM_MAX_DEPTH=1 depth limit)
   - error: Error: RLM recursion depth limit reached (RLM_DEPTH=1, RLM_MAX_DEPTH=1)

## Log pointer

Full raw stdout+stderr (9096 lines, includes every failure's full stack trace and the 14 unhandled errors section):
`C:\Users\assas\.prime-eperm-repro\logs\ab-073-vitest-full.log`

## What was NOT done

- Failed tests were not retried.
- No test or source file was edited to make anything pass.
- No root-cause diagnosis beyond what the printed error text itself shows.
- No subagents were spawned (RLM_MAX_DEPTH=1 on this daemon).