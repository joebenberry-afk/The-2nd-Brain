# Phase 8-10 — New Build Fingerprint (post-repair)

Computed via `second_brain.build_identity.describe()` (same function
`brainctl doctor`'s "build identity" check and `RELEASE_DECISION.md` use),
run against this worktree immediately after both repair commits, working
tree clean:

```json
{
  "package_version": "2.0.0-rc.1",
  "git_sha": "2d3901636e09ef57059e41bc46e162c93899428a",
  "dirty": false,
  "db_schema_version": 21,
  "adapter_build_fingerprint": "100575fea2a92d55fe948a41f6cd67960d5626927c14eaaf0bf5d9d511cb5335",
  "qualification_baseline_sha": "4af64affdf4f1ec07b9483b67f440394d2853b32",
  "qualification_baseline_current": false
}
```

## Comparison to the prior HOLD candidate

| | Prior HOLD candidate (`RELEASE_DECISION.md`) | This repair (post-fix) |
|---|---|---|
| Branch | `brain/v2-omp-qualification` | `brain/v2-omp-final-p1-repair` |
| SHA | `86585e114115bc43bf932145e716f2ed4d3dd30e` | `2d3901636e09ef57059e41bc46e162c93899428a` |
| Adapter build fingerprint | `56b61076903f681215426ae38d6ff47225739283bff731d85db1c71e25d81f68` | `100575fea2a92d55fe948a41f6cd67960d5626927c14eaaf0bf5d9d511cb5335` |

The fingerprint changed, as expected: it is a SHA-256 over every
`brainstem/prime-extension/{src,types}` file's own SHA-256, sorted by
relative path (`adapter_build_fingerprint()`), and this repair changed
`src/index.ts` and `types/prime.d.ts` (`fix(prime-extension)` commit
`a9ff745`). `qualification_baseline_current` is `false` in both cases —
expected, since neither commit is the qualification baseline SHA
(`4af64affdf4f1ec07b9483b67f440394d2853b32`) itself; both are ahead of it on
a repair branch.

`db_schema_version` (`21`) and `qualification_baseline_sha` are unchanged —
this repair touches no database schema and no baseline-SHA constant.
