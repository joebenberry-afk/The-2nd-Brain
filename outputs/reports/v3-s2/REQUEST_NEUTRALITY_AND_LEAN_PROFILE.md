# V3 S2 — request-neutral evidence capture and the shipped Lean profile

Date: 2026-09-24. Branch `brain/v3-s2` in `.worktrees/v3-s1`. Scope: S2 request-neutrality
evidence (PERF-01/RET-05 measurement substrate) and the candidate's Lean advisory shipping
default. Nothing is installed, reloaded, pushed or deployed; the canonical home
(`C:/Users/assas/Documents/The-Second-Brain`) is read-only in this work (SQLite backup for the
corpus snapshot, plus reads of its config/frontier records).

## 1. Lean advisory: shipped default is now `off`

The renderer decides Lean injection from `<home>/config/skills.toml` `[lean] eval`
(`SECOND_BRAIN_LEAN` overrides). Two files were changed, neither of them the canonical home's
config and neither of them the live install:

| File | Before | After |
|---|---|---|
| `config/skills.toml` (this branch's deployable home config, sha256 `de159f94b154cb97…` after the change) | `eval = "advisory"` | `eval = "off"` |
| `src/second_brain/defaults/config/skills.toml` (seed copied by `brainctl init` into a new home, sha256 `c1f173c17970532a…`) | no `[lean]` section (=> inert) | `[lean] eval = "off"` (explicit) |

No kernel text was deleted: `skills/candidates/lean-code/SKILL.md` is untouched and still parses
into the same kernel (`tests/test_v3_shipping_lean_default.py`). Re-enabling is a configuration
flip (`SECOND_BRAIN_LEAN=advisory`, or `eval = "advisory"`), which is exactly what the
`candidate_lean` ablation arm runs.

Measured consequence (this is a finding, not an assumption): with `[lean] eval = "advisory"` the
kernel is still gated by the skillforge/frontier approval binding
(`skills.approved_content` / `approvedLeanText`). The live home has **no**
`frontier/skill-lean-code-promotion*.md` record, so both the live install and every arm resolve
`decision=omit, reason=unapproved_content` — the always-on advisory kernel is **inert in the
live install today**, and it does not appear in any captured request. The shipped `eval = "off"`
makes that state explicit instead of depending on a missing approval.

Reconciliation with S1: S1's report listed a live "Lean kernel (865 chars, live `advisory`)". 865
chars is the canonical kernel's length (`load_lean_kernel` on the live home returns exactly
865 chars at status `candidate`) — the *dormant* size carried in the lean outcome/telemetry, not
injected content. No captured request in this slice contains it, in any arm.

Evidence: `request-capture-smoke/manifest.json`

- `arms.<arm>.lean_gate_probe.gate` — resolved by that arm's own interpreter inside its own run
  home: `candidate` -> `{"mode": "off", "source": "file"}`, `candidate_lean` and `m00` ->
  `{"mode": "advisory", "source": "file"}`.
- `arms.<arm>.lean_overlay` — the candidate worktree's shipped file (`sha256 de159f94…`,
  `eval = "off"`, `rewritten_lines: 0`) and the one-value ablation file (`sha256 452700b4…`,
  `eval = "advisory"`, `rewritten_lines: 1`).
- `corpus.frontier_approvals` — the approval records present in the snapshot (no lean-code
  promotion record), which is why `candidate_lean` reports `unapproved_content`.
- `runs.json[*].lean_kernel` — the extension's own telemetry per run: `candidate` ->
  `("omit", "off", "off", "file")`; `m00`/`candidate_lean` ->
  `("omit", "unapproved-content", "advisory", "file", kernel_chars 0)`.

`SECOND_BRAIN_LEAN` is removed from every run's environment, so no arm can inherit an override
from the caller's shell; the telemetry `eval_source` field would reveal it if one leaked.

### What the harness runs (config fidelity)

`m00` keeps the live snapshot config. The two candidate arms get the candidate worktree's shipped
`config/skills.toml` copied into their disposable home (`applied_overlays`); everything else in
the home is the live snapshot. `config_deviation_inventory` lists every other config file the
candidate branch ships that this harness does **not** apply, with both hashes, so a reviewer can
see the scope of the configuration under test (notably `config/retrieval.toml` and its `[gate]`
section, which belongs to the retrieval-decision work, not this slice).

## 2. Provider-request capture (what the model was actually sent)

`scripts/v3_request_capture_extension.ts` is loaded by **every** arm as the **last** `-e` path —
native and inert included (`--no-extensions -e <capture>`), so all arms are measured under the
same host surface. It registers `before_provider_request`, writes the payload it observes to
`<out>/capture/<case>-<arm>-R<rep>/provider-request-<seq>.json` plus an `index.jsonl` (per-request
model, byte size, sha256, payload keys, message count, pid), and returns `undefined` so it never
changes what the host sends.

### Ordering: it really sees the post-Brain payload

