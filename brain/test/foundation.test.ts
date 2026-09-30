import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { createNote, differentBody, formatNote, headline, loadNotes, parseNote, retireNote, saveNote, staleEvidence, type Note } from "../src/notes.ts";
import { addProjectDoc, addProjectTag, loadProjects, normalizePath, normalizeRemote, projectById, resolveProject, visibleTo } from "../src/project.ts";
import { anchorSection, docAnswer, projectDocs } from "../src/docs.ts";
import { staleHere } from "../src/search.ts";
import { shareNote } from "../src/sync.ts";
import { cutToTokens, estimateTokens, retrying, slug } from "../src/util.ts";
import { workText } from "../src/work.ts";

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
    const note = sample({ errors: ["key: value # hash", "true", "  padded", "re:[a-z]+"], host: "omp", replaces: "n-1", retired: "2026-09-28T00:00:00Z", replacedBy: "n-2" });
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
    expect(parseNote(text, "/x", "p", false).tags).toEqual(["a", "b-c"]);
    expect(readFileSync).toBeDefined();
  });
});

describe("lossless bodies and cached file truth", () => {
  it("compares complete scrubbed bodies without discarding case or added details", () => {
    const home = tmp();
    const text = "Deployment rule\n\nUse port 3000; password=example-secret";
    const stored = createNote(home, { text, project: "demo" });
    expect(differentBody(stored, "  Deployment rule\r\n Use   port 3000; password=example-secret  ")).toBe(false);
    expect(differentBody(stored, text.replace("3000", "4000"))).toBe(true);
    expect(differentBody(stored, text.replace("Use", "use"))).toBe(true);
    expect(differentBody(stored, "Deployment rule")).toBe(true);
    expect(differentBody(stored, text + "\nRestart after editing.")).toBe(true);
  });

  it("sees immediate external same-size edits, additions and deletions", () => {
    const home = tmp();
    const original = createNote(home, { text: "Alpha rule", project: "demo" });
    expect(loadNotes(home).notes[0]?.body).toBe("Alpha rule");
    const before = statSync(original.path);
    writeFileSync(original.path, formatNote({ ...original, body: "Bravo rule" }));
    utimesSync(original.path, before.atimeMs / 1000, before.mtimeMs / 1000);
    expect(loadNotes(home).notes[0]?.body).toBe("Bravo rule");

    const added = join(home, "notes", "other", "private", "external.md");
    mkdirSync(join(home, "notes", "other", "private"), { recursive: true });
    writeFileSync(added, formatNote(sample({ id: "external", body: "External note" })));
    expect(loadNotes(home).notes.find((n) => n.id === "external")).toMatchObject({ body: "External note", project: "other", private: true });
    rmSync(original.path);
    expect(loadNotes(home).notes.map((n) => n.id)).toEqual(["external"]);
    rmSync(join(home, "notes"), { recursive: true });
    expect(loadNotes(home)).toEqual({ notes: [], errors: [] });
  });

  it("never caches unsaved caller edits and invalidates its own writes, moves and retirement", () => {
    const home = tmp();
    const first = createNote(home, { text: "Original rule", project: "demo", tags: ["node"] });
    const loaded = loadNotes(home).notes[0]!;
    loaded.body = "Not saved";
    loaded.tags.push("unsaved");
    expect(loadNotes(home).notes[0]).toMatchObject({ body: "Original rule", tags: ["node"] });
    const moved = saveNote(home, { ...first, private: true, body: "Private rule" });
    expect(loadNotes(home).notes).toEqual([moved]);
    const next = createNote(home, { text: "Replacement", project: "demo" });
    retireNote(home, first.id, next.id);
    expect(loadNotes(home).notes.find((n) => n.id === first.id)).toMatchObject({ replacedBy: next.id, retired: expect.any(String) });
  });

  it("reports external corruption and recovers after repair", () => {
    const home = tmp();
    const original = createNote(home, { text: "Safe rule", project: "demo" });
    loadNotes(home);
    writeFileSync(original.path, "invalid frontmatter");
    const broken = loadNotes(home);
    expect(broken.notes).toEqual([]);
    expect(broken.errors).toEqual([expect.stringContaining("missing frontmatter")]);
    writeFileSync(original.path, formatNote(original));
    expect(loadNotes(home)).toEqual({ notes: [original], errors: [] });
  });
});

