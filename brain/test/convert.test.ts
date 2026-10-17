import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { convertV3 } from "../src/convert.ts";
import { createNote, loadNotes } from "../src/notes.ts";
import { visibleTo } from "../src/project.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-convert-"));

function createV3Record(
  id: string,
  opts: {
    title?: string;
    type?: string;
    scope?: string;
    project?: string;
    domains?: string[];
    status?: string;
    grade?: string;
    recorded_at?: string;
    valid_from?: string;
    superseded_at?: string;
    superseded_by?: string;
    supersedes?: string;
    evidence?: string[];
    terms?: string[];
    trigger_errors?: string[];
    edited_at?: string;
  } = {},
): string {
  const lines = ["---", `id: ${id}`, `title: "${opts.title || "Test"}"`, `type: ${opts.type || "fact"}`];

  if (opts.scope) lines.push(`scope: ${opts.scope}`);
  if (opts.project) lines.push(`project: ${opts.project}`);
  if (opts.domains && opts.domains.length > 0) {
    lines.push("domains:");
    for (const d of opts.domains) lines.push(`  - ${d}`);
  }
  if (opts.status) lines.push(`status: ${opts.status}`);
  if (opts.grade) lines.push(`grade: ${opts.grade}`);
  if (opts.recorded_at) lines.push(`recorded_at: ${opts.recorded_at}`);
  if (opts.valid_from) lines.push(`valid_from: ${opts.valid_from}`);
  if (opts.superseded_at) lines.push(`superseded_at: ${opts.superseded_at}`);
  if (opts.superseded_by) lines.push(`superseded_by: ${opts.superseded_by}`);
  if (opts.supersedes) lines.push(`supersedes: ${opts.supersedes}`);
  if (opts.edited_at) lines.push(`edited_at: ${opts.edited_at}`);
  if (opts.evidence && opts.evidence.length > 0) {
    lines.push("evidence:");
    for (const e of opts.evidence) lines.push(`  - ${e}`);
  }
  if (opts.terms && opts.terms.length > 0) {
    lines.push("terms:");
    for (const t of opts.terms) lines.push(`  - ${t}`);
  }
  if (opts.trigger_errors && opts.trigger_errors.length > 0) {
    lines.push("trigger_errors:");
    for (const e of opts.trigger_errors) lines.push(`  - ${e}`);
  }

  lines.push("---", "", "Test body");
  return lines.join("\n");
}

describe("convert", () => {
  it("converts fact type", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { type: "fact", scope: "project", project: "demo" }),
    );

    const report = convertV3(from, to);
    expect(report.written).toBe(1);

    const { notes } = loadNotes(to);
    expect(notes[0]?.kind).toBe("fact");
  });

  it("converts decision type", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { type: "decision" }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.kind).toBe("decision");
  });

  it("converts locator type to fact", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(join(from, "records", "mem-1.md"), createV3Record("mem-1", { type: "locator" }));

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.kind).toBe("fact");
  });

  it("converts correction type to gotcha", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { type: "correction" }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.kind).toBe("gotcha");
  });

  it("converts state type to note", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { type: "state" }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.kind).toBe("note");
  });

  it("converts project scope", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { scope: "project", project: "demo" }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.project).toBe("demo");
  });

  it("converts domain scope with domains to global", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { scope: "domain", domains: ["web", "typescript"] }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.project).toBe("global");
    expect(notes[0]?.tags).toEqual(["typescript", "web"]);
  });

  it("converts domain scope without domains", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { scope: "domain" }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.project).toBe("global");
  });

  it("converts global scope", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { scope: "global" }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.project).toBe("global");
  });

  it("converts valid_from as at, or recorded_at", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", {
        valid_from: "2026-09-27T10:00:00Z",
        recorded_at: "2026-09-26T00:00:00Z",
      }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.at).toBe("2026-09-27T10:00:00Z");
  });

  it("converts current+TESTED status to tested=true", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { status: "current", grade: "TESTED" }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.tested).toBe(true);
  });

  it("converts current+VERIFIED status to tested=true", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", { status: "current", grade: "VERIFIED" }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.tested).toBe(true);
  });

  it("converts superseded status to retired", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", {
        status: "superseded",
        superseded_at: "2026-09-27T15:00:00Z",
      }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.retired).toBe("2026-09-27T15:00:00Z");
  });

  it("converts terms to tags for project notes", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", {
        scope: "project",
        project: "demo",
        terms: ["typescript", "node"],
      }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.tags).toEqual(["node", "typescript"]);
  });

  it("converts evidence and trigger_errors", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", {
        evidence: ["CLAUDE.md"],
        trigger_errors: ["EADDRINUSE"],
      }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.evidence).toEqual(["CLAUDE.md"]);
    expect(notes[0]?.errors).toEqual(["EADDRINUSE"]);
  });

  it("converts private records", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records", "private"), { recursive: true });

    writeFileSync(
      join(from, "records", "private", "mem-secret.md"),
      createV3Record("mem-secret", {}),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.private).toBe(true);
  });

  it("skips records that already exist", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", {}),
    );

    convertV3(from, to);
    const firstReport = convertV3(from, to);

    expect(firstReport.skipped).toBe(1);
    expect(firstReport.written).toBe(0);
  });

  it("skips a record whose id differs only in case", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });
    createNote(to, { id: "n-abcdef0123", project: "demo", text: "Existing note" });
    writeFileSync(join(from, "records", "mem-1.md"), createV3Record("N-ABCDEF0123", {}));
    const report = convertV3(from, to);
    expect(report.written).toBe(0);
    expect(report.skipped).toBe(1);
    expect(loadNotes(to).notes.map((n) => n.id)).toEqual(["n-abcdef0123"]);
  });

  it("a dry run counts duplicates in its own batch", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records", "private"), { recursive: true });
    writeFileSync(join(from, "records", "mem-1.md"), createV3Record("mem-1", {}));
    writeFileSync(join(from, "records", "private", "mem-1.md"), createV3Record("mem-1", {}));
    const report = convertV3(from, to, { dryRun: true });
    expect(report.written).toBe(1);
    expect(report.skipped).toBe(1);
    expect(loadNotes(to).notes).toHaveLength(0);
  });

  it("reports errors for malformed records", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(join(from, "records", "bad.md"), "no frontmatter");

    const report = convertV3(from, to);
    expect(report.errors.length).toBeGreaterThan(0);
  });

  it("reports errors for records with missing id", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      `---
title: Missing ID
---
Body`,
    );

    const report = convertV3(from, to);
    expect(report.errors.some((e) => e.includes("missing id or title"))).toBe(true);
  });

  it("converts projects from project.toml", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "projects", "demo"), { recursive: true });

    writeFileSync(
      join(from, "projects", "demo", "project.toml"),
      `id = "demo"
repo_path = "/path/to/repo"
git_remote = "https://github.com/owner/demo"
domains = ["typescript", "web"]
`,
    );

    const report = convertV3(from, to);
    expect(report.projects).toBe(1);

    const projectsJson = JSON.parse(readFileSync(join(to, "projects.json"), "utf8"));
    expect(projectsJson.projects.demo).toMatchObject({
      paths: ["/path/to/repo"],
      remote: "https://github.com/owner/demo",
      tags: ["typescript", "web"],
    });
  });

  it("does not overwrite existing projects", () => {
    const from = tmp();
    const to = tmp();

    // Create existing project in to
    writeFileSync(
      join(to, "projects.json"),
      JSON.stringify({ projects: { demo: { remote: "old" } } }),
    );

    mkdirSync(join(from, "projects", "demo"), { recursive: true });
    writeFileSync(
      join(from, "projects", "demo", "project.toml"),
      `id = "demo"
repo_path = "/new/path"
git_remote = "https://github.com/owner/new"
`,
    );

    convertV3(from, to);

    const projectsJson = JSON.parse(readFileSync(join(to, "projects.json"), "utf8"));
    expect(projectsJson.projects.demo.remote).toBe("old");
  });

  it("dryRun computes report without writing", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", {}),
    );

    const report = convertV3(from, to, { dryRun: true });
    expect(report.written).toBe(1);

    const { notes } = loadNotes(to);
    expect(notes).toHaveLength(0);
  });

  it("converts superseded_by and supersedes links", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });

    writeFileSync(
      join(from, "records", "mem-1.md"),
      createV3Record("mem-1", {
        supersedes: "mem-0",
        status: "superseded",
        superseded_by: "mem-2",
      }),
    );

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes[0]?.replaces).toBe("mem-0");
    expect(notes[0]?.replacedBy).toBe("mem-2");
  });
});

