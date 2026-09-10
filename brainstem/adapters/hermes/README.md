# Second Brain Hermes adapter

This directory contains a standalone Hermes Agent plugin. It is a thin
transport/adaptation layer over the existing Second Brain contract; it does
not create Hermes-owned project memory, retrieval, telemetry, or ledger state.

## Runtime behavior

- `on_session_start` maps the Hermes session, configured bot name/role,
  provider/model, and repository to a canonical Brain session and agent.
- `pre_llm_call` sends only the current user message and bounded configured
  model candidates as ephemeral routing metadata. Brain owns model policy; the
  hook returns only ephemeral context to Hermes.
- `llm_request` middleware applies a cached Brain decision to the outgoing
  request. It rewrites the model and only provider fields already represented by
  the original request (including OpenRouter `extra_body.provider`); unsafe
  cross-provider handoffs fail open and are reported to Brain.
- `post_api_request` and `api_request_error` record decision-correlated,
  task-text-free invocation lifecycle facts, including bounded usage/cost data.
- `second_brain_writeback` is an explicit tool for significant, evidence-backed
  events. It creates the existing candidate memory with provenance; it does not
  promote the candidate automatically.
- `on_session_finalize` records finalization and checkpoints the existing
  per-session ledger.
- Any missing Brain, malformed response, timeout, or Brain exception fails open
  and does not break Hermes.

Hermes injects `pre_llm_call` results into the ephemeral current user message,
not its system prompt. This preserves the host prompt-cache prefix and keeps
Brain context out of Hermes' canonical conversation history.

## Configuration

Configure the plugin through Hermes' namespaced settings (not `.env`):

```yaml
plugins:
  entries:
    second-brain-hermes:
      enabled: true
      settings:
        brain_home: C:\\Users\\assas\\Documents\\The-Second-Brain
        brain_python: C:\\Users\\assas\\Documents\\The-Second-Brain\\.venv\\Scripts\\python.exe
        model_candidates:
          - provider: openrouter
            model: anthropic/claude-sonnet
            tier: premium
            capabilities: [reasoning]
            cost: medium
            availability: true
        bot_name: Brain-Dev
        bot_role: dev
        project_id: <registered-project-id>
        repo_root: C:\\Users\\assas\\Documents\\The-Second-Brain
        timeout_seconds: 5.0
```

Use distinct `bot_name`/`bot_role` settings for Brain-Dev,
Brain-Validator, and Brain-Integrator. The Hermes session ID is supplied by
Hermes at runtime; reconnecting the same bot/session reuses the same Brain
identity.

`repo_root` identifies the consumer project for Brain project resolution and
worker operations; it is not a Brain backend import root. Backend imports come
only from the configured `brain_python` environment (or configured `brainctl`).


## Validation and install

From the repository root, validate the plugin with the installed Hermes
runtime before enabling it:

```text
hermes plugins doctor brainstem/adapters/hermes --ci
```

Install the adapter from a published standalone plugin repository using
Hermes' normal `hermes plugins install` flow, or copy this directory into the
active Hermes profile's plugin directory for local development. Keep the Brain
repository available at the configured `brain_home`; Python module requests use
the configured environment with `-P`, a trusted backend working directory, and
`PYTHONHOME`/`PYTHONPATH` cleared for the Windows toolchain.
