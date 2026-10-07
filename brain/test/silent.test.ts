import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, normalize } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import type { ToolEvent } from "../src/capture.ts";
import { mineSilentRecalls, type SilentContext, type SilentRecall } from "../src/silent.ts";
import { normalizePath } from "../src/project.ts";

const root = mkdtempSync(join(tmpdir(), "brain-silent-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));
mkdirSync(join(root, "docs"));
mkdirSync(join(root, "src"));
for (const file of ["docs/plan.md", "docs/done.md", "AGENTS.md", "src/a.ts"]) writeFileSync(join(root, file), "x");

const T0 = Date.parse("2026-10-01T10:00:00Z");
const recall = (session: string, query: string, offsetS = 0): SilentRecall => ({ at: T0 + offsetS * 1000, project: "p", session, query });
const read = (path: string, offsetS: number, extra: Partial<ToolEvent> = {}): ToolEvent => ({ v: 1, at: new Date(T0 + offsetS * 1000).toISOString(), session: "s", cwd: root, tool: "read", path, ok: true, ...extra });
const ctx = (registered: string[] = []): SilentContext => ({ root: () => root, registered: () => new Set(registered.map(normalizePath)), exclude: [] });

describe("mineSilentRecalls", () => {
  it("groups distinct silent queries answered by one unregistered doc across sessions, ignoring context files, registered docs and outside paths", () => {
    const events = new Map([
      ["s1", [read("AGENTS.md", 1), read(join(tmpdir(), "elsewhere.md"), 2), read("docs/done.md", 3), read("docs/plan.md", 4), { ...read("x", 5), tool: "brain_note" }]],
      ["s2", [read(normalize(join(root, "docs/plan.md")), 2)]],
      ["s3", [read("docs/plan.md", 2)]],
    ]);
    const recalls = [recall("s1", "how is x planned"), recall("s2", "where is the plan"), recall("s3", "single other query"), recall("s3", "single other query", 3600)];
    const { examined, cases } = mineSilentRecalls(recalls, events, ctx([join(root, "docs/done.md")]));
    expect(examined).toBe(4);
    expect(cases).toHaveLength(1);
    expect(cases[0]).toMatchObject({ path: "docs/plan.md", kind: "doc", silent: 3, sessions: 3, noted: 1, queries: ["how is x planned", "where is the plan", "single other query"] });
  });

  it("reports a source file for a repeated silent query, and nothing when a read falls outside the window or nothing recurs", () => {
    const events = new Map([["s1", [read("skill://ponytail", 4), read("src/a.ts:10-40", 5)]], ["s2", [read("src/a.ts", 5)]], ["s3", [read("docs/plan.md", 11 * 60)]]]);
    const { cases } = mineSilentRecalls([recall("s1", "Why  the thing"), recall("s2", "why the thing"), recall("s3", "late")], events, ctx());
    expect(cases).toHaveLength(1);
    expect(cases[0]).toMatchObject({ path: "src/a.ts", kind: "source", silent: 2, sessions: 2, queries: ["Why  the thing", "why the thing"] });
    const late = new Map([["s3", [read("docs/plan.md", 11 * 60)]], ["s4", [read("docs/plan.md", 11 * 60)]]]);
    expect(mineSilentRecalls([recall("s3", "late"), recall("s4", "late")], late, ctx()).cases).toMatchObject([{ path: undefined, kind: "none", silent: 2, sessions: 2 }]);
  });
});
