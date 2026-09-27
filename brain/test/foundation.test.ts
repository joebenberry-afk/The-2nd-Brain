import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { createNote, formatNote, headline, loadNotes, parseNote, retireNote, saveNote, type Note } from "../src/notes.ts";
import { normalizeRemote, resolveProject, visibleTo } from "../src/project.ts";
import { cutToTokens, estimateTokens, slug } from "../src/util.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "brain-"));

function sample(over: Partial<Note> = {}): Note {
  return {
    id: "n-0000000001",
    kind: "gotcha",
    project: "demo",
    private: false,
    at: "2026-09-27T10:00:00Z",
    source: "agent",
    tags: ["windows"],
    errors: ["SRE module mismatch", "re:No such built-in module: node:\\w+"],
    evidence: ["scripts/a.ps1"],
    tested: true,
    body: "PYTHONHOME breaks python: clear it first\n\nDetails: the uv tree is corrupt.",
    path: "",
    ...over,
  };
}

describe("notes", () => {
  it("round-trips every field, including values that need quoting", () => {
    const note = sample({ errors: ["key: value # hash", "true", "  padded", "re:[a-z]+"], replaces: "n-1", retired: "2026-09-28T00:00:00Z", replacedBy: "n-2" });
    const back = parseNote(formatNote(note), "/x", "demo", false);
    expect({ ...back, path: "" }).toEqual({ ...note, errors: ["key: value # hash", "true", "  padded", "re:[a-z]+"] });
  });

  it("uses the first body line as headline", () => {
    expect(headline({ body: "\n# Title here\nmore" })).toBe("Title here");
  });

  it("saves under the project, moves when made private, and loads with scope from the path", () => {
    const home = tmp();
    const note = createNote(home, { text: "Use node 22.18+", project: "demo", kind: "fact" });
    expect(note.path).toBe(join(home, "notes", "demo", `${note.id}.md`));
    const moved = saveNote(home, { ...note, private: true });
    const { notes, errors } = loadNotes(home);
    expect(errors).toEqual([]);
    expect(notes).toHaveLength(1);
    expect(notes[0]?.private).toBe(true);
    expect(notes[0]?.path).toBe(moved.path);
  });

  it("reports bad files and duplicate ids without failing", () => {
    const home = tmp();
    mkdirSync(join(home, "notes", "a"), { recursive: true });
    mkdirSync(join(home, "notes", "b"), { recursive: true });
    writeFileSync(join(home, "notes", "a", "n-1.md"), formatNote(sample({ id: "n-1" })));
    writeFileSync(join(home, "notes", "b", "n-1.md"), formatNote(sample({ id: "n-1" })));
    writeFileSync(join(home, "notes", "a", "broken.md"), "no frontmatter");
    const { notes, errors } = loadNotes(home);
    expect(notes).toHaveLength(1);
    expect(errors).toHaveLength(2);
  });

  it("retires with a two-way replacement link", () => {
    const home = tmp();
    const old = createNote(home, { text: "old rule", project: "demo" });
    const next = createNote(home, { text: "new rule", project: "demo" });
    retireNote(home, old.id, next.id);
    const { notes } = loadNotes(home);
    const byId = new Map(notes.map((n) => [n.id, n]));
    expect(byId.get(old.id)?.retired).toBeTruthy();
    expect(byId.get(old.id)?.replacedBy).toBe(next.id);
    expect(byId.get(next.id)?.replaces).toBe(old.id);
    expect(() => retireNote(home, old.id)).toThrow(/already retired/);
  });

  it("reads V3-style inline lists and single quotes", () => {
    const text = "---\nid: n-9\ntags: [a, 'b c']\nkind: fact\n---\nBody";
    expect(parseNote(text, "/x", "p", false).tags).toEqual(["a", "b c"]);
    expect(readFileSync).toBeDefined();
  });
});

describe("project", () => {
  it("normalizes remotes", () => {
    expect(normalizeRemote("git@github.com:Owner/Repo.git")).toBe("github.com/owner/repo");
    expect(normalizeRemote("https://user@github.com/owner/repo/")).toBe("github.com/owner/repo");
  });

  it("resolves from BRAIN_PROJECT, projects.json paths/remotes, git remote, then folder", () => {
    const home = tmp();
    const repo = tmp();
    mkdirSync(join(repo, ".git"));
    writeFileSync(join(repo, ".git", "config"), '[core]\n\tbare = false\n[remote "origin"]\n\turl = git@github.com:me/My-App.git\n');
    mkdirSync(join(repo, "sub"));
    expect(resolveProject(home, join(repo, "sub"), {}).id).toBe("my-app");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { app: { remote: "https://github.com/me/my-app", tags: ["web"] } } }));
    expect(resolveProject(home, repo, {})).toMatchObject({ id: "app", tags: ["web"] });
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { pinned: { paths: [join(repo, "sub")] } } }));
    expect(resolveProject(home, join(repo, "sub"), {}).id).toBe("pinned");
    expect(resolveProject(home, repo, { BRAIN_PROJECT: "x" }).id).toBe("x");
    const plain = join(tmp(), "Some Folder");
    mkdirSync(plain);
    expect(resolveProject(home, plain, {}).id).toBe("some-folder");
  });

  it("scopes visibility by project and shared tags", () => {
    const project = { id: "demo", tags: ["python"], root: null };
    expect(visibleTo(sample(), project)).toBe(true);
    expect(visibleTo(sample({ project: "other" }), project)).toBe(false);
    expect(visibleTo(sample({ project: "global", tags: [] }), project)).toBe(true);
    expect(visibleTo(sample({ project: "global", tags: ["python"] }), project)).toBe(true);
    expect(visibleTo(sample({ project: "global", tags: ["rust"] }), project)).toBe(false);
    expect(visibleTo(sample({ project: "global", tags: [] }), null)).toBe(true);
  });
});

describe("util", () => {
  it("estimates and cuts to token budgets", () => {
    expect(estimateTokens("abcd")).toBe(1);
    expect(estimateTokens("abcde")).toBe(2);
    const cut = cutToTokens("x".repeat(100), 10);
    expect(cut.length).toBeLessThanOrEqual(40);
    expect(cut.endsWith("…")).toBe(true);
    expect(slug("  The 2nd Brain!! ")).toBe("the-2nd-brain");
    expect(slug("***")).toBe("default");
  });
});

describe("project remote matching through a proxy or mirror", () => {
  it("matches owner/repo when the host differs", () => {
    const home = mkdtempSync(join(tmpdir(), "brain-"));
    const repo = mkdtempSync(join(tmpdir(), "brain-"));
    mkdirSync(join(repo, ".git"));
    writeFileSync(join(repo, ".git", "config"), '[remote "origin"]\n\turl = http://proxy@127.0.0.1:9/git/Owner/Repo\n');
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { mine: { remote: "https://github.com/owner/repo" } } }));
    expect(resolveProject(home, repo, {}).id).toBe("mine");
  });
});
