import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  normalizePath,
  v3Brief,
  v3BriefMessage,
  v3Correction,
  v3Enabled,
  v3Telemetry,
  viewKey,
} from "../src/v3-memory";

function home(): { home: string; repo: string } {
  const root = mkdtempSync(join(tmpdir(), "v3-memory-"));
  const repo = join(root, "work", "repo");
  mkdirSync(join(repo, "sub"), { recursive: true });
  const views = join(root, "brain", "views");
  mkdirSync(join(views, "p1"), { recursive: true });
  mkdirSync(join(views, "_none"), { recursive: true });
  writeFileSync(
    join(views, "projects.json"),
    JSON.stringify([
      { id: "p1", paths: [normalizePath(repo)] },
      { id: "outer", paths: [normalizePath(join(root, "work"))] },
    ]),
  );
  writeFileSync(join(views, "p1", "brief.md"), "# Brain brief — p1\n- A decision [mem-aaaaaaaaaaaa]\n");
  writeFileSync(join(views, "_none", "brief.md"), "");
  writeFileSync(
    join(views, "p1", "corrections.json"),
    JSON.stringify([
      { id: "mem-bbbbbbbbbbbb", errors: ["module mismatch"], text: "Short pattern" },
      { id: "mem-cccccccccccc", errors: ["SRE module mismatch"], text: "Unset PYTHONHOME" },
      { id: "mem-dddddddddddd", errors: ["re:(unclosed"], text: "Invalid" },
      { id: "mem-eeeeeeeeeeee", errors: ["re:no such table: \\w+"], text: "Run migrations" },
    ]),
  );
  return { home: join(root, "brain"), repo };
}

describe("v3 memory (OMP reads precompiled views)", () => {
  it("is off unless SECOND_BRAIN_V3 says on", () => {
    expect(v3Enabled({})).toBe(false);
    expect(v3Enabled({ SECOND_BRAIN_V3: "ON" })).toBe(true);
    expect(v3Enabled({ SECOND_BRAIN_V3: "off" })).toBe(false);
  });

  it("normalizes paths like the Python core", () => {
    expect(normalizePath("C:\\Users\\X\\Repo\\")).toBe("c:/users/x/repo");
    expect(normalizePath("/srv/repo/")).toBe("/srv/repo");
  });

  it("resolves the longest declared project path", () => {
    const { home: h, repo } = home();
    expect(viewKey(h, join(repo, "sub"))).toBe("p1");
    expect(viewKey(h, "/elsewhere")).toBe("_none");
    expect(viewKey(h, undefined)).toBe("_none");
  });

  it("returns the brief, or nothing for an empty or missing one", () => {
    const { home: h, repo } = home();
    expect(v3Brief(h, repo)).toContain("[mem-aaaaaaaaaaaa]");
    expect(v3Brief(h, "/elsewhere")).toBeUndefined();
    expect(v3Brief("/no/such/home", repo)).toBeUndefined();
  });

  it("matches one correction: longest pattern, regex, invalid regex ignored", () => {
    const { home: h, repo } = home();
    expect(v3Correction(h, repo, "AssertionError: SRE module mismatch")).toBe(
      "Brain correction (advisory): Unset PYTHONHOME [mem-cccccccccccc]",
    );
    expect(v3Correction(h, repo, "sqlite3.OperationalError: no such table: kb_meta")).toContain(
      "[mem-eeeeeeeeeeee]",
    );
    expect(v3Correction(h, repo, "unrelated failure")).toBeUndefined();
    expect(v3Correction(h, "/elsewhere", "SRE module mismatch")).toBeUndefined();
    expect(v3Correction(h, repo, "   ")).toBeUndefined();
  });

  it("builds a hidden custom message and writes telemetry without throwing", () => {
    const { home: h } = home();
    expect(v3BriefMessage("x")).toEqual({
      customType: "brain.v3.brief",
      content: "x",
      display: false,
      details: { v3: true, kind: "brief" },
    });
    v3Telemetry(h, "brief", "12345678", 1.234);
    const line = JSON.parse(readFileSync(join(h, "telemetry", "kb-hooks.jsonl"), "utf8").trim());
    expect(line).toMatchObject({ event: "brief", host: "omp", tokens: 2, ms: 1.23 });
    // A home whose telemetry dir cannot be created (its parent is a regular file).
    const blocked = join(h, "views", "p1", "brief.md");
    expect(() => v3Telemetry(blocked, "brief", undefined, 0)).not.toThrow();
  });
});
