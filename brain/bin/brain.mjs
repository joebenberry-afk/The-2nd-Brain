#!/usr/bin/env node
// Runs the TypeScript sources directly: Node >= 22.18 strips types natively; Bun runs them too.
process.stdout.on("error", (error) => {
  if (error.code === "EPIPE") process.exit(0);
  throw error;
});
const { main } = await import("../src/cli.ts");
// brain.ps1 passes argv as JSON: Windows PowerShell 5.1 drops quotes inside native arguments. It
// is honoured only when there is no real argv, so a leftover value never replays; children never see it.
const raw = process.env.BRAIN_ARGV;
delete process.env.BRAIN_ARGV;
const argv = raw !== undefined && process.argv.length <= 2 ? [].concat(JSON.parse(raw)).map(String) : process.argv.slice(2);
const code = await main(argv);
// Exit once output is flushed: a timed-out judge fetch leaves a TCP connect that would keep the
// process alive ~10 s more on a network that drops packets. `mcp` returns only after stdin ends.
process.stderr.write("", () => process.stdout.write("", () => process.exit(code)));
