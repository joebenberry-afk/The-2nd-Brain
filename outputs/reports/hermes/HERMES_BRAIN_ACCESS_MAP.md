# Hermes ↔ Second Brain Access Map

**Status:** seam map before implementation
**Repository:** `C:\Users\assas\Documents\The-Second-Brain`
**Branch:** `brain/v1-rc4-prime-074-compat`
**HEAD at mapping time:** `0bc2b8d56ceed3c1e17576283f05b4dba6f52d91`

## Boundary decision

Hermes will remain a thin host adapter. It will use Hermes' documented native
plugin hooks (`on_session_start`, `pre_llm_call`, and
`on_session_finalize`) and call the existing Brain CLI through the repository
venv. No Hermes-native project-memory copy, vector store, retrieval engine,
ledger, or telemetry store will be introduced.

The adapter boundary is `brainstem/adapters/hermes/`; the Python CLI bridge is
an adapter entry point over existing `second_brain` primitives. The plugin must
fail open when the Brain is unavailable.

## Requirement-to-primitive map

| Hermes requirement | Existing Brain primitive | Adapter seam |
|---|---|---|
| Stable host/session registration | `contracts.BrainSessionIdentity` and `autoinject.BrainLifecycle.start_session()` (`src/second_brain/contracts.py:224`, `src/second_brain/autoinject.py:893`) | Map Hermes session ID + configured bot identity to one canonical host-session key; register idempotently on session start and lazily before retrieval. |
| Repository/project identity | `autoinject._resolve_project_id()` and `registry` (`src/second_brain/autoinject.py:196`, `src/second_brain/registry.py`) | Resolve from configured/callback cwd using the existing registry ladder; retain repo root as bounded metadata. |
| Bot/agent identity | `contracts.AgentIdentity` shape and `ledger.LedgerStore.register_agent()` (`src/second_brain/contracts.py:244`, `src/second_brain/ledger.py:419`) | Register `bot_name`, role, provider, model, and host agent ID in the canonical per-session ledger. |
| Bounded targeted retrieval | `autoinject.BrainLifecycle.prepare_injection()` + `render_packet()` (`src/second_brain/autoinject.py:926`, `:635`) | Pass only the current Hermes user message as an ephemeral query; return the canonical packet only when the existing AutoInject mode is `advisory` or `active`. |
| Startup/resume context | Hermes `pre_llm_call` return contract; Brain AutoInject budget (`src/second_brain/autoinject.py:641`, `:1123`) | Inject the bounded packet into Hermes' ephemeral current user message, never into the system prompt or Hermes session memory. |
| Controlled durable write | `autoinject.BrainLifecycle.writeback_candidate()` (`src/second_brain/autoinject.py:1035`) and `semantic.add_memory()` (`src/second_brain/semantic.py:459`) | Expose an explicit writeback tool. Writes are candidates with provenance; no automatic promotion to current truth. |
| Telemetry | existing privacy-safe `_append_telemetry()` used by AutoInject (`src/second_brain/autoinject.py:853`) and `telemetry.validate/report()` (`src/second_brain/telemetry.py`) | Record bounded identity, decision, counts, hashes, and outcome metadata only; never persist raw query text in telemetry. |
| Per-session ledger | `ledger.LedgerStore`, `append_events()`, `checkpoint_ledger()` (`src/second_brain/ledger.py:256`, `:470`, `:1289`) | Create/reopen the canonical `state/sessions/<sha256(host-session)>/ledger.sqlite`, register the bot, append lifecycle/retrieval/writeback evidence, and checkpoint at finalization. |
| Recovery/compaction | `LedgerStore.continuation_capsule()`, `LedgerRehydrator`, and `SessionLifecycle.recover_report()` (`src/second_brain/ledger.py:692`, `:1080`, `:1406`) | Initial Hermes slice records enough lifecycle/retrieval evidence for existing recovery tools; it does not create a Hermes recovery subsystem. |
| Provider/model metadata | Hermes hook callback kwargs and `contracts.AgentIdentity` fields | Pass provider/model through the adapter; use `unknown` when Hermes does not expose a field rather than infer it. |

## Planned minimal runtime flow

```text
Hermes plugin hook
  -> JSON subprocess call to the Brain venv
  -> resolve/register canonical Brain session + agent
  -> Brain AutoInject retrieval with existing budget/filters
  -> canonical packet (or no injection)
  -> Hermes ephemeral pre_llm_call context
  -> existing Brain telemetry + session ledger
```

The write flow is explicit and controlled:

```text
Hermes writeback tool
  -> existing Brain writeback candidate primitive
  -> provenance + telemetry + ledger evidence
```

## Intentionally out of scope for this slice

- Hermes-native memory or session search as a project-memory authority.
- A second database, vector index, cache, or policy lifecycle.
- Automatic semantic extraction of every assistant response.
- Automatic candidate promotion.
- Modifying Hermes core; the integration belongs in a standalone plugin adapter.
- Prime Phase N live promotion work documented in
  `outputs/reports/rc4/prime-074/final-promotion-gates/`; that is the next
  project milestone, not part of Hermes bootstrap.

## Evidence for the reference contract

- `brainstem/adapters/claude-code/README.md` and
  `src/second_brain/cli.py:2719` show the existing thin host-adapter pattern.
- `tests/test_claude_code_adapter.py` proves lifecycle, fail-open, ledger, and
  bounded-resume behavior for the reference adapter.
- Hermes documentation confirms plugin hooks inject ephemeral context through
  `pre_llm_call` and that injection is appended to the user message rather than
  the system prompt, preserving prompt-cache stability.