describe("file evidence", () => {
  it("is stale only when all file references are missing from all roots", () => {
    const home = tmp();
    const project = tmp();
    writeFileSync(join(home, "present.md"), "evidence");
    const base = sample({ evidence: ["missing.ts", "present.md:1-4", "commit:abcdef0"] });
    expect(staleEvidence(base, [project, home])).toBe(false);
    expect(staleEvidence(base, [project])).toBe(true);
    expect(staleEvidence({ ...base, evidence: [join(home, "present.md")] }, [project])).toBe(false);
    expect(staleEvidence({ ...base, evidence: ["missing.ts", "events:missing.jsonl"] }, [home])).toBe(true);
    expect(staleEvidence({ ...base, evidence: ["present.md (checked locally)"] }, [home])).toBe(false);
    for (const entry of ["present.md:1:4", "present.md#L3", "present.md#L3-L9", "present.md:sym", "present.md(1,4)", join(home, "present.md:2:1")]) {
      expect(staleEvidence({ ...base, evidence: [entry] }, [home])).toBe(false);
    }
    expect(staleEvidence({ ...base, evidence: ["missing.md:1:4"] }, [home])).toBe(true);
  });

  it.each([[], ["events:missing.jsonl"], ["commit:abc1234"], ["https://example.test/missing.ts"], ["session:local/123"], ["owner confirmed this"], ["../outside.md"], ["src/../../outside.md"], ["..\\outside.md"]])("does not call non-file or escaping evidence stale: %j", (...evidence: string[]) => {
    expect(staleEvidence(sample({ evidence }), [tmp()])).toBe(false);
  });

  it("invalidates evidence results after own writes or an external note change", () => {
    const home = tmp();
    const saved = createNote(home, { text: "Check source", project: "demo", evidence: ["proof.md"] });
    const [loaded] = loadNotes(home).notes;
    expect(staleEvidence(loaded!, [home])).toBe(true);
    writeFileSync(join(home, "proof.md"), "proof");
    saveNote(home, saved);
    expect(staleEvidence(saved, [home])).toBe(false);
    loadNotes(home);
    rmSync(join(home, "proof.md"));
    writeFileSync(saved.path, formatNote({ ...saved, body: "Check revised source" }));
    const [edited] = loadNotes(home).notes;
    expect(staleEvidence(edited!, [home])).toBe(true);
  });
});

