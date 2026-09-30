/**
 * The Windows installer and uninstaller, run for real with PowerShell 7 (`pwsh`) or, on Windows
 * without it, Windows PowerShell 5.1: the shell brain.ps1's BRAIN_ARGV path exists for. Set PWSH
 * to pick a binary. After each install, Bun — Oh My Pi's runtime — loads
 * the installed extension through its entry file, the way OMP does.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { loadNotes, staleEvidence } from "../src/notes.ts";
import { PACKAGE_HOME } from "../src/util.ts";

const which = (cmd: string): string | undefined =>
  spawnSync(process.platform === "win32" ? "where" : "which", [cmd], { encoding: "utf8" }).stdout.split(/\r?\n/)[0]?.trim() || undefined;
const PWSH = process.env.PWSH || which("pwsh") || (process.platform === "win32" ? which("powershell") : undefined);
const BUN = which("bun");
const sandbox = mkdtempSync(join(tmpdir(), "brain-install-"));
const home = join(sandbox, "home");
const shim = join(home, "brain", "bin", "brain.cmd");

beforeAll(() => {
  for (const path of ["brain/src", "brain/bin", "brain/package.json", "scripts"]) {
    cpSync(join(PACKAGE_HOME, path), join(home, path), { recursive: true });
  }
  mkdirSync(join(home, "notes"));
  writeFileSync(join(home, "projects.json"), '{"projects":{}}\n');
  execFileSync("git", ["init", home]);
  // Keep the real tracked mode instead of manufacturing the executable bit in the fixture.
  const index = execFileSync("git", ["-C", PACKAGE_HOME, "rev-parse", "--path-format=absolute", "--git-path", "index"], { encoding: "utf8" }).trim();
  cpSync(index, join(home, ".git", "index"));
});

function ps(script: string, ...args: string[]): { status: number | null; out: string } {
  const r = spawnSync(PWSH as string, ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", join(home, "scripts", script), ...args], {
    encoding: "utf8", cwd: home,
    env: { ...process.env, TYPESAFE_API_KEY: undefined, SECOND_BRAIN_HOME: home },
  });
  return { status: r.status, out: r.stdout + r.stderr };
}

function bunLoads(extensions: string): string {
  const probe = join(sandbox, "probe.ts");
  writeFileSync(
    probe,
    `const mod = await import(${JSON.stringify(join(extensions, "second-brain-v4", "index.ts"))});
const on: string[] = []; const tools: string[] = [];
mod.default({ on: (e: string) => on.push(e), registerTool: (t: { name: string }) => tools.push(t.name) }, { SECOND_BRAIN_HOME: ${JSON.stringify(home)} });
console.log(on.sort().join(",") + "|" + tools.join(","));`,
  );
  return spawnSync(BUN as string, [probe], { encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined } }).stdout.trim();
}

afterAll(() => {
  rmSync(sandbox, { recursive: true, force: true });
});

describe.skipIf(!PWSH)("install-v4.ps1 / uninstall-v4.ps1", () => {
  it("parks older extensions, installs a BOM-free loader, self-checks, and rolls back", () => {
    const root = sandbox;
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
    expect(loader.toString()).toContain(`export { default } from "${join(home, "brain", "src", "omp.ts").replace(/\\/g, "/")}";`);
    expect(readFileSync(shim, "utf8")).toMatch(/^@(node|bun) "%~dp0brain\.mjs" %\*\r\n$/);
    // Windows PowerShell finds brain.ps1 too: under its Restricted or AllSigned policy the installer
    // keeps brain.cmd alone. The installer asks it without an inherited -ExecutionPolicy; so does this.
    const winPs = process.platform === "win32" ? spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", "Get-ExecutionPolicy"], {
      encoding: "utf8", env: { ...process.env, PSExecutionPolicyPreference: undefined },
    }).stdout?.trim() ?? "" : "";
    if (!/^(Restricted|AllSigned)/.test(winPs)) {
      // PowerShell prefers brain.ps1 to brain.cmd, whose cmd.exe expands %VAR% inside note text.
      const brainPs1 = (...args: string[]) => spawnSync(PWSH as string, ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", join(home, "brain", "bin", "brain.ps1"), ...args], {
        encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined, SECOND_BRAIN_HOME: home },
      });
      const note = brainPs1("note", "Shim keeps %USERPROFILE% literal", "--project", "shim");
      expect(note.status, note.stdout + note.stderr).toBe(0);
      const [saved] = readdirSync(join(home, "notes", "shim"));
      expect(readFileSync(join(home, "notes", "shim", saved as string), "utf8")).toContain("Shim keeps %USERPROFILE% literal");
      // Windows PowerShell 5.1 drops quotes inside native arguments; brain.ps1 passes argv as JSON.
      const quoted = brainPs1("note", 'Use "npm ci" not "npm install" in CI', "--project", "quoted", "--error", 'Task "build app" failed');
      expect(quoted.status, quoted.stdout + quoted.stderr).toBe(0);
      expect(loadNotes(home).notes.find((n) => n.project === "quoted")).toMatchObject({ body: 'Use "npm ci" not "npm install" in CI', errors: ['Task "build app" failed'] });
      // PowerShell parses bare 3.10, 2.0 and 0x80070005 as numbers; brain.ps1 must pass them as typed.
      const nums = spawnSync(PWSH as string, ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", `& '${join(home, "brain", "bin", "brain.ps1")}' note Pin python 3.10 not 2.0 --project nums --error 0x80070005`], {
        encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined, SECOND_BRAIN_HOME: home },
      });
      expect(nums.status, nums.stdout + nums.stderr).toBe(0);
      expect(loadNotes(home).notes.find((n) => n.project === "nums")).toMatchObject({ body: "Pin python 3.10 not 2.0", errors: ["0x80070005"] });
    }
    if (BUN) expect(bunLoads(extensions)).toBe("before_agent_start,context,session_before_branch,session_before_switch,session_branch,session_compact,session_shutdown,session_start,session_switch,tool_result|brain_recall,brain_note,brain_state");

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

  it("keeps brain.cmd alone where the execution policy would refuse brain.ps1", () => {
    // PowerShell runs brain.ps1 before brain.cmd, and under Restricted refuses it without falling back.
    const stub = "function Get-ExecutionPolicy { param($Scope) 'Restricted' }";
    const install = `& '${join(home, "scripts", "install-v4.ps1")}' -ExtensionsDir '${join(sandbox, "extensions-restricted")}' -NoPath -NoEnv`;
    const r = spawnSync(PWSH as string, ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", `${stub}; ${install}`], {
      encoding: "utf8", cwd: home, env: { ...process.env, TYPESAFE_API_KEY: undefined, SECOND_BRAIN_HOME: home },
    });
    expect(r.status, r.stdout + r.stderr).toBe(0);
    expect(r.stdout + r.stderr).toContain("RemoteSigned");
    const bin = readdirSync(join(home, "brain", "bin"));
    expect(bin).toContain("brain.cmd");
    expect(bin).not.toContain("brain.ps1");
  });
});

describe("the sh shim for Git Bash and POSIX shells", () => {
  it("runs the CLI, and is committed executable with LF endings", () => {
    const shimSh = join(home, "brain", "bin", "brain");
    const r = spawnSync("sh", [shimSh, "help"], { encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined } });
    expect(r.stdout).toContain("brain recall");
    expect(readFileSync(shimSh, "utf8")).not.toContain("\r");
    expect(spawnSync("git", ["-C", home, "ls-files", "-s", "brain/bin/brain"], { encoding: "utf8" }).stdout).toMatch(/^100755 /);
  });

  // Git Bash rewrites arguments that look like POSIX paths before a native program sees them.
  it.skipIf(process.platform !== "win32" || !which("cygpath"))("passes slash-leading note text through Git Bash as typed", () => {
    const h = mkdtempSync(join(tmpdir(), "brain-shim-"));
    const r = spawnSync("sh", [join(home, "brain", "bin", "brain"), "--home", h, "--project", "q", "note", "/clear resets context"], { encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined } });
    expect(r.status, r.stdout + r.stderr).toBe(0);
    expect(loadNotes(h).notes[0]?.body.startsWith("/clear resets context")).toBe(true);
  });

  it.skipIf(process.platform !== "win32" || !which("cygpath"))("maps a Git Bash --from path, both spellings", () => {
    const h = mkdtempSync(join(tmpdir(), "brain-shim-"));
    const shim = join(home, "brain", "bin", "brain").replace(/\\/g, "/");
    const script = `V=$(mktemp -d) && mkdir "$V/records" && sh "${shim}" --home "${h.replace(/\\/g, "/")}" convert --from "$V" --dry-run && sh "${shim}" --home "${h.replace(/\\/g, "/")}" convert --from="$V" --dry-run`;
    const r = spawnSync("sh", ["-c", script], { encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined } });
    expect(r.status, r.stdout + r.stderr).toBe(0);
    expect(r.stdout).toContain("(dry run)");
  });

  it.skipIf(process.platform !== "win32" || !which("cygpath"))("maps a Git Bash --evidence path, both spellings, keeping its line", () => {
    const h = mkdtempSync(join(tmpdir(), "brain-shim-")).replace(/\\/g, "/");
    const shim = join(home, "brain", "bin", "brain").replace(/\\/g, "/");
    const brain = `sh "${shim}" --home "${h}" --project q note`;
    const script = `P=$(mktemp -d) && touch "$P/file.ts" && ${brain} "the widget cache must be flushed after rebuild" --evidence "$P/file.ts:3" --evidence commit:abc1234 && ${brain} "the thumbnail queue drains before exit" --evidence="$P/file.ts"`;
    const r = spawnSync("sh", ["-c", script], { encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined } });
    expect(r.status, r.stdout + r.stderr).toBe(0);
    const evidence = loadNotes(h).notes.flatMap((note) => note.evidence).sort();
    expect(evidence).toHaveLength(3);
    expect(evidence[0]).toMatch(/^[A-Za-z]:\/.*\/file\.ts$/);
    expect(evidence[1]).toMatch(/^[A-Za-z]:\/.*\/file\.ts:3$/);
    expect(evidence[2]).toBe("commit:abc1234");
    expect(loadNotes(h).notes.some((note) => staleEvidence(note, [h]))).toBe(false);
  });
});

describe("brain.mjs argv from BRAIN_ARGV (brain.ps1)", () => {
  const brainMjs = join(PACKAGE_HOME, "brain", "bin", "brain.mjs");
  const note = ["note", 'Use "npm ci" not "npm install" in CI', "--project", "q", "--error", 'Task "build app" failed'];

  it("takes argv as JSON, so quotes inside arguments survive", () => {
    const h = mkdtempSync(join(tmpdir(), "brain-argv-"));
    const r = spawnSync(process.execPath, [brainMjs], { encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined, BRAIN_ARGV: JSON.stringify([...note, "--home", h]) } });
    expect(r.status, r.stdout + r.stderr).toBe(0);
    expect(loadNotes(h).notes[0]).toMatchObject({ body: 'Use "npm ci" not "npm install" in CI', errors: ['Task "build app" failed'] });
  });

  it("ignores it when there is a real argument", () => {
    const h = mkdtempSync(join(tmpdir(), "brain-argv-"));
    const r = spawnSync(process.execPath, [brainMjs, "help"], { encoding: "utf8", env: { ...process.env, TYPESAFE_API_KEY: undefined, BRAIN_ARGV: JSON.stringify([...note, "--home", h]) } });
    expect(r.status).toBe(0);
    expect(r.stdout).toContain("brain recall");
    expect(loadNotes(h).notes).toEqual([]);
  });
});
