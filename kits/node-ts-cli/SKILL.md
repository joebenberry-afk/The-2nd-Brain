---
name: node-ts-cli
description: "A TypeScript CLI with no build step: Node >= 22.18 runs .ts directly, vitest, strict types."
tags:
  - typescript
  - node
---

# node-ts-cli

## When to use
- A small tool or library in TypeScript that should run from a clone with zero build.

## Stack and why
- Node >= 22.18 strips types natively (Bun runs the same files): no tsc output, no dist/.
- `tsc --noEmit` for types, vitest for tests, eslint + @typescript-eslint for lint; all devDependencies.
- `node:util` `parseArgs` for arguments: no CLI framework.

## Scaffold
1. `package.json`: `"type": "module"`, `"bin": { "<cmd>": "bin/<cmd>.mjs" }`, `"engines": { "node": ">=22.18" }`.
2. `bin/<cmd>.mjs`: `const { main } = await import("../src/cli.ts"); process.exitCode = await main(process.argv.slice(2));`
3. `tsconfig.json`: `strict`, `noEmit`, `allowImportingTsExtensions`, `erasableSyntaxOnly`, `verbatimModuleSyntax`, `module: NodeNext`.
4. Relative imports end in `.ts`; type-only imports use `import type`.
5. `npm i -D typescript vitest @types/node eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin`.
6. `main(argv, io)` takes injected stdout/stderr/env/cwd so tests call it in-process.

## Gotchas
- No `enum`, `namespace` or constructor parameter properties: type stripping rejects them (`erasableSyntaxOnly` catches it).
- `"a/b/c".split("/", 2)` drops the rest in JS (Python keeps it): split on `indexOf` instead.
- `mkdirSync(recursive)` under `/proc` hangs forever: never use /proc paths as test fixtures.
- On Windows ship a `<cmd>.cmd` shim: `@node "%~dp0bin\<cmd>.mjs" %*`.

## MVP done when
- [ ] `node bin/<cmd>.mjs help` works from a fresh clone, and `tsc --noEmit && vitest run` is green in CI.