describe("project", () => {
  it("refuses credential tags before writing projects", () => {
    const home = tmp();
    const tag = "ghp_" + "x".repeat(30);
    expect(() => addProjectTag(home, "demo", tag)).toThrow(/tag.*credential/i);
    expect(existsSync(join(home, "projects.json"))).toBe(false);
  });

  it("matches registered paths through directory junctions in either direction", () => {
    const home = tmp();
    const root = tmp();
    const target = join(root, "repository");
    const link = join(root, "shortcut");
    mkdirSync(join(target, "sub"), { recursive: true });
    symlinkSync(target, link, "junction");
    for (const [registered, cwd] of [[target, link], [link, target]] as const) {
      writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { app: { paths: [registered] } } }));
      expect(resolveProject(home, join(cwd, "sub"), {}).id).toBe("app");
    }
  });

  it("resolves a not-yet-existing directory under a junction through its nearest existing ancestor", () => {
    const home = tmp();
    const root = tmp();
    const target = join(root, "repository");
    const link = join(root, "shortcut");
    mkdirSync(target, { recursive: true });
    symlinkSync(target, link, "junction");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { app: { paths: [link] } } }));
    expect(resolveProject(home, join(link, "missing", "deeper"), {}).id).toBe("app");
    expect(resolveProject(home, join(target, "missing"), {}).id).toBe("app");
  });

  it("keeps lexical matching for missing registered paths", () => {
    const home = tmp();
    const missing = join(home, "not-created");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { app: { paths: [missing] } } }));
    expect(resolveProject(home, join(missing, "sub"), {}).id).toBe("app");
  });

  it("normalizes forward-slash UNC paths like backslash UNC paths", () => {
    expect(normalizePath("//NAS/Share/App/")).toBe("//nas/share/app");
    expect(normalizePath(String.raw`\\NAS\Share\App`)).toBe(normalizePath("//NAS/Share/App"));
  });

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

  it("resolves a subfolder of a known plain folder to that folder, id and root", () => {
    const home = tmp();
    const plain = join(tmp(), "Absolute Laya");
    mkdirSync(join(plain, "scripts", "deep"), { recursive: true });
    expect(resolveProject(home, join(plain, "scripts"), {}).id).toBe("scripts");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { "absolute-laya": {} } }));
    expect(resolveProject(home, join(plain, "scripts", "deep"), {})).toMatchObject({ id: "absolute-laya", root: plain });
    expect(resolveProject(home, plain, {})).toMatchObject({ id: "absolute-laya", root: plain });
  });

  it("keeps a declared non-git folder as the root of a git repo inside it, so its docs resolve", () => {
    const home = tmp();
    const outer = join(tmp(), "Upscaler");
    const inner = join(outer, "Upscaler");
    mkdirSync(join(inner, ".git"), { recursive: true });
    mkdirSync(join(inner, "tools"));
    writeFileSync(join(inner, "PLAN.md"), "# Plan\n");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { up: { paths: [outer], docs: ["Upscaler/PLAN.md"] } } }));
    const project = resolveProject(home, join(inner, "tools"), {});
    expect(project).toMatchObject({ id: "up", root: inner, docRoot: outer });
    expect(projectDocs(home, project)).toEqual([join(inner, "PLAN.md")]);
  });

  it("keeps a git repo inside a declared folder as the root for anchors, evidence and added docs", () => {
    const home = tmp();
    const outer = join(tmp(), "Up");
    const inner = join(outer, "Upscaler");
    mkdirSync(join(inner, ".git"), { recursive: true });
    mkdirSync(join(inner, "docs"));
    mkdirSync(join(inner, "src"));
    writeFileSync(join(inner, "docs", "PLAN.md"), "# Plan\n\n## Phase two\n\nGovernor.\n");
    writeFileSync(join(inner, "src", "g.rs"), "");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { up: { paths: [outer] } } }));
    const project = resolveProject(home, inner, {});
    expect(anchorSection(project.root!, "docs/PLAN.md#phase-two")).toBeDefined();
    expect(staleHere(sample({ project: "up", evidence: ["src/g.rs"] }), project, home)).toBe(false);
    expect(addProjectDoc(home, project, "docs/PLAN.md")).toBe(true);
    expect(loadProjects(home).up?.docs).toEqual(["Upscaler/docs/PLAN.md"]);
    for (const cwd of [inner, outer]) expect(projectDocs(home, resolveProject(home, cwd, {}))).toEqual([join(inner, "docs", "PLAN.md")]);
  });

  it("resolves anchors, evidence and doc answers against the declared folder from a repo inside it", () => {
    const home = tmp();
    const outer = join(tmp(), "Up");
    const inner = join(outer, "Upscaler");
    mkdirSync(join(inner, ".git"), { recursive: true });
    mkdirSync(join(inner, "docs"));
    writeFileSync(join(inner, "docs", "PLAN.md"), "# Plan\n\n## Phase two\n\nGovernor.\n");
    writeFileSync(join(outer, "RESEARCH.md"), "# R\n\n## Findings\n\nTiles overlap.\n");
    writeFileSync(join(outer, "notes.txt"), "x");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { up: { paths: [outer], docs: ["Upscaler/docs/PLAN.md", "RESEARCH.md"] } } }));
    const project = resolveProject(home, inner, {});
    const text = workText({ project: "up", at: new Date().toISOString(), autoAt: "", text: "Goal: g\nSee: Upscaler/docs/PLAN.md#phase-two\nSee: RESEARCH.md#findings", auto: "", path: "" }, project.root, project.docRoot);
    expect(text).toContain("Governor.");
    expect(text).toContain("Tiles overlap.");
    expect(text).not.toContain("anchor missing");
    expect(docAnswer(home, project, "findings tiles")?.text.startsWith("RESEARCH.md › Findings")).toBe(true);
    // Spelled from the repo, so it opens from the agent's cwd; a doc outside the repo, against the folder.
    const answer = docAnswer(home, project, "phase two governor");
    expect(answer?.text.startsWith("docs/PLAN.md › Phase two")).toBe(true);
    expect(existsSync(join(project.root!, answer!.path))).toBe(true);
    expect(staleHere(sample({ project: "up", evidence: ["notes.txt"] }), project, home)).toBe(false);
  });

  it("resolves a registered doc against the declared folder before a same-named one in a repo inside it", () => {
    const home = tmp();
    const outer = tmp();
    const app = join(outer, "app");
    mkdirSync(join(app, ".git"), { recursive: true });
    writeFileSync(join(outer, "PLAN.md"), "# Plan\n\n## Goals\n\nzebras\n");
    writeFileSync(join(app, "PLAN.md"), "# App plan\n\n## Goals\n\ngiraffes\n");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { proj: { paths: [outer], docs: ["PLAN.md"] } } }));
    const project = resolveProject(home, app, {});
    expect(projectDocs(home, project)).toEqual([join(outer, "PLAN.md")]);
    // A See: anchor names the doc recall pointed to, not the repo's same-named file.
    const answer = docAnswer(home, project, "goals zebras");
    expect(answer?.text).toBe("PLAN.md › Goals (line 3)");
    const work = { project: "proj", at: new Date().toISOString(), autoAt: "", text: `Goal: g\nSee: ${answer!.path}#goals`, auto: "", path: "" };
    expect(workText(work, project.root, project.docRoot, projectDocs(home, project))).toContain("zebras");
    // An unregistered doc stays the repo's own.
    expect(workText({ ...work, text: "Goal: g\nSee: PLAN.md#goals" }, project.root, project.docRoot, [])).toContain("giraffes");
    expect(addProjectDoc(home, project, "PLAN.md")).toBe(true);
    expect(loadProjects(home).proj?.docs).toEqual(["PLAN.md", "app/PLAN.md"]);
    expect(addProjectDoc(home, project, "PLAN.md")).toBe(false);
  });

  it("stores a doc added in a linked worktree of a declared checkout as the checkout's own path", () => {
    const home = tmp();
    const main = join(tmp(), "mainrepo");
    mkdirSync(main);
    const git = (...args: string[]) => expect(spawnSync("git", ["-c", "user.email=a@b", "-c", "user.name=n", ...args], { cwd: main, encoding: "utf8" }).status).toBe(0);
    git("init", "-q");
    git("commit", "-q", "--allow-empty", "-m", "init");
    git("worktree", "add", "-q", join(".claude", "worktrees", "feat-x"));
    const worktree = join(main, ".claude", "worktrees", "feat-x");
    mkdirSync(join(worktree, "docs"));
    writeFileSync(join(worktree, "docs", "NEW.md"), "# New\n");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { mainrepo: { paths: [main] } } }));
    const project = resolveProject(home, worktree, {});
    expect(project).toMatchObject({ id: "mainrepo", root: worktree });
    expect(project.docRoot).toBeUndefined();
    expect(addProjectDoc(home, project, "docs/NEW.md")).toBe(true);
    expect(loadProjects(home).mainrepo?.docs).toEqual(["docs/NEW.md"]);
  });

  it("stores a doc added in a worktree of a repo inside a declared folder against the declared folder", () => {
    const home = tmp();
    const outer = tmp();
    const app = join(outer, "app");
    mkdirSync(app);
    const git = (...args: string[]) => expect(spawnSync("git", ["-c", "user.email=a@b", "-c", "user.name=n", ...args], { cwd: app, encoding: "utf8" }).status).toBe(0);
    git("init", "-q");
    mkdirSync(join(app, "docs"));
    writeFileSync(join(app, "docs", "PLAN.md"), "# Plan\n\n## Status\n\nmain says: old status\n");
    git("add", "docs/PLAN.md");
    git("commit", "-q", "-m", "init");
    git("worktree", "add", "-q", join(".claude", "worktrees", "x"));
    const worktree = join(app, ".claude", "worktrees", "x");
    writeFileSync(join(worktree, "docs", "PLAN.md"), "# Plan\n\n## Status\n\nworktree says: new status\n");
    writeFileSync(join(worktree, "docs", "NEW.md"), "# New\n\n## Spec\n\nbrand new spec\n");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { proj: { paths: [outer], docs: ["app/docs/PLAN.md"] } } }));
    const project = resolveProject(home, worktree, {});
    expect(project).toMatchObject({ id: "proj", root: worktree, docRoot: outer });
    expect(addProjectDoc(home, project, "docs/NEW.md")).toBe(true);
    expect(loadProjects(home).proj?.docs).toEqual(["app/docs/PLAN.md", "app/docs/NEW.md"]);
    expect(addProjectDoc(home, project, "docs/PLAN.md")).toBe(false);
    // The worktree reads its own copies: the edited plan and the doc that exists only there.
    expect(projectDocs(home, project)).toEqual([join(worktree, "docs", "PLAN.md"), join(worktree, "docs", "NEW.md")]);
    const work = { project: "proj", at: new Date().toISOString(), autoAt: "", text: "Goal: g\nSee: app/docs/PLAN.md#status\nSee: app/docs/NEW.md#spec", auto: "", path: "" };
    const shown = workText(work, project.root, project.docRoot, projectDocs(home, project));
    expect(shown).toContain("worktree says");
    expect(shown).toContain("brand new spec");
    expect(shown).not.toContain("main says");
    expect(shown).not.toContain("anchor missing");
    expect(docAnswer(home, project, "spec brand new")?.path).toBe("docs/NEW.md");
    // A heading the worktree's copy no longer has is missing, however the anchor is spelled: never main's.
    writeFileSync(join(worktree, "docs", "PLAN.md"), "# Plan\n\n## State\n\nworktree says: new status\n");
    for (const see of ["app/docs/PLAN.md#status", "docs/PLAN.md#status"]) {
      const gone = workText({ ...work, text: `Goal: g\nSee: ${see}` }, project.root, project.docRoot, projectDocs(home, project));
      expect(gone).not.toContain("main says");
      expect(gone).toContain(`anchor missing: ${see}`);
    }
    // The main checkout keeps reading its own copy.
    const main = resolveProject(home, app, {});
    expect(projectDocs(home, main)).toEqual([join(app, "docs", "PLAN.md")]);
    expect(workText(work, main.root, main.docRoot, projectDocs(home, main))).toContain("main says");
  });

  it("gives a project named explicitly its declared folder as root", () => {
    const home = tmp();
    const dir = tmp();
    mkdirSync(join(dir, "docs"));
    mkdirSync(join(dir, "sub"));
    writeFileSync(join(dir, "docs", "X.md"), "# X\n");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { p: { paths: [dir], docs: ["docs/X.md"] } } }));
    const project = projectById(home, "p", join(dir, "sub"));
    expect(project.root).toBe(dir);
    expect(projectDocs(home, project)).toEqual([join(dir, "docs", "X.md")]);
    expect(projectById(home, "other", join(dir, "sub")).root).toBeNull();
  });

  it("does not adopt an unregistered parent folder that merely has notes", () => {
    const home = tmp();
    const parent = join(tmp(), "parent");
    mkdirSync(join(parent, "child"), { recursive: true });
    mkdirSync(join(home, "notes", "parent"), { recursive: true });
    expect(resolveProject(home, join(parent, "child"), {}).id).toBe("child");
  });

  it("never walks up to the home folder, even when it is registered", () => {
    const home = tmp();
    const owner = join(tmp(), "owner");
    mkdirSync(join(owner, "AI-Knowledge"), { recursive: true });
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { owner: {} } }));
    const saved = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
    process.env.HOME = owner;
    process.env.USERPROFILE = owner;
    try {
      expect(resolveProject(home, join(owner, "AI-Knowledge"), {}).id).toBe("ai-knowledge");
    } finally {
      for (const [key, value] of Object.entries(saved)) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
    }
  });

  it("names a linked worktree of a repo without a remote after the main checkout", () => {
    const home = tmp();
    const main = join(tmp(), "projA");
    mkdirSync(main);
    const git = (...args: string[]) => expect(spawnSync("git", ["-c", "user.email=a@b", "-c", "user.name=n", ...args], { cwd: main, encoding: "utf8" }).status).toBe(0);
    git("init", "-q");
    git("commit", "-q", "--allow-empty", "-m", "init");
    git("worktree", "add", "-q", join(".claude", "worktrees", "feat-x"));
    const worktree = join(main, ".claude", "worktrees", "feat-x");
    mkdirSync(join(worktree, "src"));
    expect(resolveProject(home, main, {}).id).toBe("proja");
    for (const cwd of [worktree, join(worktree, "src")]) expect(resolveProject(home, cwd, {})).toMatchObject({ id: "proja", root: worktree });
  });

  it("never derives a Windows device name as a project id", () => {
    const home = tmp();
    expect(projectById(home, "aux", home).id).toBe("aux-project");
    const repo = tmp();
    mkdirSync(join(repo, ".git"));
    writeFileSync(join(repo, ".git", "config"), '[remote "origin"]\n\turl = https://example.com/o/con.git\n');
    expect(resolveProject(home, repo, {}).id).toBe("con-project");
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { nul: {} } }));
    expect(Object.keys(loadProjects(home))).toEqual(["nul-project"]);
  });

  it.skipIf(process.platform !== "win32" && process.platform !== "darwin")("stores an added doc as spelled on disk, once", () => {
    const home = tmp();
    const repo = tmp();
    mkdirSync(join(repo, ".git"));
    mkdirSync(join(repo, "docs"));
    writeFileSync(join(repo, "docs", "plan.md"), "# Plan\n");
    const project = resolveProject(home, repo, {});
    expect(addProjectDoc(home, project, "Docs/Plan.MD")).toBe(true);
    expect(loadProjects(home)[project.id]?.docs).toEqual(["docs/plan.md"]);
    expect(addProjectDoc(home, project, "docs/plan.md")).toBe(false);
  });

  it("tags the owner, not an alias, when a note under an old id is shared", () => {
    const home = tmp();
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { owner: { aliases: ["old"] } } }));
    const note = createNote(home, { project: "old", text: "Old id fact" });
    shareNote(home, note.id, "t");
    const projects = (JSON.parse(readFileSync(join(home, "projects.json"), "utf8")) as { projects: Record<string, { tags?: string[] }> }).projects;
    expect(projects.owner?.tags).toEqual(["t"]);
    expect(Object.keys(projects)).toEqual(["owner"]);
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

  it("retries a held file briefly and rethrows any other error at once", () => {
    const coded = (code: string) => Object.assign(new Error(code), { code });
    let calls = 0;
    expect(retrying(() => {
      if (++calls < 3) throw coded("EPERM");
      return 7;
    })).toBe(7);
    expect(calls).toBe(3);
    calls = 0;
    expect(() => retrying(() => {
      calls++;
      throw coded("ENOENT");
    })).toThrow("ENOENT");
    expect(calls).toBe(1);
  });

  it("keeps a moved note in one place when its old file cannot be removed", () => {
    const home = tmp();
    const note = createNote(home, { text: "Held while moving", project: "alpha" });
    const held = join(tmp(), "held");
    mkdirSync(held);
    writeFileSync(join(held, "x"), "x");
    expect(() => saveNote(home, { ...note, project: "beta", path: held })).toThrow(/not moved/);
    expect(existsSync(join(home, "notes", "beta", `${note.id}.md`))).toBe(false);
    expect(existsSync(note.path)).toBe(true);
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

describe("inferred project tags", () => {
  it("adds the stack implied by root manifest files to declared tags", () => {
    const home = mkdtempSync(join(tmpdir(), "brain-"));
    const repo = join(mkdtempSync(join(tmpdir(), "brain-")), "web-app");
    mkdirSync(join(repo, ".git"), { recursive: true });
    writeFileSync(join(repo, "package.json"), "{}");
    writeFileSync(join(repo, "tsconfig.json"), "{}");
    mkdirSync(join(repo, "sub"));
    expect(resolveProject(home, join(repo, "sub"), {})).toMatchObject({ id: "web-app", tags: ["node", "typescript"] });
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { "web-app": { tags: ["frontend", "node"] } } }));
    expect(resolveProject(home, repo, {}).tags).toEqual(["frontend", "node", "typescript"]);
    expect(visibleTo({ ...sample(), project: "global", tags: ["typescript"] }, resolveProject(home, repo, {}))).toBe(true);
  });
});

describe("project aliases", () => {
  it("maps a derived id (remote name or folder) to the project that lists it as an alias", () => {
    const home = mkdtempSync(join(tmpdir(), "brain-"));
    writeFileSync(join(home, "projects.json"), JSON.stringify({ projects: { sztool: { aliases: ["sz-tool", "sz-tools"], tags: ["sparking-zero"] } } }));
    const folder = join(mkdtempSync(join(tmpdir(), "brain-")), "SZ-Tools");
    mkdirSync(folder);
    expect(resolveProject(home, folder, {})).toMatchObject({ id: "sztool", tags: ["sparking-zero"] });
    const repo = mkdtempSync(join(tmpdir(), "brain-"));
    mkdirSync(join(repo, ".git"));
    writeFileSync(join(repo, ".git", "config"), '[remote "origin"]\n\turl = git@github.com:me/SZ_Tool.git\n');
    expect(resolveProject(home, repo, {}).id).toBe("sztool");
  });
});