describe("convert: a V3 project named Global (review regression)", () => {
  it("keeps its notes in their own project, keeps projects.json keys, and drops unusable error patterns", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records", "private"), { recursive: true });
    mkdirSync(join(from, "projects", "other"), { recursive: true });
    writeFileSync(join(from, "records", "mem-g.md"), createV3Record("mem-g", { scope: "project", project: "Global", trigger_errors: ["Exit code 1", "re:(a+)+b", "specific failure text"] }));
    writeFileSync(join(from, "records", "private", "mem-gp.md"), createV3Record("mem-gp", { scope: "project", project: "Global" }));
    writeFileSync(join(from, "projects", "other", "project.toml"), `id = "other"\n`);
    writeFileSync(join(to, "projects.json"), JSON.stringify({ version: 2, projects: { keep: {} } }));

    const report = convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes.map((n) => [n.id, n.project]).sort()).toEqual([["mem-g", "global-project"], ["mem-gp", "global-project"]]);
    const other = { id: "other", tags: [], root: null };
    expect(notes.some((n) => visibleTo(n, other))).toBe(false);
    expect(JSON.parse(readFileSync(join(to, "projects.json"), "utf8"))).toMatchObject({ version: 2, projects: { keep: {}, other: {} } });
    expect(notes.find((n) => n.id === "mem-g")?.errors).toEqual(["specific failure text"]);
    expect(report.errors).toHaveLength(2);
    expect(report.errors.join("\n")).toMatch(/Exit code 1[\s\S]*\(a\+\)\+b/);
  });

  it("files a device-named V3 project under <name>-project", () => {
    const from = tmp();
    const to = tmp();
    mkdirSync(join(from, "records"), { recursive: true });
    mkdirSync(join(from, "projects", "aux"), { recursive: true });
    writeFileSync(join(from, "records", "mem-1.md"), createV3Record("mem-1", { scope: "project", project: "aux" }));
    writeFileSync(join(from, "records", "mem-2.md"), createV3Record("mem-2", { scope: "global" }));
    writeFileSync(join(from, "projects", "aux", "project.toml"), `id = "aux"\n`);

    convertV3(from, to);
    const { notes } = loadNotes(to);
    expect(notes.find((n) => n.id === "mem-1")?.project).toBe("aux-project");
    expect(existsSync(join(to, "notes", "aux-project"))).toBe(true);
    expect(notes.find((n) => n.id === "mem-2")?.project).toBe("global");
    expect(Object.keys(JSON.parse(readFileSync(join(to, "projects.json"), "utf8")).projects)).toEqual(["aux-project"]);
  });
});
