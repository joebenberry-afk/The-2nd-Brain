/**
 * The `brain` command: the same functions the OMP extension uses, for any shell, harness or
 * human. `main(argv, io)` takes injected I/O so tests run it in-process.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "node:util";
import { acceptProposal, appendEvent, findFix, listProposals, rejectProposal, renderFix, scanCommits, scanEvents, unmatchedErrors } from "./capture.ts";
import { renderCard } from "./card.ts";
import { convertV3 } from "./convert.ts";
import { draftKit, findKit, kitsDir, loadKits } from "./kits.ts";
import { createNote, findNote, findSameHeadline, GLOBAL, KINDS, loadNotes, parseFrontmatter, retireNote, saveNote, upgradeNote, type Kind } from "./notes.ts";
import { gitRoot, loadProjects, projectById, resolveProject, type Project } from "./project.ts";
import { answerWithHits } from "./search.ts";
import { scrub } from "./scrub.ts";
import { shareNote, sync } from "./sync.ts";
import { logUse, stats, type UseKind } from "./telemetry.ts";
import { estimateTokens, findHome, slug, tagKey } from "./util.ts";
import { readWork, renderResume, resumeText, writeWork } from "./work.ts";

export interface Io {
  out: (text: string) => void;
  err: (text: string) => void;
  env: NodeJS.ProcessEnv;
  cwd: string;
  stdin: () => string;
}

class UsageError extends Error {}

const USAGE = `brain — agent memory that survives compaction (V4)

  brain card                                   start card for this directory's project
  brain recall <query…|note id> [--all] [--history] [-n N]
  brain note <text…> [--kind K] [--error E]… [--tag T]… [--evidence P]… [--tested] [--global|--private]
  brain state [<text…>]                        show or replace the working state
  brain show <id> · retire <id> [--by <id>] · tested <id> · share <id> --tag T · move <id> --to P
  brain review · accept <pid>… · reject <pid>…
  brain kit list · kit show <name> · kit new <name> [--from <project>] [--tag T]…
  brain sync [--no-push] [-m <message>]
  brain stats [--days N] · check · convert --from <v3 home> [--dry-run]
  brain hook claude-code                       Claude Code hook (JSON on stdin)

Every command takes --home <dir> and --project <id>. Kinds: ${KINDS.join(", ")}.`;

const OPTIONS = {
  home: { type: "string" },
  project: { type: "string" },
  kind: { type: "string" },
  error: { type: "string", multiple: true },
  tag: { type: "string", multiple: true },
  evidence: { type: "string", multiple: true },
  tested: { type: "boolean" },
  global: { type: "boolean" },
  private: { type: "boolean" },
  all: { type: "boolean" },
  history: { type: "boolean" },
  limit: { type: "string", short: "n" },
  by: { type: "string" },
  "no-push": { type: "boolean" },
  message: { type: "string", short: "m" },
  days: { type: "string" },
  from: { type: "string" },
  to: { type: "string" },
  "dry-run": { type: "boolean" },
  help: { type: "boolean", short: "h" },
} as const;

type Values = ReturnType<typeof parseArgs<{ options: typeof OPTIONS; allowPositionals: true }>>["values"];

interface Ctx {
  home: string;
  project: Project;
  args: string[];
  opts: Values;
  io: Io;
  started: number;
}

function defaultIo(): Io {
  return {
    out: (text) => void process.stdout.write(text + "\n"),
    err: (text) => void process.stderr.write(text + "\n"),
    env: process.env,
    cwd: process.cwd(),
    stdin: () => readFileSync(0, "utf8"),
  };
}

function need(value: string | undefined, what: string): string {
  if (!value || !value.trim()) throw new UsageError(`${what} is required`);
  return value;
}

function positiveInt(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n) || n < 1) throw new UsageError(`expected a positive number, got ${value}`);
  return n;
}

function use(c: Ctx, kind: UseKind, text: string): void {
  logUse(c.home, { kind, project: c.project.id, tokens: estimateTokens(text), ms: performance.now() - c.started });
}

const COMMANDS: Record<string, (c: Ctx) => number> = {
  card(c) {
    const card = renderCard(c.home, loadNotes(c.home).notes, c.project, { tools: false });
    if (card) {
      c.io.out(card);
      use(c, "card", card);
    }
    return 0;
  },

  recall(c) {
    const query = need(c.args.join(" "), "a query");
    const { text, hits } = answerWithHits(loadNotes(c.home).notes, query, {
      project: c.project,
      home: c.home,
      all: c.opts.all === true,
      history: c.opts.history === true,
      limit: positiveInt(c.opts.limit, 3),
    });
    c.io.out(text);
    logUse(c.home, { kind: "recall", project: c.project.id, tokens: estimateTokens(text), ms: performance.now() - c.started, hits });
    return 0;
  },

  note(c) {
    const text = need(c.args.join(" "), "note text");
    const kind = c.opts.kind ?? "note";
    if (!(KINDS as readonly string[]).includes(kind)) throw new UsageError(`unknown kind ${kind} (${KINDS.join(", ")})`);
    if (c.opts.global && c.opts.private) throw new UsageError("--global and --private exclude each other");
    const scope = c.opts.global ? GLOBAL : c.project.id;
    const same = findSameHeadline(loadNotes(c.home).notes, text, scope, c.project.tags, c.opts.private === true);
    if (same) {
      const changed = upgradeNote(c.home, same, {
        kind: c.opts.kind ? (kind as Kind) : undefined,
        tags: c.opts.tag,
        errors: c.opts.error,
        evidence: c.opts.evidence,
        tested: c.opts.tested === true,
      });
      c.io.out(`${changed ? "updated" : "already noted"} ${same.id}`);
      return 0;
    }
    const note = createNote(c.home, {
      text,
      project: scope,
      kind: kind as Kind,
      tags: c.opts.tag ?? [],
      errors: c.opts.error ?? [],
      evidence: c.opts.evidence ?? [],
      tested: c.opts.tested === true,
      private: c.opts.private === true,
      source: "agent",
    });
    c.io.out(`saved ${note.id}`);
    use(c, "note", text);
    return 0;
  },

  state(c) {
    if (!c.args.length) {
      c.io.out(resumeText(readWork(c.home, c.project.id)) || "no working state");
      return 0;
    }
    const work = writeWork(c.home, c.project.id, c.args.join(" "));
    c.io.out(`state saved (${estimateTokens(work.text)} tokens)`);
    use(c, "state", work.text);
    return 0;
  },

  show(c) {
    const id = need(c.args[0], "a note id");
    const note = findNote(loadNotes(c.home).notes, id);
    if (!note) throw new Error(`no note ${id}`);
    c.io.out(readFileSync(note.path, "utf8").trimEnd());
    return 0;
  },

  retire(c) {
    const id = need(c.args[0], "a note id");
    retireNote(c.home, id, c.opts.by);
    c.io.out(`retired ${id}${c.opts.by ? ` (replaced by ${c.opts.by})` : ""}`);
    return 0;
  },

  tested(c) {
    const id = need(c.args[0], "a note id");
    const note = findNote(loadNotes(c.home).notes, id);
    if (!note) throw new Error(`no note ${id}`);
    saveNote(c.home, { ...note, tested: true });
    c.io.out(`tested ${id}`);
    return 0;
  },

  move(c) {
    const id = need(c.args[0], "a note id");
    const target = need(c.opts.to, "--to <project|global>");
    const to = slug(target) === GLOBAL ? GLOBAL : projectById(c.home, target, c.io.cwd).id;
    const note = findNote(loadNotes(c.home).notes, id);
    if (!note) throw new Error(`no note ${id}`);
    saveNote(c.home, { ...note, project: to });
    c.io.out(`moved ${id} to ${to}`);
    return 0;
  },

  share(c) {
    const id = need(c.args[0], "a note id");
    const tag = need(c.opts.tag?.[0], "--tag");
    const note = shareNote(c.home, id, tag);
    c.io.out(`shared ${id} with tag ${note.tags.join(", ")}${note.taggedProject ? `; project ${note.taggedProject} now has tag ${tagKey(tag)}, so it still sees it` : ""}`);
    return 0;
  },

  review(c) {
    const notes = loadNotes(c.home).notes;
    scanEvents(c.home, notes);
    const root = gitRoot(c.io.cwd);
    if (root) scanCommits(c.home, root, c.project.id, notes);
    const pending = listProposals(c.home);
    if (!pending.length) {
      c.io.out("nothing to review");
      return 0;
    }
    for (const p of pending) c.io.out(`${p.id} [${p.kind}${p.tested ? ", tested" : ""}] (${p.project})\n${scrub(p.text).text.slice(0, 800)}`);
    c.io.out("accept: brain accept <pid>… · reject: brain reject <pid>…");
    return 0;
  },

  accept(c) {
    if (!c.args.length) throw new UsageError("proposal ids are required");
    for (const pid of c.args) c.io.out(`accepted ${pid} → ${acceptProposal(c.home, pid).id}`);
    return 0;
  },

  reject(c) {
    if (!c.args.length) throw new UsageError("proposal ids are required");
    for (const pid of c.args) {
      rejectProposal(c.home, pid);
      c.io.out(`rejected ${pid}`);
    }
    return 0;
  },

  kit(c) {
    const [sub, name] = c.args;
    const kits = loadKits(c.home);
    if (sub === "list") {
      c.io.out(kits.length ? kits.map((k) => `${k.name} — ${k.description}`).join("\n") : "no kits");
      return 0;
    }
    if (sub === "show") {
      const kit = findKit(kits, need(name, "a kit name"));
      if (!kit) throw new Error(`no kit ${name}`);
      c.io.out(readFileSync(kit.path, "utf8").trimEnd());
      return 0;
    }
    if (sub === "new") {
      const tags = c.opts.tag ?? [];
      const from = c.opts.from ? projectById(c.home, c.opts.from, c.io.cwd).id : c.project.id;
      const notes = loadNotes(c.home).notes;
      // A --from that matches no project is a typo, not a request for an empty scaffold.
      if (c.opts.from && !notes.some((n) => n.project === from && !n.retired)) throw new Error(`no notes in project ${from}`);
      const kit = draftKit(c.home, need(name, "a kit name"), from, notes, tags.length ? tags : undefined);
      c.io.out(`drafted ${kit.path}`);
      return 0;
    }
    throw new UsageError("kit list | kit show <name> | kit new <name>");
  },

  sync(c) {
    c.io.out(sync(c.home, { message: c.opts.message, push: c.opts["no-push"] !== true }).message);
    return 0;
  },

  stats(c) {
    const s = stats(c.home, positiveInt(c.opts.days, 7));
    c.io.out(`last ${s.days} days · ${s.sessions} sessions`);
    for (const [kind, v] of Object.entries(s.byKind).sort()) c.io.out(`${kind}: ${v.count} (${v.tokens} tokens)`);
    c.io.out(`cards: ${s.cards.main} main · ${s.cards.sub} sub`);
    const rate = s.recalls.measured ? `${Math.round(100 * s.recalls.matched / s.recalls.measured)}% (${s.recalls.matched}/${s.recalls.measured} measured)` : "n/a (0 measured)";
    c.io.out(`recall calls: ${s.recalls.calls} · hit rate: ${rate}`);
    const unmatched = unmatchedErrors(c.home, loadNotes(c.home).notes, { days: s.days }).slice(0, 5);
    if (unmatched.length) {
      c.io.out("Unmatched errors:");
      for (const error of unmatched) c.io.out(`${error.count} × ${error.signature}`);
    }
    return 0;
  },

  check(c) {
    const { notes, errors: noteErrors } = loadNotes(c.home);
    const errors = [...noteErrors, ...configErrors(c.home)];
    const active = notes.filter((n) => !n.retired).length;
    c.io.out(`notes: ${notes.length} (${active} active) · projects: ${Object.keys(loadProjects(c.home)).length} · kits: ${loadKits(c.home).length}`);
    for (const e of errors) c.io.err(e);
    return errors.length ? 1 : 0;
  },

  convert(c) {
    const report = convertV3(need(c.opts.from, "--from"), c.home, { dryRun: c.opts["dry-run"] === true });
    c.io.out(`written ${report.written}, skipped ${report.skipped}, projects ${report.projects}${c.opts["dry-run"] ? " (dry run)" : ""}`);
    for (const e of report.errors) c.io.err(e);
    return report.errors.length ? 1 : 0;
  },
};

/**
 * Problems that would otherwise be silent: a home that is not a directory, files the loader never
 * reads (outside a project folder, in a folder that is not a project id, not named *.md), merge
 * leftovers in working states, an unreadable or mistyped projects.json, a kit that is skipped.
 */
