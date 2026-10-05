import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeEach, vi } from "vitest";

// CLI children inherit an empty memory root, never the owner's Claude memories.
const claude = mkdtempSync(join(tmpdir(), "brain-empty-claude-"));
process.env.CLAUDE_CONFIG_DIR = claude;
afterAll(() => rmSync(claude, { recursive: true, force: true }));

// Never inherit the owner's credentials, including in CLI child processes.
delete process.env.TYPESAFE_API_KEY;
beforeEach(() => {
  delete process.env.TYPESAFE_API_KEY;
  vi.stubGlobal("fetch", () => { throw new Error("Network is disabled in tests; mock fetch explicitly"); });
});
