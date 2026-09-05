# Independent offline closeout

- Pyright: 85 -> 0 errors;195 files analyzed. No blanket suppressions. Two new reachable-boundary regressions fail against baseline functions (TypeError for non-iterable corroboration; ORPHAN_TASK instead of PROTOCOL_ERROR for missing task identity) and pass after repair.
- Full Python:1827 passed,464.32s. Focused governor/origin/Hermes:119 passed. Final type/semantic-policy confirmation:25 passed. Worker durability + Python installer:32 passed.
- Ruff:434 baseline ->430 findings;0 newly introduced normalized findings. Existing lint debt remains; not a clean repository-wide lint claim.
- Doctor:19/19,0warnings after explicitly matching SECOND_BRAIN_HOME to worktree. Initial mismatch was invocation environment, not repaired source.
- Pester installer/rollback:18/18 against temporary targets. Initial unsupported -Show invocation and global ErrorActionPreference=Stop attempt are retained as invalid/failed harness attempts, superseded by supported default-Continue execution with explicit result-count/failure checks. No default installation occurred.

## Governor component evidence

165 real session ledgers;329 session directories. Same root returned HARD/579890/400000 before and after. Empty home honestly returns ACCOUNTING_UNAVAILABLE with used=null.

| Component | Before median ms | After median ms |
|---|---:|---:|
| Python startup |44.73|42.74|
| Empty-home check |0.79|0.66|
| Telemetry lookup/parse |1.87|1.54|
| Directory enumeration |0.36|0.29|
| Serial SQLite open/query/close control |913.01|932.81|
| Direct populated check_budget |933.66|141.44|
| Python CLI |1256.77|323.22|
| Actual TS-to-Python bridge |not measured before|323.01|

Dominant cost was SQLite query I/O, not startup or telemetry. Alternating5-sample experiment:serial758.65ms,4 readers205.73ms,8 readers125.87ms. Repair uses stdlib ThreadPoolExecutor(max_workers=8), one read-only connection per ledger, closed within its owning thread. Identity validation/dedup remain serialized in sorted input order; exceptions preserve ACCOUNTING_UNAVAILABLE/fail-open. No retention, ancestry, ledger schema, cap, telemetry identity or immutable-read shortcut changed. No persistent cache/index added. Direct latency improved84.9%; final bridge maximum465.86ms remains below existing3000ms timeout. These are local measurements, not provider/economics qualification.

## Runtime restrictions

No provider calls;no default deployment;no Gate22/23;no tag. Existing 5-minute ordering evidence remains historical and authoritative for snapshot-only observers.