- Documented contract: OMP loads explicit `-e` paths in the order given and de-duplicates by
  absolute path, first position winning; `ExtensionRunner.emitBeforeProviderRequest` walks the
  loaded extensions in that order and replaces `currentPayload` only when a handler returns a
  value (`docs` in the host repo: `extension-loading.md` "Load order and precedence",
  `extensions.md` provider-hook list; host source snapshot
  `docs/integrations/omp-host-patch-2026-09-19/host/runner.ts`).
- Empirical check (`--order-probe`, `capture-order-check.json`): with the mutating probe loaded
  **before** the capture, the capture recorded the probe's replacement
  (`marker_seen_in_capture = ["v3-order-probe-marker"]`); with the probe loaded **after** the
  capture, the capture recorded none (`[null]`). Verdict fields are both `true`.
- Residual limitation (recorded, not hidden): this proves ordering **between extension
  handlers**. Provider-adapter serialization after the hook is outside extension control, so the
  capture is "the last extension-stage payload", which is the payload Brain can influence.

### Normalization: two views, one declared path list

A review finding was fixed before this smoke: an earlier revision replaced *any* key named
`id`/`timestamp`/`duration` anywhere in the payload and rewrote UUID/date/epoch-ms patterns inside
*all* strings — which could have made genuinely different requests compare equal. The normalizer
is now path-directed:

- **content view (the diff is computed on this)** — the only edit is this run's own path strings
  (`<CWD>`, `<RUN_DIR>`, `<WORK_DIR>`, `<BRAIN_HOME>`, `<EXTENSION_n>`; longest first, both
  separator spellings). Model-visible text and the tool-schema subtree are never otherwise
  rewritten, so a changed schema property named `id`, a changed UUID/date inside message text, a
  changed `tool_calls` entry, or any changed message field all show up as differences. Message
  identity is the sha256 of the **whole message object**, not just its text. The raw untouched
  payload sha256 stays available per request in the capture `index.jsonl` (`payload_sha256`).
