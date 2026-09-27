#!/usr/bin/env node
// Runs the TypeScript sources directly: Node >= 22.18 strips types natively; Bun runs them too.
process.stdout.on("error", (error) => {
  if (error.code === "EPIPE") process.exit(0);
  throw error;
});
const { main } = await import("../src/cli.ts");
process.exitCode = await main(process.argv.slice(2));
