/**
 * The Windows installer and uninstaller, run for real with PowerShell 7 (GitHub's runners ship
 * `pwsh`; set PWSH to a binary elsewhere). After each install, Bun — Oh My Pi's runtime — loads
 * the installed extension through its entry file, the way OMP does.
 */
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { PACKAGE_HOME } from "../src/util.ts";

const which = (cmd: string): string | undefined =>
  spawnSync(process.platform === "win32" ? "where" : "which", [cmd], { encoding: "utf8" }).stdout.split(/\r?\n/)[0]?.trim() || undefined;
const PWSH = process.env.PWSH || which("pwsh");
const BUN = which("bun");
const shim = join(PACKAGE_HOME, "brain", "bin", "brain.cmd");
const shimExisted = existsSync(shim);

function ps(script: string, ...args: string[]): { status: number | null; out: string } {
  const r = spawnSync(PWSH as string, ["-NoLogo", "-NoProfile", "-File", join(PACKAGE_HOME, "scripts", script), ...args], {
    encoding: "utf8",
    env: { ...process.env, SECOND_BRAIN_HOME: PACKAGE_HOME },
  });
  return { status: r.status, out: r.stdout + r.stderr };
}

function bunLoads(extensions: string): string {
  const probe = join(mkdtempSync(join(tmpdir(), "brain-probe-")), "probe.ts");
  writeFileSync(
    probe,
    `const mod = await import(${JSON.stringify(join(extensions, "second-brain-v4", "index.ts"))});
const on: string[] = []; const tools: string[] = [];
mod.default({ on: (e: string) => on.push(e), registerTool: (t: any) => tools.push(t.name) }, { SECOND_BRAIN_HOME: ${JSON.stringify(PACKAGE_HOME)} });
console.log(on.sort().join(",") + "|" + tools.join(","));`,
  );
  return spawnSync(BUN as string, [probe], { encoding: "utf8" }).stdout.trim();
}

afterAll(() => {
  if (!shimExisted) rmSync(shim, { force: true });
});

describe.skipIf(!PWSH)("install-v4.ps1 / uninstall-v4.ps1", () => {
  it("parks older extensions, installs a BOM-free loader, self-checks, and rolls back", () => {
    const root = mkdtempSync(join(tmpdir(), "brain-install-"));
    const extensions = join(root, "extensions");
    for (const old of ["second-brain", "second-brain-v3"]) {
      mkdirSync(join(extensions, old), { recursive: true });
      writeFileSync(join(extensions, old, "index.ts"), `// ${old}\n`);
    }
    const install = ps("install-v4.ps1", "-ExtensionsDir", extensions, "-NoPath", "-NoEnv");
    expect(install.status, install.out).toBe(0);
    expect(install.out).toMatch(/notes: \d+ \(\d+ active\)/);
    expect(readdirSync(extensions)).toEqual(["second-brain-v4"]);
    // Parked as one set (one stamp), so -Restore brings back both
    expect(new Set(readdirSync(join(root, "extensions-disabled")).map((name) => name.slice(-15))).size).toBe(1);
    const loader = readFileSync(join(extensions, "second-brain-v4", "index.ts"));
    expect(loader.subarray(0, 2).toString()).toBe("//");
    expect(loader.toString()).toContain(`export { default } from "${join(PACKAGE_HOME, "brain", "src", "omp.ts").replace(/\\/g, "/")}";`);
    expect(readFileSync(shim, "utf8")).toMatch(/^@(node|bun) "%~dp0brain\.mjs" %\*\r\n$/);
    if (BUN) expect(bunLoads(extensions)).toBe("before_agent_start,context,session_before_branch,session_before_switch,session_branch,session_compact,session_shutdown,session_switch,tool_result|brain_recall,brain_note,brain_state");

    const copy = ps("install-v4.ps1", "-ExtensionsDir", extensions, "-NoPath", "-NoEnv", "-Copy");
    expect(copy.status, copy.out).toBe(0);
    const copied = readdirSync(join(extensions, "second-brain-v4"));
    expect(copied).toContain("omp.ts");
    expect(copied).not.toContain("cli.ts");
    if (BUN) expect(bunLoads(extensions)).toMatch(/\|brain_recall,brain_note,brain_state$/);

    const undo = ps("uninstall-v4.ps1", "-ExtensionsDir", extensions, "-Restore");
    expect(undo.status, undo.out).toBe(0);
    expect(readdirSync(extensions).sort()).toEqual(["second-brain", "second-brain-v3"]);
    expect(readFileSync(join(extensions, "second-brain-v3", "index.ts"), "utf8")).toBe("// second-brain-v3\n");
  });
});

describe("the sh shim for Git Bash and POSIX shells", () => {
  it("runs the CLI, and is committed executable with LF endings", () => {
    const shimSh = join(PACKAGE_HOME, "brain", "bin", "brain");
    const r = spawnSync("sh", [shimSh, "help"], { encoding: "utf8" });
    expect(r.stdout).toContain("brain recall");
    expect(readFileSync(shimSh, "utf8")).not.toContain("\r");
    expect(spawnSync("git", ["-C", PACKAGE_HOME, "ls-files", "-s", "brain/bin/brain"], { encoding: "utf8" }).stdout).toMatch(/^100755 /);
  });
});
