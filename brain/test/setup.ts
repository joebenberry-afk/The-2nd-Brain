import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeEach, vi } from "vitest";

// CLI children inherit empty host roots, never the owner's Claude memories or OMP/Claude sessions.
const claude = mkdtempSync(join(tmpdir(), "brain-empty-claude-"));
const omp = mkdtempSync(join(tmpdir(), "brain-empty-omp-"));
process.env.CLAUDE_CONFIG_DIR = claude;
process.env.PI_CODING_AGENT_DIR = omp;
afterAll(() => { rmSync(claude, { recursive: true, force: true }); rmSync(omp, { recursive: true, force: true }); });

// Never inherit the owner's credentials or live Tora session (it judges recall now), including in CLI
// child processes. Tora tests pass their own env with a fake session directory.
delete process.env.TYPESAFE_API_KEY;
process.env.BRAIN_TORA = "off";
beforeEach(() => {
  delete process.env.TYPESAFE_API_KEY;
  vi.stubGlobal("fetch", () => { throw new Error("Network is disabled in tests; mock fetch explicitly"); });
});
