---
name: omp-extension
description: "Build an Oh My Pi extension that survives OMP updates: hooks, hidden context, tools, no build step."
tags:
  - omp
  - typescript
---

# omp-extension

## When to use
- Adding behaviour to Oh My Pi sessions (context, tools, logging) without patching OMP.

## Stack and why
- One default-exported function `(pi) => void` in `index.ts`; OMP runs TypeScript directly, so no bundler.
- Node built-ins only: no dependency can break on an OMP upgrade.
- Read every host field defensively (`typeof x === "function"`, optional chaining); a renamed field must degrade to "do nothing", never throw.

## Scaffold
1. `~/.omp/agent/extensions/<name>/index.ts` with `export default function (pi) { … }`.
2. Hidden context on a turn: `pi.on("before_agent_start", …)` → `{ message: { customType, content, display: false } }`.
3. Per-LLM-call context: `pi.on("context", e => ({ messages: [...] }))`; insert right after the last `compactionSummary` message (Anthropic-native compaction drops everything before it) with frozen values so the prompt cache holds.
4. Tools: `pi.registerTool({ name, label, description, parameters, execute })`; build `parameters` with `pi.typebox.Type` when present, else plain JSON schema.
5. Keep the source in a repo and install a one-line loader: `export { default } from "<abs path>/index.ts";`.
6. Restart OMP to load changes.

## Gotchas
- Wrap every handler in try/catch and return `undefined`: a throw can break the session.
- `execute` argument order differs between hosts: find params and ctx by shape, not position.
- Live pilots saw a single `ipython` tool with `%%bash` cells: read commands from `input.command | cmd | code`.
- Tool descriptions cost tokens in every context: keep them to one sentence.
- Handling `session_before_compact` turns off OMP's background compaction; save state in `session_compact` (it also fires for `/handoff`).
- Extensions are rebound into every subagent: check `ctx.agent.kind === "sub"` before writing shared state.
- Tools default to `exec` approval: declare `approval: "read"` / `"write"` or they prompt in ask modes and fail in headless children.
- The `edit` tool's input is `{ input: string }` (hashline `[path#TAG]` headers), not `{ path }`.

## MVP done when
- [ ] A fake-host vitest (collect `on` handlers, call them) passes, and one real OMP session shows the hidden message.
