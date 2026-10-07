import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { pathHint } from "../src/paths.ts";
import { estimateTokens } from "../src/util.ts";
import { FIX_BUDGET } from "../src/capture.ts";

/** A non-git tree (the bounded walk); tmpdir is outside any checkout. */
function tree(files: string[]): string {
  const root = mkdtempSync(join(tmpdir(), "brain-paths-"));
  for (const file of files) {
    mkdirSync(join(root, file, ".."), { recursive: true });
    writeFileSync(join(root, file), "");
  }
  return root;
}

describe("pathHint", () => {
  it("names the same file in the folder where it actually lives, nearest folders first", () => {
    const root = tree(["brain/scripts/agentbench.ts", "old/agentbench.ts", "brain/src/card.ts"]);
    const hint = pathHint("read", "scripts/agentbench.ts:15-47", "Path 'scripts/agentbench.ts:15' not found", root);
    expect(hint).toBe("Brain: scripts/agentbench.ts does not exist; closest: brain/scripts/agentbench.ts, old/agentbench.ts");
  });

  it("catches a typo, another extension, and a missing folder", () => {
    const root = tree(["src/telemetry.ts", "docs/LOOP.md", "brain/scripts/perf.ts"]);
    expect(pathHint("Read", join(root, "src/telemtry.ts"), "File does not exist.", root)).toContain("closest: src/telemetry.ts");
    expect(pathHint("grep", "src/telemetry.js", "Path not found: src/telemetry.js", root)).toContain("closest: src/telemetry.ts");
    expect(pathHint("glob", "scripts", "Path not found: scripts", root)).toContain("closest: brain/scripts/");
  });

  it("lists the deepest existing folder when nothing looks alike", () => {
    const root = tree(["data/test/a.jsonl", "data/test/b.jsonl", "data/train/c.jsonl"]);
    expect(pathHint("read", "data/test/README.md", "Path 'data/test/README.md' not found", root)).toBe("Brain: data/test/README.md does not exist; data/test/ holds: a.jsonl, b.jsonl");
  });

  it("stays silent on other errors, existing paths, URLs, shell commands and unrelated names", () => {
    const root = tree(["src/card.ts"]);
    expect(pathHint("read", "src/card.ts:9999", "Path 'src/card.ts:9999' not found", root)).toBe("");
    expect(pathHint("edit", "src/cards.ts", "String to replace not found in file.", root)).toBe("");
    expect(pathHint("edit", "src/card.ts", "Edit rejected for src/card.ts: file changed between read and edit.", root)).toBe("");
    expect(pathHint("read", "https://example.com/x.md", "Not found", root)).toBe("");
    expect(pathHint("bash", "src/cards.ts", "No such file or directory", root)).toBe("");
    expect(pathHint("read", "quantum.py", "Path 'quantum.py' not found", root)).toBe("");
  });

  it("stays within the fix budget however many files match", () => {
    const root = tree(Array.from({ length: 12 }, (_, i) => `a_rather_long_folder_name_number_${i}/another_long_folder_name/index.ts`));
    const hint = pathHint("read", "index.ts", "Path 'index.ts' not found", root);
    expect(hint).toMatch(/^Brain: index\.ts does not exist; closest: /);
    expect(estimateTokens(hint)).toBeLessThanOrEqual(FIX_BUDGET);
  });
});
