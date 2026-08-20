# 00 — Pilot 5 Evidence Freeze (Prime 0.7.4 Upgrade Qualification)

## Frozen references

- Second Brain branch: `brain/v1-rc4-cvm-closure-repair`
- RC4 repair SHA (candidate code, authorized): `98f147f9ad8cc454fbb1e6c59fe992e9f98c7c72`
- Pilot 5 evidence SHA (frozen, evidence-only commit on top of the repair SHA): `31c4b03fcd6c5aadfffdc6864134dd822ed14352`
- Parent of the evidence commit: `98f147f9ad8cc454fbb1e6c59fe992e9f98c7c72` (exact match to the
  RC4 repair SHA — the evidence commit is the immediate child, no other
  commits in between)
- Tree state at freeze time: clean, local == origin (`git fetch` +
  `git rev-parse HEAD` == `git rev-parse origin/brain/v1-rc4-cvm-closure-repair`
  == `31c4b03fcd6c5aadfffdc6864134dd822ed14352`)

## Confirmed: Pilot 5 evidence commit contains evidence/report changes ONLY

`git diff --stat 98f147f9..31c4b03` — 4 files changed, all under
`outputs/reports/rc4/`:

```
outputs/reports/rc4/15-real-prime-pilot-5.md
outputs/reports/rc4/raw/manifest.jsonl
outputs/reports/rc4/raw/pilot-05/pilot-05-evidence-bundle.json
outputs/reports/rc4/raw/pilot-05/pilot-workload.diff
```

No `brainstem/prime-extension/` or `src/second_brain/` files appear in this
diff — **no runtime implementation was altered during Pilot 5's evidence
capture**. This confirms `98f147f9ad8cc454fbb1e6c59fe992e9f98c7c72` remains
the exact, unmodified runtime code that Pilot 5 actually exercised.

## Prime 0.7.3 version string (this machine, at freeze time)

- `PRIME_AGENT_BUILD_ID` env var (daemon): `v0.7.3-dirty`
- Prime Agent repo (`C:\Tools\prime-agent`): git checkout, remote
  `origin = https://github.com/PrimeIntellect-ai/prime-agent.git`
- Prime repo HEAD at freeze time: `61131b2d195ba7a67a4ce8ac60bb10cecae07b67`
- Prime repo branch: (detached / local working branch — see
  `01-prime-073-known-good-baseline.md` for the exact rollback procedure)
- `package.json` / `packages/coding-agent/package.json` version field: `0.7.3`
- Local working-tree modifications present (the two known Windows patches):
  `packages/coding-agent/src/core/kernel/bootstrap.ts`,
  `packages/coding-agent/src/core/session-lease.ts`
  (see `02-local-patch-disposition.md` for exact hunks and disposition)
- Confirmed real, resolvable `v0.7.4` tag exists on `origin` (fetched):
  `git tag -l "*0.7.4*"` → `v0.7.4`. This satisfies the "exact 0.7.4 release
  must be verifiable" gate before any upgrade work proceeds.

## Second Brain Prime extension version/hash (at freeze time)

Combined sha256 over all 13 `.ts` files in
`brainstem/prime-extension/src/` (sorted filename order, hash-of-hashes):

```
5c44759771add150628ca72a095c7e08f892626353962dac21d91f307a360e2d
```

Per-file hashes recorded in the sanitized freeze bundle
(`outputs/reports/rc4/prime-074/raw/00-freeze-hashes.json`).

**Confirmed the globally installed extension copy
(`C:\Users\assas\.prime\agent\extensions\second-brain\`) matches this
source hash EXACTLY** — Prime is loading the frozen RC4 candidate code, not
stale code, at freeze time.

## Pilot 5 real session ID

`01a02028-9f7c-758b-b275-fe8805cc22a6` (RLM child `sub-bbf19333`) — see
`outputs/reports/rc4/15-real-prime-pilot-5.md` and
`outputs/reports/rc4/raw/pilot-05/pilot-05-evidence-bundle.json` for the
full evidence.

## Raw evidence hashes (Pilot 5, already recorded, re-confirmed here)

- Prime transcript sha256:
  `2ced25cc7f92b61407dbdb395918ad019d65c6df5e5d6ded96c20b31269e8cee`
  (433,106 B — local only)

  Correction: see the pilot-05 evidence bundle
  (`raw_files_retained_local_only`) for the exact byte counts/hashes of all
  four raw artifacts (transcript, telemetry, ledger, rlm-subagent.json);
  reproduced verbatim here for convenience:
  - transcript: 418,712 B,
    sha256 `2ced25cc7f92b61407dbdb395918ad019d65c6df5e5d6ded96c20b31269e8cee`
  - telemetry: 493,540 B,
    sha256 `0b7b2ce9feaf95489e8b6f46f88fb8c5cb1e12757753e5a13dcca8712b6abd90`
  - ledger.sqlite: 172,032 B,
    sha256 `85449b5c4d63980bbed788a19441b3d615093416db537ae0fe92ef5cee9e8524`
  - rlm-subagent.json: 3,816 B,
    sha256 `28318fe2566976ae5d341bad8c226530bbe5d8c7529a40981596728d5ca61985`

## Sanitized evidence path

`outputs/reports/rc4/raw/pilot-05/pilot-05-evidence-bundle.json` (committed
at `31c4b03fcd6c5aadfffdc6864134dd822ed14352`).

## Freeze verdict

Pilot 5 evidence tip is unambiguously established, verified evidence-only,
and pushed. `98f147f9ad8cc454fbb1e6c59fe992e9f98c7c72` is confirmed as the
exact runtime candidate code Pilot 5 exercised, still matching the
currently-installed global extension byte-for-byte. Proceeding to
Section 2 (preserve the 0.7.3 rollback baseline).