- **transport view (a secondary flag, `transport_identical`)** — the content view plus exactly
  these declared paths replaced by `<normalized>`: `messages[*].tool_calls[*].id`,
  `messages[*].tool_call_id` (observed in this work's captures),
  `prompt_cache_key`, `messages[*].id`, `messages[*].timestamp`, `messages[*].responseId`
  (documented OMP provider-envelope fields, so other providers cannot inject id noise).
- **unlisted transport-like paths** — any *other* key whose name looks transport-ish (`id`,
  `*_id`, `*Id`, `timestamp`, `created*`, `ttft`, `duration`, `*cache_key`) is listed in
  `unlisted_transport_like_keys` and left verbatim: unlisted noise must be visible, never masked.

`tests/test_v3_request_diff.py` pins that boundary: a tool schema with a property `id`, message
text differing only in a UUID/date, a changed `tool_calls` entry, declared tool-call ids (masked
only in the transport view) and an undeclared `vendor_trace_id` (reported, not masked).

Rule hits are recorded per request in `runs.json[*].normalization` (`paths` / `transport` /
`unlisted_transport_like_keys`) and merged per case/arm/rep in `diffs.json[*].normalized_fields`.

### Diff

`diffs.json` holds, per case/arm/rep: request counts, `first_request_identical` (content view),
`first_request_transport_identical`, `first_request_added_messages` /
`first_request_removed_messages` (role, chars, bounded head), `first_request_deltas`
(system/message/tool-schema chars), `char_deltas` over all requests, `per_request` (top-level
fields added/removed, changed scalars, tool schemas added/removed/changed, each with
`content_identical` and `transport_identical`), `same_request_set` /
`same_transport_request_set`, and `tail_requests_note` / `tail_request_shapes`.

Messages are matched as a multiset by `(role, sha256-of-the-whole-message)` rather than by
position: Second Brain patches the *system prompt* (m00 collapses the two host system blocks into
one) and *appends* a message, so positional pairing would report role changes that never
happened.

Provider usage is recorded separately from the request inventory and never coerced to 0:
`runs.json[*].provider_usage.totals[field]` is `null` when no assistant message reported that
field, with `fields_reported` counts and the per-request model/responseId list alongside.

## 3. Smoke results

One repetition, two dev cases (`D01` no-benefit overlap, `D02` short memory question), all five
arms, capture extension in every arm, `--order-probe`. `manifest.json` pins the run to
`harness_sha256 7a6e0950…` (this file at this commit). Artifacts:
`outputs/reports/v3-s2/request-capture-smoke/` (`manifest.json`, `runs.json`, `aggregate.json`,
`diffs.json`, `capture/`, `normalized/`, `capture-order-check.json`). Raw host streams:
`D01-<arm>-0.jsonl`, `D02-<arm>-0.jsonl`.

### D01 — "Reply with exactly: NB-OK-17. Do not use any tools." (no-benefit)

| arm | provider requests | first request vs native | Δ system chars | Δ message chars | Δ tool schemas | prompt tokens | Brain-visible chars |
|---|---|---|---|---|---|---|---|
| native | 1 | (reference) | — | — | — | 9653 | 0 |
| inert | 1 | **identical** (both views) | 0 | 0 | 0 | 9653 | 0 |
| candidate | 1 | **identical** (both views) | 0 | 0 | 0 | 9653 | 0 |
| candidate_lean | 1 | **identical** (both views) | 0 | 0 | 0 | 9653 | 0 |
| m00 | 1 | differs (both views) | +54 | +1440 | 0 | 10050 | 1386 |

m00's difference (`diffs.json["D01/m00/R0"]`): it removes the two host system blocks
(16939 + 915 chars) and sends one 17908-char system block (+54 chars of extension prefix), and
**adds** one user message of 1386 chars (the AutoInject packet) — the whole `brain_visible_chars`
count. The candidate and the Lean flip add nothing: same messages, same system prompt, same 12
tool schemas, identical prompt tokens.

### D02 — "In what order should database migrations be applied?" (memory)

| arm | provider requests | first request vs native | Δ system chars | Δ message chars | memory delivered | prompt tokens |
|---|---|---|---|---|---|---|
| native | 2 | (reference) | — | — | no | 19683 |
| inert | 2 | **identical** (both views) | 0 | 0 | no | 19755 |
| candidate | 2 | one added user message (495 chars) | 0 | +495 | yes | 19878 |
| candidate_lean | 2 | one added user message (495 chars) | 0 | +495 | yes | 19889 |
| m00 | 2 | two system blocks replaced by one (+54) and one added user message (615 chars) | +54 | +669 | yes | 20057 |

The candidate's only model-visible addition is the single bounded `[BRAIN_CONTEXT_DELTA v1]`
user message (495 chars vs m00's 615). It never touches the system prompt or the tool schemas, and
both candidate arms are identical to another (the Lean flip = 0 content delta).

### Cross-checks and caveats

- **Request counts after the first are the model's own tool loop.** D02 made 2 provider requests in
  this repetition (and 3 in earlier ones) for *every* arm including native; only the first request
  compares the arms' own injection. `same_request_set` / `same_transport_request_set` are
  therefore `false` for D02 even for the **inert** arm: the tail requests carry the model's own
  tool-call traffic (tool-call ids, timing, argument text), which differs run to run and is not
  Brain content. `first_request_identical` is the meaningful field for arm-injection claims.
- **Normalization did work and stayed narrow**: across the 15 captured requests of this
  repetition the rules fired as `path:<CWD>` 12×,
  `transport:messages[*].tool_calls[*].id` 8×, `transport:messages[*].tool_call_id` 8×, and
  **zero** `unlisted:` hits (no transport-looking path was left unexplained). Payloads were
  37,220-39,562 bytes, none truncated; every captured request reported model `deepseek-flash`.
  Without the path rule the arms would not be comparable at all (the cwd appears verbatim in the
  user reminder), and without the declared transport paths the model's own tool-call ids would
  make every tail request look different.
- **Unknown usage stays null**: e.g. D01/candidate `provider_usage.totals.reasoningTokens = null`
  with `fields_reported.reasoningTokens = 0`; `cost_total` is null when no request reported one.
  Provider usage is stored separately from the request inventory (count, per-request model,
  byte size, sha256, pid).
- **Lean decisions are recorded, not inferred**: `runs.json[*].lean_kernel` shows
  `candidate -> (omit, off, off, file)`, `candidate_lean`/`m00` ->
  `(omit, unapproved-content, advisory, file, kernel_chars 0)` — the config flip is visible
  (`manifest.arms.*.lean_gate_probe.gate`: `off`/`file` vs `advisory`/`file`), and it changes no
  request content in this profile.
- **Hook-order check**: `capture-order-check.json` — both verdict flags `true` (see §2).
- **Capture-extension footprint**: measured, not assumed, and reproducible with the harness
  itself (`--no-capture` vs capture on the same case and arms). D01 native prompt tokens are
  **9653 in both modes**; a fixed-path comparison over 2 runs per configuration gave no capture
  9647 / 9649, capture 9649 / 9650, capture + inert 9650 / 9649 — run-to-run variance (±3 tokens,
  0.03 %) is as large as any configuration effect. The smoke's `inert` rows add a *second*
  handler and their first request is still byte-identical to native's, so the capture extension
  does not change what the model is sent: it registers one `before_provider_request` handler and
  no tool, message or prompt text.
- **n = 1 per cell**, dev cases only. This proves the capture/diff machinery and shows the
  direction of the S2 patches; it is not the held-out evaluation and no timing claim is made
  from these numbers.


## 4. Reproducing

```powershell
cd .worktrees/v3-s1
$env:PYTHONHOME=$null; $env:PYTHONPATH=$null
.venv\Scripts\python.exe scripts\v3_matched_arms.py --reps 1 `
  --cases-file outputs\reports\v3-s2\dev\cases.jsonl --cases D01,D02 --order-probe `
  --out outputs\reports\v3-s2\request-capture-smoke
.venv\Scripts\python.exe -m pytest tests\test_v3_shipping_lean_default.py -q
.venv\Scripts\python.exe -m pytest tests\test_v3_request_diff.py -q
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m pyright scripts\v3_matched_arms.py tests\test_v3_request_diff.py tests\test_v3_shipping_lean_default.py
```

`--no-capture` restores the S1 timing surface (no capture extension) when only wall-clock
numbers are wanted; it produces no request-diff evidence.
