# Second Brain in the DeepSeek Harness

A DSH Host plugin that gives every Harness session the Brain's memory:

| Moment | What happens |
|---|---|
| **New session** | the Brain's start card is injected as one context message before the first step (where we left off, the notes that matter, recurring fixes) |
| **Subagent** | the child card: the parent plan's watch-outs, standing rules, recurring fixes and live doc headings (≤200 tokens) |
| **Working** | `brain_recall(query)`, `brain_note(text)`, `brain_state(text)` — the same tools OMP exposes, with the Brain's own when-to-act descriptions |
| **A tool fails** | the one tested fix the Brain knows for that error is appended to the result as `Brain: … [id]`, or nothing |
| **Every tool** | its outcome is recorded with `brain event`, so `brain review` and tested-fix learning see DSH sessions; `brain scan` catches up at compaction and session end |
| **150k context** | a ≤40-token hand-off hint (`brain rollover`) lands before the next step: save state, start fresh |
| **Compaction** | when the compaction dropped the card, it is injected again for the next step |
| **Resume** | nothing: the resumed history already carries its card |

Everything delegates to `brain` in the checkout, so notes, working state, recall judging, capture and telemetry keep one implementation. Nothing is duplicated, and the plugin is inert when the checkout or its runtime is missing.

## One warm process

The plugin starts one `brain serve` process per Host and sends it one JSON line per
command. The stat-validated note cache is paid once per session instead of once per
call:

| Command | Fresh CLI process | Warm service |
|---|---|---|
| `card --tools` | ~215 ms | ~35 ms |
| `recall` | ~410 ms | ~32 ms |
| `fix` (known-error path) | ~375 ms | ~31 ms |

Requests run in order; a call that outlives its timeout kills the process and the
next call starts a fresh one. A checkout older than the plugin (no `serve`) is
detected once and every call falls back to one process per call with the older
feature set (no capture, child card or context hint).

## Install (once per profile)

The plugin reads `SECOND_BRAIN_HOME` (set by `scripts/install-v4.ps1`):

```powershell
node brain/bin/brain.mjs check
```

Then install the bundle through the Harness plugin manager (absolute path to this
`dsh/` directory):

```text
plugin_manager(action: "install_bundle", target: "<this checkout>/dsh")
```

The row appears as **Second Brain** in Settings → Plugins. New sessions pick it up
immediately; a session already open gets the tools at its next request, but its card
only on its next start.

`dsh/index.js` is loaded when the Harness starts. If you update the checkout, restart the
Harness so the Host imports the updated module.

## Configuration

The row lives in the profile's `cordis.patch.yml` as `second-brain`. Defaults:

| Field | Default | Meaning |
|---|---|---|
| `home` | `SECOND_BRAIN_HOME` | Brain checkout (must contain `brain/bin/brain.mjs`) |
| `node` | `DSH_SECOND_BRAIN_NODE`, then `node` on `PATH` | runtime that starts the service (Node ≥ 22.18 or Bun) |
| `card` | `true` | inject the start card into fresh main sessions |
| `childCard` | `true` | inject the child card into subagents |
| `tools` | `true` | register `brain_recall`, `brain_note`, `brain_state` |
| `fix` | `true` | append a tested known fix to a failed tool result |
| `capture` | `true` | record tool outcomes, capture owner rules and scan at session end |
| `rollover` | `true` | inject the context hand-off hint at the project's threshold |

```yaml
- id: second-brain
  name: '@local/dsh-second-brain'
  config:
    home: C:/Users/assas/Documents/The-Second-Brain
    card: true
    tools: true
    fix: true
    capture: true
    rollover: true
```

## Behaviour details

- **Child agents** get the tools, the child card and no start card. `brain_state` is
  hidden from them (`brain_state` answers `not saved: working state belongs to the
  parent session` if a host still calls it). The child card is built from the parent
  plan's Watch out field, standing rules, recurring fixes, parent edits and live doc
  headings; the Host does not hand the plugin the child's brief, so the brief-ranked
  note selection OMP does is not used.
- **Capture** sends `{tool, input, isError, step, content?}` per tool call. A successful
  result is recorded in the background; a failed one is answered with its fix before the
  result returns. `step` counts assistant messages, so a retry from a later model message
  scores a fired fix and a same-batch sibling does not. Capture never holds a successful
  result: it is capped at 4 s (8 s for a fix), and every failure is swallowed with a
  `second-brain:` warning.
- **Timeouts.** A card, fix, prompt or scan is abandoned after 8 s (4 s for an event)
  without disturbing other calls; ordinary tool calls get 30 s and a wedged one replaces
  the warm process.
- **Telemetry.** `BRAIN_SESSION` carries the DSH session id, so `brain stats` counts
  these calls as CLI use and separates each session.
- **No context cost when empty.** An empty card, an unmatched fix or a hint below the
  threshold injects nothing.

## Verify

```powershell
node brain/bin/brain.mjs check                 # notes and projects check
node brain/bin/brain.mjs card --tools          # the card this project would inject
node brain/bin/brain.mjs rollover 151000       # the hand-off hint, once
```

Then in the Harness ask for `brain_recall` of a known note id, save a `brain_note`, and
check `brain stats --days 1` counts the calls.
## Limits

- **Start card cost.** The card is ≤320 tokens per session and the child card ≤200;
  nothing is injected when the Brain has nothing to say.
- **Working state is agent-written.** The plugin does not save auto observations
  (edited files, last ask) at session end: DSH exposes its transcript through the Host,
  not a file the plugin may read, so `state/work/<project>.auto.md` still comes from
  OMP and Claude Code only.
- **Host-scoped notes.** DSH fixes and cards are host-agnostic, as the CLI is: a note
  with `host: omp` or `host: claude-code` is not filtered out. Add a `dsh` host value
  before relying on host scoping here.
