import * as notesModule from "../src/notes.ts";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { draftKit, findKit, KIT_BUDGET, kitsDir, kitsFor, loadKits, KitError } from "../src/kits.ts";
import { createNote, loadNotes } from "../src/notes.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-kits-"));

describe("kits", () => {
  it("kitsDir returns the kits directory", () => {
    const home = "/home/test";
    expect(kitsDir(home)).toBe(join(home, "kits"));
  });

  it("loadKits returns empty array when kits dir does not exist", () => {
    const home = tmp();
    expect(loadKits(home)).toEqual([]);
  });

  it("loadKits reads SKILL.md files with frontmatter", () => {
    const home = tmp();
    const kitPath = join(home, "kits", "my-kit");
    mkdirSync(kitPath, { recursive: true });
    writeFileSync(
      join(kitPath, "SKILL.md"),
      `---
name: my-kit
description: "Test kit for projects"
tags:
  - typescript
  - web
---

# My Kit

This is the body.`,
    );

    const kits = loadKits(home);
    expect(kits).toHaveLength(1);
    expect(kits[0]).toMatchObject({
      name: "my-kit",
      description: "Test kit for projects",
      tags: ["typescript", "web"],
    });
    expect(kits[0]?.body).toContain("This is the body");
  });

  it("loadKits skips kits without description", () => {
    const home = tmp();
    const kitPath = join(home, "kits", "no-desc");
    mkdirSync(kitPath, { recursive: true });
    writeFileSync(
      join(kitPath, "SKILL.md"),
      `---
name: no-desc
tags: [a]
---

Body`,
    );

    expect(loadKits(home)).toHaveLength(0);
  });

  it("loadKits uses folder name when name is missing", () => {
    const home = tmp();
    const kitPath = join(home, "kits", "folder-name");
    mkdirSync(kitPath, { recursive: true });
    writeFileSync(
      join(kitPath, "SKILL.md"),
      `---
description: "Kit from folder"
---

Body`,
    );

    const kits = loadKits(home);
    expect(kits[0]?.name).toBe("folder-name");
  });

  it("loadKits sorts by name", () => {
    const home = tmp();
    for (const name of ["zebra", "apple", "banana"]) {
      const kitPath = join(home, "kits", name);
      mkdirSync(kitPath, { recursive: true });
      writeFileSync(
        join(kitPath, "SKILL.md"),
        `---
description: "Kit ${name}"
---

Body`,
      );
    }

    const kits = loadKits(home);
    expect(kits.map((k) => k.name)).toEqual(["apple", "banana", "zebra"]);
  });

  it("findKit returns matching kit or undefined", () => {
    const kits = [
      { name: "kit1", description: "A", tags: [], path: "", body: "" },
      { name: "kit2", description: "B", tags: [], path: "", body: "" },
    ];

    expect(findKit(kits, "kit1")).toBeDefined();
    expect(findKit(kits, "kit3")).toBeUndefined();
  });

  it("kitsFor filters by tags", () => {
    const kits = [
      { name: "web", description: "A", tags: ["typescript", "web"], path: "", body: "" },
      { name: "cli", description: "B", tags: ["rust", "cli"], path: "", body: "" },
      { name: "both", description: "C", tags: ["typescript", "cli"], path: "", body: "" },
    ];

    const project = { id: "demo", tags: ["typescript", "python"], root: null };
    const matching = kitsFor(kits, project);
    expect(matching.map((k) => k.name)).toEqual(["web", "both"]);
  });

  it("draftKit refuses when SKILL.md already exists", () => {
    const home = tmp();
    const kitPath = join(home, "kits", "test-kit");
    mkdirSync(kitPath, { recursive: true });
    writeFileSync(join(kitPath, "SKILL.md"), "---\n---\nBody");

    expect(() => draftKit(home, "test-kit", "demo", [], [])).toThrow(KitError);
  });

  it("draftKit creates a kit with correct structure and sections", () => {
    const home = tmp();

    // Create some notes
    createNote(home, {
      text: "Use TypeScript\n\nFor type safety.",
      project: "demo",
      kind: "decision",
    });
    createNote(home, {
      text: "Run tests\n\nExecute vitest",
      project: "demo",
      kind: "procedure",
    });
    createNote(home, {
      text: "Port mismatch\n\nListen on correct port",
      project: "demo",
      kind: "gotcha",
      errors: ["EADDRINUSE"],
    });

    const { notes } = loadNotes(home);
    const kit = draftKit(home, "My Kit", "demo", notes, ["web"]);

    expect(kit.name).toBe("my-kit");
    expect(kit.tags).toContain("web");
    expect(kit.body).toContain("## When to use");
    expect(kit.body).toContain("## Stack and why");
    expect(kit.body).toContain("## Scaffold");
    expect(kit.body).toContain("## Gotchas");
    expect(kit.body).toContain("## MVP done when");
  });

  it("draftKit includes decision headlines with ids", () => {
    const home = tmp();

    const decision = createNote(home, {
      text: "Use TypeScript",
      project: "demo",
      kind: "decision",
    });

    const { notes } = loadNotes(home);
    const kit = draftKit(home, "test", "demo", notes);

    expect(kit.body).toContain("Use TypeScript");
    expect(kit.body).toContain(`(${decision.id})`);
  });

  it("draftKit respects budget and stops adding items", () => {
    const home = tmp();

    // Create many notes to exceed budget
    for (let i = 0; i < 20; i++) {
      createNote(home, {
        text: `Decision ${i}`,
        project: "demo",
        kind: "decision",
      });
    }

    const { notes } = loadNotes(home);
    const kit = draftKit(home, "test", "demo", notes);

    // Check that the kit doesn't exceed budget (600 tokens = ~2400 chars)
    const tokens = Math.ceil(kit.body.length / 4);
    expect(tokens).toBeLessThanOrEqual(KIT_BUDGET);
  });

  it("draftKit numbers procedures but bullets other sections", () => {
    const home = tmp();

    createNote(home, {
      text: "First decision",
      project: "demo",
      kind: "decision",
    });
    createNote(home, {
      text: "First procedure",
      project: "demo",
      kind: "procedure",
    });

    const { notes } = loadNotes(home);
    const kit = draftKit(home, "test", "demo", notes);

    expect(kit.body).toContain("1. First procedure");
    expect(kit.body).toContain("- First decision");
  });

  it("draftKit includes error symptoms for gotchas", () => {
    const home = tmp();

    createNote(home, {
      text: "Python issue",
      project: "demo",
      kind: "gotcha",
      errors: ["AssertionError: SRE module mismatch"],
    });

    const { notes } = loadNotes(home);
    const kit = draftKit(home, "test", "demo", notes);

    expect(kit.body).toContain("symptom:");
    expect(kit.body).toContain("AssertionError: SRE module mismatch");
  });

  it("draftKit skips retired notes", () => {
    const home = tmp();

    createNote(home, {
      text: "Active decision",
      project: "demo",
      kind: "decision",
    });
    const retired = createNote(home, {
      text: "Retired decision",
      project: "demo",
      kind: "decision",
    });

    let { notes } = loadNotes(home);
    notes = notes.map((n) => (n.id === retired.id ? { ...n, retired: "2026-09-27T00:00:00Z" } : n));

    const kit = draftKit(home, "test", "demo", notes);
    expect(kit.body).toContain("Active decision");
    expect(kit.body).not.toContain("Retired decision");
  });

  it("draftKit limits items per section", () => {
    const home = tmp();

    // Create 10 decisions
    for (let i = 0; i < 10; i++) {
      createNote(home, {
        text: `Decision ${i}`,
        project: "demo",
        kind: "decision",
      });
    }

    const { notes } = loadNotes(home);
    const kit = draftKit(home, "test", "demo", notes);

    // Decisions are limited to 6
    const lines = kit.body.split("\n");
    const decisionCount = lines.filter((l) => l.match(/^- Decision \d+/)).length;
    expect(decisionCount).toBeLessThanOrEqual(6);
  });

  it("draftKit handles sections with no items", () => {
    const home = tmp();

    // Create only decisions, no procedures or gotchas
    createNote(home, {
      text: "A decision",
      project: "demo",
      kind: "decision",
    });

    const { notes } = loadNotes(home);
    const kit = draftKit(home, "test", "demo", notes);

    expect(kit.body).toContain("## Scaffold");
    expect(kit.body).toContain("- none recorded yet");
  });

  it("draftKit sorts decisions and procedures by newest first", () => {
    const home = tmp();

    const old = createNote(home, {
      text: "Old decision",
      project: "demo",
      kind: "decision",
      source: "user",
    });
    const newer = createNote(home, {
      text: "Newer decision",
      project: "demo",
      kind: "decision",
      source: "user",
    });

    let { notes } = loadNotes(home);
    notes = notes.map((n) => {
      if (n.id === newer.id) return { ...n, at: "2026-09-27T12:00:00Z" };
      if (n.id === old.id) return { ...n, at: "2026-09-27T10:00:00Z" };
      return n;
    });

    const kit = draftKit(home, "test", "demo", notes);

    // Newer should come first
    const indexNewer = kit.body.indexOf("Newer decision");
    const indexOlder = kit.body.indexOf("Old decision");
    expect(indexNewer).toBeLessThan(indexOlder);
  });

  it("draftKit lists tested gotchas first, then the newest", () => {
    const home = tmp();
    const { saveNote } = notesModule;
    const older = createNote(home, { text: "Older untested gotcha", project: "demo", kind: "gotcha" });
    saveNote(home, { ...older, at: "2026-01-01T00:00:00Z" });
    const newer = createNote(home, { text: "Newer untested gotcha", project: "demo", kind: "gotcha" });
    saveNote(home, { ...newer, at: "2026-06-01T00:00:00Z" });
    const tested = createNote(home, { text: "Old tested gotcha", project: "demo", kind: "gotcha", tested: true, errors: ["boom"] });
    saveNote(home, { ...tested, at: "2025-01-01T00:00:00Z" });
    const kit = draftKit(home, "test", "demo", loadNotes(home).notes);
    const order = ["Old tested gotcha", "Newer untested gotcha", "Older untested gotcha"].map((h) => kit.body.indexOf(h));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(kit.body).toContain("- Old tested gotcha — symptom: `boom`");
  });
});
