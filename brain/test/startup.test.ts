import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { expect, it } from "vitest";

it("runs a no-op hook without loading optional command modules", () => {
  const home = mkdtempSync(join(tmpdir(), "brain-startup-test-"));
  mkdirSync(join(home, "notes"));
  const cli = pathToFileURL(join(import.meta.dirname, "..", "src", "cli.ts")).href;
  // Module-loading boundary test: register before importing the CLI under test.
  const script = `
    import { registerHooks } from "node:module";
    registerHooks({ resolve(specifier, context, next) {
      if (/\\/(?:mcp|proxy|convert|okf|silent|sync|tidy|judge)\\.ts$/.test(specifier)) {
        throw new Error("optional command module loaded by hook: " + specifier);
      }
      return next(specifier, context);
    }});
    const { main } = await import(${JSON.stringify(cli)});
    process.exitCode = await main(["hook", "claude-code"], {
      stdin: () => "{}", cwd: ${JSON.stringify(home)},
      env: { SECOND_BRAIN_HOME: ${JSON.stringify(home)} },
    });
  `;
  try {
    const child = spawnSync(process.execPath, ["--input-type=module", "-e", script], { encoding: "utf8", windowsHide: true, timeout: 15_000 });
    expect(child.error).toBeUndefined();
    expect(child.stderr).toBe("");
    expect(child.status).toBe(0);
    expect(child.stdout.trim()).toBe("{}");
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});
