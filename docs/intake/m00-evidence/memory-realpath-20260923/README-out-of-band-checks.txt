Out-of-band checks for memory-realpath-20260923
===============================================

These two checks were run by hand (read-only) alongside the probe run. They are
NOT produced by `scripts/native_noninterference_probe.py`; the payload and the
two `.jsonl` streams beside this file are. Recorded here because the payload's
`canonical_home_untouched` field cannot interpret itself.

Interpreter for every command below (absolute path, cleaned env):
  env -u PYTHONHOME -u PYTHONPATH \
    C:/Users/assas/Documents/The-Second-Brain/.worktrees/m00.3-producer-guard/.venv/Scripts/python.exe

The canonical home resolves (SECOND_BRAIN_HOME, then the packaged default) to
C:\Users\assas\Documents\The-Second-Brain -- a live checkout that other agent
sessions on this host also write. A read-only snapshot is:

  python -c "import time;from pathlib import Path;h=Path(r'C:\Users\assas\Documents\The-Second-Brain');s=(h/'db/brain.sqlite').stat();print(time.strftime('%H:%M:%S',time.localtime(s.st_mtime_ns/1e9)),s.st_size)"

A. Competing-writer measurement (no probe process involved)
----------------------------------------------------------
The canonical db is written by ambient activity whether or not this probe runs,
so a mtime delta across a probe run window is not attributable to the probe.

  22:05:01  db mtime at the first memory-check run's "before" snapshot
  22:06:01  db mtime observed during that run window (changed, size same)
  22:06:48  db mtime 22:06:01  <- probe finished ~22:06:15, no probe running
  22:07:06  db mtime 22:07:06  <- changed with NO probe running (T0 -> T1)
  22:07:06  db mtime at run 2's "before" snapshot
  22:07:06  db mtime at run 2's "after" snapshot  -> payload untouched=True
  22:09:14  db mtime 22:09:14  <- changed again ~1.5 min after run 2 ended,
            with no probe running (T2)

Size is 5017600 bytes throughout; there is no `db/brain.sqlite-wal` on this
host, so the mtime moves without a size change. Both directions are recorded:
one probe window in which the canonical db did not move (run 2), and two
intervals in which it moved while no probe process existed (T0->T1, T2).

Isolation is structural, not inferred: every arm ran with
SECOND_BRAIN_HOME=<its own disposable temp home> (payload field
`second_brain_home_env`) and nothing in the arms' argv/env names the canonical
home.

B. Replay of the archived streams through the current extractor
--------------------------------------------------------------
The payload was written before the child-delivery observation was tightened from
"any toolResult exists" to the host's own `<task-result>` envelope. Both
archived streams were re-scored with the current module to confirm the recorded
observation values are reproducible rather than artefacts of the coarser rule:

  import importlib.util, json, pathlib
  # load scripts/native_noninterference_probe.py from the candidate worktree
  # summarize_arm(<archived stream>.read_text(), token=<arm token>)

  memory_on : task_result_records={'unique': 1, 'roles': ['toolResult']}
              in_child_result=False  stream_hits=34
              injected_context_records=['brain.autoinject.packet']
  memory_off: task_result_records={'unique': 1, 'roles': ['toolResult']}
              in_child_result=False  stream_hits=0
  replayed verdicts: N1..N5 all true (same as the payload)
  replayed observation: delivered=True, child_quoted_token=False

So the payload's `observations` values hold under the tightened rule.

Limits of these checks
----------------------
- Run 1 (a live memory-check run whose payload was superseded by run 2 after the
  extractor fix; same prompt, model, arms) reported the same five verdicts true
  and a child that DID quote the token. Its streams are not archived here, so
  the child-context observation should be read as run-to-run variable, not as a
  fixed property. The run-1 output is visible in this worker's transcript.
- Neither check proves anything about a state the probe never touched: they only
  show that the canonical db has writers other than this probe, and that no arm
  process had it in SECOND_BRAIN_HOME.

C. Known defect in this payload's `brain_delivery` diagnostics
-------------------------------------------------------------
`brain_delivery.outcome_project_ids`, `outcome_project_resolutions` and
`delivery_ids` in `../memory-realpath-20260923.json` were produced by a reader
that looked up snake_case keys (`project_id`, `project_resolution`,
`delivery_id`) in the extension's persisted emit cache, which serializes the
camelCase TS objects `PersistedEmitEntry` / `AutoInjectShadowOutcome`
(`brainstem/prime-extension/src/autoinject.ts`). They therefore render as
`["None"]`, `["None"]` and `[]` even though the cache did carry real values.

No verdict depends on those fields. The real packet project id is in the host
stream itself: the injected `brain.autoinject.packet` record in
`memory_on.jsonl` begins `project: memprobe-temp`. The reader was corrected after
the run, together with a `--self-test` guard (`self_test_delivery_cache`) that
pins the persisted shape so the same silent degradation cannot recur; the payload
was not regenerated because that would have exceeded the two-live-runs-per-arm
budget. `decisions` and `reasons` in the same object were unaffected (they use
their real key names): the payload reads `["INJECT", "NO_INJECTION"]` with
reasons `["NO_RELEVANT_MEMORY", "None"]` (the `"None"` is this reader's
stringified null for the INJECT entry's absent reason). So this run's home served
one injecting session and one non-injecting second session — consistent with the
parent receiving the packet and the child not.

