/**
 * The `brain` command: the same functions the OMP extension uses, for any shell, harness or
 * human. `main(argv, io)` takes injected I/O so tests run it in-process.
 */
import { closeSync, existsSync, fstatSync, openSync, readdirSync, readFileSync, readSync, renameSync, rmSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { isAbsolute, join, relative, resolve } from "node:path";
import { parseArgs } from "node:util";
import { acceptProposal, appendEvent, errorSignature, eventsDir, EVENT_CAP_BYTES, findFix, listProposals, parseEvent, rejectProposal, renderFix, safeSession, scanCommits, scanEvents, toolEventFrom, unmatchedErrors } from "./capture.ts";
import { renderCard } from "./card.ts";
import { convertV3 } from "./convert.ts";
import { createNote, differentBody, findNote, findSameHeadline, GLOBAL, KINDS, loadNotes, retireNote, saveNote, upgradeNote, type Kind } from "./notes.ts";
import { addProjectDoc, gitRoot, loadProjects, projectById, resolveProject, type Project } from "./project.ts";
import { runMcp } from "./mcp.ts";
import { answerWithHits } from "./search.ts";
import { scrub } from "./scrub.ts";
import { shareNote, sync } from "./sync.ts";
import { demotedFixes, logUse, stats, type UseKind } from "./telemetry.ts";
import { estimateTokens, findHome, slug, tagKey, writeAtomic } from "./util.ts";
import { readWork, renderResume, resumeText, stateSaved, writeAuto, writeWork, type AutoFields } from "./work.ts";

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
  brain fix <error text…>                      tested known fix, or silence
  brain state [<text…>]                        show or replace the working state
  brain show <id> · retire <id> [--by <id>] · tested <id> · share <id> --tag T · move <id> --to P
  brain review · accept <pid>… · reject <pid>…
  brain project docs add <path> · project docs list
  brain sync [--no-push] [-m <message>]
  brain stats [--days N] · check · convert --from <v3 home> [--dry-run]
  brain hook claude-code                       Claude Code hook (JSON on stdin)
  brain hook agents-md                         print the managed agent instructions
  brain mcp                                    MCP server on stdio (brain_recall, brain_note, brain_state)

Every command takes --home <dir> and --project <id>. Kinds: ${KINDS.join(", ")}.`;

const AGENTS_BLOCK = "<!-- The-Second-Brain:begin id=second-brain -->\nUse `brain recall \"<query>\"` before exploring unfamiliar ground, choosing a tool/stack, or retrying a failing command; the repo wins on conflict.\nUse `brain note \"<text>\"` for what the repo cannot tell you: a decision and its why, an environment gotcha with its error line, what failed before, an owner preference.\nUse `brain state \"Goal: … Next: …\"` when the goal or next step changes.\nUse `brain fix \"<error>\"` after an unexplained failure (tested known fix, or silence).\n<!-- The-Second-Brain:end -->";

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
  "all-builds": { type: "boolean" },
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

function use(c: Ctx, kind: UseKind, text: string, hits?: number, id?: string, query?: string, ids?: string[]): void {
  logUse(c.home, { kind, project: c.project.id, tokens: estimateTokens(text), ms: performance.now() - c.started, via: "cli", session: c.io.env.BRAIN_SESSION ?? c.io.env.CLAUDE_SESSION_ID ?? undefined, hits, id, query, ids });
}

/** Fixes that stopped helping (see demotedFixes): no longer fired until their note is edited. */
function fixesToReview(c: Ctx): number {
  const { notes } = loadNotes(c.home);
  const paused = [...demotedFixes(c.home, (id) => {
    const path = notes.find((n) => n.id === id)?.path;
    try {
      return path ? statSync(path).mtimeMs : undefined;
    } catch {
      return undefined;
    }
  })].filter((id) => notes.some((n) => n.id === id && n.tested)).sort();
  if (paused.length) c.io.out("Fixes to review (helped under half of 4+ runs; paused until the note is edited):");
  for (const id of paused) c.io.out(`  ${id}`);
  return paused.length;
}

const COMMANDS: Record<string, (c: Ctx) => number> = {
  project(c) {
    const [kind, action, path, ...extra] = c.args;
    if (kind !== "docs" || extra.length || (action !== "add" && action !== "list") || (action === "list" && path)) throw new UsageError("use brain project docs add <path> or brain project docs list");
    if (action === "add") {
      const added = addProjectDoc(c.home, c.project, need(path, "a repo-relative Markdown path"));
      c.io.out(added ? `added ${path}` : `already listed: ${path}`);
    } else {
      const docs = loadProjects(c.home)[c.project.id]?.docs;
      c.io.out(Array.isArray(docs) && docs.length ? docs.filter(d => typeof d === "string").join("\n") : "no project docs");
    }
    return 0;
  },
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
    const { text, hits, ids } = answerWithHits(loadNotes(c.home).notes, query, {
      project: c.project,
      home: c.home,
      tools: false,
      all: c.opts.all === true,
      history: c.opts.history === true,
      limit: positiveInt(c.opts.limit, 3),
    });
    c.io.out(text);
    use(c, "recall", text, hits, undefined, query, ids);
    return 0;
  },

  fix(c) {
    const fix = findFix(loadNotes(c.home).notes, need(c.args.join(" "), "error text"), c.project, c.home);
    const text = fix ? renderFix(fix) : "";
    if (text) c.io.out(text);
    use(c, "fix", text, undefined, fix?.id);
    return 0;
  },

  note(c) {
    const text = need(c.args.join(" "), "note text");
    const kind = c.opts.kind ?? "note";
    if (!(KINDS as readonly string[]).includes(kind)) throw new UsageError(`unknown kind ${kind} (${KINDS.join(", ")})`);
    if (c.opts.global && c.opts.private) throw new UsageError("--global and --private exclude each other");
    const scope = c.opts.global ? GLOBAL : c.project.id;
    const same = findSameHeadline(loadNotes(c.home).notes, text, scope, c.project.tags, c.opts.private === true);
    if (same && differentBody(same, text)) {
      c.io.out(`not saved: ${same.id} has this headline with a different body; use a new headline, or \`brain retire ${same.id}\` first`);
      return 0;
    }
    if (same) {
      const changed = upgradeNote(c.home, same, {
        kind: c.opts.kind ? (kind as Kind) : undefined,
        tags: c.opts.tag,
        errors: c.opts.error,
        evidence: c.opts.evidence,
        tested: c.opts.tested === true,
      });
      c.io.out(`${changed ? "updated" : "already noted"} ${same.id}`);
      use(c, "note", text);
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
      c.io.out(resumeText(readWork(c.home, c.project.id), c.project.root) || "no working state");
      return 0;
    }
    const work = writeWork(c.home, c.project.id, c.args.join(" "));
    c.io.out(stateSaved(work));
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
    const reviewFixes = fixesToReview(c);
    if (!pending.length) {
      if (!reviewFixes) c.io.out("nothing to review");
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

  sync(c) {
    c.io.out(sync(c.home, { message: c.opts.message, push: c.opts["no-push"] !== true }).message);
    return 0;
  },

  stats(c) {
    const s = stats(c.home, positiveInt(c.opts.days, 7), new Date(), { allBuilds: c.opts["all-builds"] === true });
    c.io.out(`last ${s.days} days · ${s.sessions} sessions` + (s.olderBuildRows ? ` · newest build only (${s.olderBuildRows} older rows left out; --all-builds)` : ""));
    for (const [kind, v] of Object.entries(s.byKind).sort()) c.io.out(`${kind}: ${v.count} (${v.tokens} tokens)`);
    c.io.out(`cards: ${s.cards.main} main · ${s.cards.sub} sub`);
    const rate = s.recalls.measured ? `${Math.round(100 * s.recalls.matched / s.recalls.measured)}% (${s.recalls.matched}/${s.recalls.measured} measured)` : "n/a (0 measured)";
    c.io.out(`recall calls: ${s.recalls.calls} · hit rate: ${rate}`);
    c.io.out(`recall: ${s.recallQueries.logged} queries logged, ${s.recallQueries.silent} silent`);
    c.io.out(`brain tools used in: ${s.toolUse.main.using}/${s.toolUse.main.sessions} main sessions · ${s.toolUse.sub.using}/${s.toolUse.sub.sessions} sub`);
    c.io.out(`tool use by surface: ${s.toolCalls.tool} tool · ${s.toolCalls.cli} cli · ${s.toolCalls.hook} hook · ${s.toolCalls.mcp} mcp calls (recall/note/state; unattributed history excluded)`);
    if (s.fixes.length) c.io.out(`fixes fired: ${s.fixes.slice(0, 5).map((f) => `${f.id} in ${f.sessions} session${f.sessions === 1 ? "" : "s"}`).join(" · ")}`);
    for (const f of s.fixOutcomes.slice(0, 5)) c.io.out(`fix outcomes: ${f.id} helped ${f.helped}/missed ${f.missed}`);
    fixesToReview(c);
    if (s.errors.length) {
      c.io.out(`Brain errors (swallowed, host unaffected): ${s.errors.length}`);
      for (const e of s.errors.slice(-3)) c.io.out(`${e.at.slice(0, 16).replace("T", " ")} ${e.error}`);
    }
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
    c.io.out(`notes: ${notes.length} (${active} active) · projects: ${Object.keys(loadProjects(c.home)).length}`);
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
 * leftovers in working states, an unreadable or mistyped projects.json.
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
            for (const key of ["paths", "tags", "aliases", "docs"]) if (key in e && !strings(e[key])) errors.push(`${projectsFile}: ${id}.${key} must be a list of strings`);
            if ("remote" in e && typeof e.remote !== "string") errors.push(`${projectsFile}: ${id}.remote must be a string`);
          }
        }
      }
    } catch (error) {
      errors.push(`${projectsFile}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  return errors;
}

/** Read bounded complete JSONL rows; transcript history can be much larger than the Brain. */
function hookTail(path: string, limit: number): string[] {
  const fd = openSync(path, "r");
  try {
    const size = fstatSync(fd).size;
    const offset = Math.max(0, size - limit);
    const bytes = Buffer.alloc(Math.min(size, limit));
    const count = readSync(fd, bytes, 0, bytes.length, offset);
    const lines = bytes.subarray(0, count).toString("utf8").split("\n");
    if (offset) lines.shift();
    lines.pop(); // an unfinished append is not a complete event
    return lines;
  } finally {
    closeSync(fd);
  }
}

/** Reuse the append-only capture log: concurrent tool hooks cannot overwrite each other's edits. */
function saveHookAuto(home: string, project: Project, session: string, transcript: unknown): void {
  const fields: AutoFields = {};
  try {
    for (const line of hookTail(join(eventsDir(home), safeSession(session) + ".jsonl"), EVENT_CAP_BYTES + 8192)) {
      const event = parseEvent(line);
      if (!event || event.session !== session) continue;
      if (event.ok && /^(Edit|Write|MultiEdit)$/.test(event.tool) && event.path) {
        const absolute = resolve(event.cwd, event.path);
        const rel = relative(project.root ?? event.cwd, absolute);
        const path = (rel && !rel.startsWith("..") && !isAbsolute(rel) ? rel : absolute).replace(/\\/g, "/");
        fields.edited = [...(fields.edited ?? []).filter((p) => p !== path), path].slice(-20);
      }
      if (!event.ok && event.error) fields.failure = `${event.command ?? event.tool} → ${errorSignature(event.error)}`;
    }
  } catch {
    // A session may contain only conversation, with no captured tool events.
  }
  if (typeof transcript === "string" && transcript) {
    try {
      for (const line of hookTail(transcript, 262_144).reverse()) {
        let row: { type?: unknown; isSidechain?: unknown; isMeta?: unknown; message?: { content?: unknown } } | null;
        try { row = JSON.parse(line); } catch { continue; }
        if (row?.type !== "user" || row.isSidechain === true || row.isMeta === true) continue;
        const content = row.message?.content;
        const text = typeof content === "string" ? content : Array.isArray(content) ? content.map((block: unknown) => {
          const b = block as { type?: unknown; text?: unknown } | null;
          return b?.type === "text" && typeof b.text === "string" ? b.text : "";
        }).filter(Boolean).join("\n") : "";
        if (text.trim()) { fields.ask = text; break; }
      }
    } catch {
      // The host writes transcripts asynchronously; unavailable ask never loses the edits.
    }
  }
  writeAuto(home, project.id, fields);
}

/** Hooks run in separate processes; hash keys so commands and session names never persist. */
function hookFixDir(home: string, session: string): string {
  return join(home, "state", "pending-fixes", createHash("sha256").update(session).digest("hex"));
}

/** Claude Code hook input/output: https://code.claude.com/docs/en/hooks */
function claudeCodeHook(io: Io, explicitHome: string | undefined): number {
  let output: object = {};
  try {
    const home = findHome(explicitHome, io.env);
    const payload: unknown = JSON.parse(io.stdin() || "{}");
    if (home && payload && typeof payload === "object" && !Array.isArray(payload)) {
      const p = payload as Record<string, unknown>;
      const cwd = typeof p.cwd === "string" && p.cwd ? p.cwd : io.cwd;
      const event = p.hook_event_name;
      const session = typeof p.session_id === "string" && p.session_id ? p.session_id : undefined;
      // agent_type alone also occurs for a main session started with --agent.
      const sub = (typeof p.agent_id === "string" && !!p.agent_id) || event === "SubagentStart" || event === "SubagentStop";
      const key = sub ? `${session ?? "claude-code"}:agent:${String(p.agent_id ?? "unknown")}` : session ?? "claude-code";
      const project = resolveProject(home, cwd, io.env);
      if (event === "SessionStart" && ["startup", "resume", "clear", "compact"].includes(String(p.source ?? "startup"))) {
        rmSync(hookFixDir(home, key), { recursive: true, force: true });
        let card: string;
        if (p.source === "compact") {
          card = sub ? "" : renderResume(readWork(home, project.id), project.root);
        } else {
          const { notes } = loadNotes(home);
          if (!sub) {
            try { scanEvents(home, notes); } catch { /* the card matters more than capture */ }
          }
          card = renderCard(home, notes, project, { tools: false, subagent: sub });
        }
        if (card) {
          output = { hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: card } };
          logUse(home, { kind: p.source === "compact" ? "resume" : "card", project: project.id, tokens: estimateTokens(card), ms: 0, session, via: "hook", sub });
        }
      } else if (event === "PostToolUse" || (event === "PostToolUseFailure" && p.is_interrupt !== true)) {
        const fields = toolEventFrom(p.tool_name, p.tool_input, event === "PostToolUseFailure", p.error);
        appendEvent(home, key, cwd, fields);
        const pendingDir = hookFixDir(home, key);
        const pendingPath = join(pendingDir, createHash("sha256").update(fields.command || fields.tool).digest("hex") + ".json");
        if (session) {
          const claimed = `${pendingPath}.${process.pid}.claimed`;
          try {
            // Claim before reading: overlapping hooks must not score one firing twice.
            renameSync(pendingPath, claimed);
            const pending: unknown = JSON.parse(readFileSync(claimed, "utf8"));
            if (pending && typeof pending === "object" && "id" in pending && typeof pending.id === "string" && "project" in pending && typeof pending.project === "string") {
              logUse(home, { kind: "fixout", id: pending.id, project: pending.project, outcome: fields.ok ? "helped" : "missed", tokens: 0, ms: 0, session, via: "hook", sub });
            }
          } catch { /* missing or torn local pending state is unmeasured */ }
          finally { rmSync(claimed, { force: true }); }
        }
        if (!fields.ok && fields.error) {
          const fix = findFix(loadNotes(home).notes, fields.error, project, home);
          if (fix) {
            const text = renderFix(fix);
            output = { hookSpecificOutput: { hookEventName: "PostToolUseFailure", additionalContext: text } };
            logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(text), ms: 0, session, via: "hook", sub, id: fix.id });
            if (session) {
              try { writeAtomic(pendingPath, JSON.stringify({ id: fix.id, project: project.id })); }
              catch { /* telemetry state must not suppress the fix */ }
            }
          }
        }
      } else if (session && (event === "SessionEnd" || event === "PreCompact" || event === "SubagentStop")) {
        rmSync(hookFixDir(home, key), { recursive: true, force: true });
        if (!sub) saveHookAuto(home, project, session, p.transcript_path);
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
    if (args[0] === "agents-md") {
      io.out(AGENTS_BLOCK);
      return 0;
    }
    if (args[0] !== "claude-code") {
      io.err("brain: unknown hook (supported: claude-code, agents-md)");
      return 1;
    }
    return claudeCodeHook(io, opts.home);
  }
  // A long-lived stdio server: the MCP client owns stdout, so nothing else may print there.
  if (command === "mcp") return runMcp({ home: opts.home, env: opts.project ? { ...io.env, BRAIN_PROJECT: opts.project } : io.env });
  const run = Object.hasOwn(COMMANDS, command) ? COMMANDS[command] : undefined;
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