function configErrors(home: string): string[] {
  const errors: string[] = [];
  const isDir = (path: string) => {
    try {
      return statSync(path).isDirectory();
    } catch {
      return false;
    }
  };
  if (!isDir(home)) return [`${home}: not a directory (the Brain home)`];
  const list = (dir: string) => {
    try {
      return readdirSync(dir, { withFileTypes: true }).filter((e) => !e.name.startsWith("."));
    } catch {
      return [];
    }
  };
  const notesDir = join(home, "notes");
  if (existsSync(notesDir) && !isDir(notesDir)) errors.push(`${notesDir}: not a directory`);
  for (const entry of list(notesDir)) {
    const path = join(notesDir, entry.name);
    if (!entry.isDirectory()) {
      errors.push(`${path}: not in a project folder, never read`);
      continue;
    }
    if (entry.name !== slug(entry.name)) errors.push(`${path}: folder is not a project id (use ${slug(entry.name)}), never read`);
    for (const [dir, inner] of [[path, true], [join(path, "private"), false]] as const) {
      for (const file of list(dir)) {
        if (file.isDirectory() ? !(inner && file.name === "private") : !file.name.endsWith(".md")) {
          errors.push(`${join(dir, file.name)}: never read (notes are <project>/<id>.md or <project>/private/<id>.md)`);
        }
      }
    }
  }
  for (const entry of list(join(home, "work"))) {
    const path = join(home, "work", entry.name);
    if (!entry.name.endsWith(".md") || entry.name.slice(0, -3) !== slug(entry.name.slice(0, -3))) {
      errors.push(`${path}: never read (working states are work/<project id>.md)`);
    } else if (/^(<{7}|>{7}|={7})( |$)/m.test(readFileSync(path, "utf8"))) {
      errors.push(`${path}: holds merge conflict markers`);
    }
  }
  const projectsFile = join(home, "projects.json");
  if (existsSync(projectsFile)) {
    try {
      const data: unknown = JSON.parse(readFileSync(projectsFile, "utf8").replace(/^\uFEFF/, ""));
      const projects = (data as { projects?: unknown } | null)?.projects;
      if (!projects || typeof projects !== "object" || Array.isArray(projects)) errors.push(`${projectsFile}: expected { "projects": { … } }`);
      else {
        const strings = (v: unknown) => Array.isArray(v) && v.every((x) => typeof x === "string");
        for (const [id, entry] of Object.entries(projects as Record<string, unknown>)) {
          const e = entry as Record<string, unknown> | null;
          if (!e || typeof e !== "object" || Array.isArray(e)) errors.push(`${projectsFile}: ${id} is not an object, ignored`);
          else {
            for (const key of ["paths", "tags", "aliases"]) if (key in e && !strings(e[key])) errors.push(`${projectsFile}: ${id}.${key} must be a list of strings`);
            if ("remote" in e && typeof e.remote !== "string") errors.push(`${projectsFile}: ${id}.remote must be a string`);
          }
        }
      }
    } catch (error) {
      errors.push(`${projectsFile}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  const loaded = new Set(loadKits(home).map((k) => k.path));
  for (const entry of list(kitsDir(home))) {
    const skill = join(kitsDir(home), entry.name, "SKILL.md");
    if (!entry.isDirectory() || loaded.has(skill)) continue;
    let why = "missing";
    try {
      const { fields } = parseFrontmatter(readFileSync(skill, "utf8"));
      why = fields.get("description") ? "unreadable" : "without a description";
    } catch (error) {
      if (existsSync(skill)) why = error instanceof Error ? error.message : String(error);
    }
    errors.push(`${skill}: ${why}`);
  }
  return errors;
}

/** `brain hook claude-code`: one JSON object in, one out, exit 0 — whatever happens. */
function claudeCodeHook(io: Io, explicitHome: string | undefined): number {
  let output: object = {};
  try {
    const home = findHome(explicitHome, io.env);
    const payload: unknown = JSON.parse(io.stdin() || "{}");
    if (home && payload && typeof payload === "object") {
      const p = payload as Record<string, unknown>;
      const cwd = typeof p.cwd === "string" && p.cwd ? p.cwd : io.cwd;
      const project = resolveProject(home, cwd, io.env);
      const event = p.hook_event_name;
      const session = typeof p.session_id === "string" && p.session_id ? p.session_id : undefined;
      if (event === "SessionStart" && ["startup", "resume", "clear", "compact"].includes(String(p.source ?? "startup"))) {
        let card: string;
        if (p.source === "compact") {
          card = renderResume(readWork(home, project.id));
        } else {
          const { notes } = loadNotes(home);
          // Startup capture remains incremental and separate from the compact resume.
          try {
            scanEvents(home, notes);
          } catch {
            // the card matters more than the count
          }
          card = renderCard(home, notes, project, { tools: false });
        }
        if (card) {
          output = { hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: card } };
          logUse(home, { kind: p.source === "compact" ? "resume" : "card", project: project.id, tokens: estimateTokens(card), ms: 0, session });
        }
      } else if (event === "PostToolUseFailure" && typeof p.error === "string" && p.error.trim() && p.is_interrupt !== true) {
        const input = (p.tool_input && typeof p.tool_input === "object" ? p.tool_input : {}) as Record<string, unknown>;
        appendEvent(home, session ?? "claude-code", cwd, {
          tool: typeof p.tool_name === "string" ? p.tool_name : "unknown",
          command: typeof input.command === "string" ? input.command : undefined,
          path: typeof input.file_path === "string" ? input.file_path : undefined,
          ok: false,
          error: p.error,
        });
        const fix = findFix(loadNotes(home).notes, p.error, project);
        if (fix) {
          const text = renderFix(fix);
          output = { hookSpecificOutput: { hookEventName: "PostToolUseFailure", additionalContext: text } };
          logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(text), ms: 0, session });
        }
      }
    }
  } catch {
    output = {}; // fail open: never break the host session
  }
  io.out(JSON.stringify(output));
  return 0;
}

export async function main(argv: string[], ioOverrides: Partial<Io> = {}): Promise<number> {
  const io: Io = { ...defaultIo(), ...ioOverrides };
  const started = performance.now();
  let parsed: { values: Values; positionals: string[] };
  try {
    parsed = parseArgs({ args: argv, options: OPTIONS, allowPositionals: true, strict: true });
  } catch (error) {
    io.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
  const [command = "help", ...args] = parsed.positionals;
  const opts = parsed.values;
  if (command === "help" || opts.help) {
    io.out(USAGE);
    return 0;
  }
  if (command === "hook") {
    if (args[0] !== "claude-code") {
      io.err("brain: unknown hook (supported: claude-code)");
      return 1;
    }
    return claudeCodeHook(io, opts.home);
  }
  const run = COMMANDS[command];
  if (!run) {
    io.err(`brain: unknown command ${command} (brain help)`);
    return 1;
  }
  const home = findHome(opts.home, io.env);
  if (!home) {
    io.err("brain: no Brain home (set SECOND_BRAIN_HOME)");
    return 2;
  }
  const project: Project = opts.project ? projectById(home, opts.project, io.cwd) : resolveProject(home, io.cwd, io.env);
  try {
    return run({ home, project, args, opts, io, started });
  } catch (error) {
    io.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
}
