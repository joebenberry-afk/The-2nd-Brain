#!/usr/bin/env node
// Runs the TypeScript sources directly: Node >= 22.18 strips types natively; Bun runs them too.
const { main } = await import("../src/cli.ts");
process.exitCode = await main(process.argv.slice(2));
