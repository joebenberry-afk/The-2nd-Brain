/**
 * The `brain` command: the same functions the OMP extension uses, for any shell, harness or
 * human. `main(argv, io)` takes injected I/O so tests run it in-process.
 */
import { closeSync, existsSync, fstatSync, openSync, readdirSync, readFileSync, readSync, renameSync, rmSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { basename, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { collectAsks, formatWeek, hostSessionRoots, MAX_WEEKS, weeklyAsks, windowStart } from "./asks.ts";
import { acceptProposal, appendEvent, autoEvidence, captureUserRules, dismissError, findFix, fixCutHint, listClaudeMemory, listProposals, rejectProposal, renderFix, scanCommits, scanEvents, scrubCut, sessionEdits, toolEventFrom, unmatchedErrors } from "./capture.ts";
import { operationOf, outcomeOf, type PendingFix } from "./outcome.ts";
import { cardIds, LEAN_LINE, renderCard } from "./card.ts";
import { projectDocs, suggestDocs } from "./docs.ts";
import { createNote, differentBody, errorPatternProblem, findNote, findSameHeadline, GLOBAL, headline, KINDS, loadNotes, loadVisibleNotes, markTested, retireNote, staleAfterProblem, TESTERS, updateNote, upgradeNote, type Kind } from "./notes.ts";
import { addProjectDoc, docFile, gitRoot, idFor, loadProjects, projectById, resolveProject, type Project } from "./project.ts";
import { pathHint } from "./paths.ts";
import type { JudgeName, ToraRecall, RecallTrace } from "./judge.ts";
import { scrub } from "./scrub.ts";
import { noteUsage, pausedFixes, logUse, stats, toolSchemaUse, usageWindow, type UseKind } from "./telemetry.ts";
import { estimateTokens, findHome, noHome, slug, tagKey, writeAtomic } from "./util.ts";
import { readWork, workText, stateSaved, writeAuto, writeWork, type AutoFields } from "./work.ts";
import { rolloverHint } from "./rollover.ts";

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
  brain recall <query…|note id> [--all] [--history] [-n 1-3]
  brain note <text…> [--kind K] [--error E]… [--tag T]… [--evidence P]… [--tested] [--stale-after DATE] [--replaces ID] [--global|--private]
  brain fix <error text…>                      tested known fix, or silence
  brain state [<text…>]                        show or replace the working state
  brain show <id> · retire <id> [--by <id>] · tested <id> · share <id> --tag T · move <id> --to P
  brain review [--all] · accept <pid>… · reject <pid>…
  brain dismiss <signature…>                   ignore a recurring unmatched error
  brain project docs add <path> · project docs list · project docs suggest [-n N]
  brain sync [--no-push] [-m <message>]
  brain stats [--days N] · check · convert --from <v3 home> [--dry-run]
  brain tidy [--all] [--days N] [--pair-budget N]  read-only duplicates, contradictions, unused notes, unseen global tags
  brain export <dir>                           public notes as an OKF bundle (one way)
  brain hook claude-code                       Claude Code hook (JSON on stdin)
  brain hook agents-md                         print the managed agent instructions
  brain mcp                                    MCP server on stdio (brain_recall, brain_note, brain_state)
  brain proxy [--port N]                       layer 4 proxy for Claude Code and Codex, 127.0.0.1 only (default port 47830)

Every command takes --home <dir> and --project <id>. Kinds: ${KINDS.join(", ")}.`;

const AGENTS_BLOCK = "<!-- The-Second-Brain:begin id=second-brain -->\nUse `brain recall \"<query>\"` before exploring unfamiliar ground, choosing a tool/stack, or retrying a failing command, in the same turn as your first search (a recall alone costs a turn); the repo wins on conflict.\nUse `brain note \"<text>\"` for what the repo cannot tell you: a decision and its why, an environment gotcha with its error line, what failed before, an owner preference.\nUse `brain state \"Goal: … Next: …\"` when the goal or next step changes.\nUse `brain fix \"<error>\"` after an unexplained failure (tested known fix, or silence).\n<!-- The-Second-Brain:end -->";

const OPTIONS = {
  home: { type: "string" },
  project: { type: "string" },
  kind: { type: "string" },
  error: { type: "string", multiple: true },
  tag: { type: "string", multiple: true },
  evidence: { type: "string", multiple: true },
  tested: { type: "boolean" },
  "stale-after": { type: "string" },
  replaces: { type: "string" },
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
  "pair-budget": { type: "string" },
  from: { type: "string" },
  to: { type: "string" },
  "dry-run": { type: "boolean" },
  port: { type: "string" },
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

function use(c: Ctx, kind: UseKind, text: string, hits?: number, id?: string, query?: string, ids?: string[], judged?: boolean, dropped?: number, tora?: ToraRecall, judge?: JudgeName, recall?: RecallTrace): void {
  logUse(c.home, { kind, project: c.project.id, tokens: estimateTokens(text), ms: performance.now() - c.started, via: "cli", session: c.io.env.BRAIN_SESSION ?? c.io.env.CLAUDE_CODE_SESSION_ID ?? c.io.env.CLAUDE_SESSION_ID, hits, id, query, ids, judged, judge, dropped, tora, recall });
}

/** Fixes that stopped helping (see demotedFixes): no longer fired until their note is edited. */
function fixesToReview(c: Ctx): number {
  const { notes } = loadNotes(c.home);
  const paused = [...pausedFixes(c.home, notes)].filter((id) => notes.some((n) => n.id === id && n.tested)).sort();
  if (paused.length) c.io.out("Fixes to review (helped under half of 4+ runs; paused until the note is edited):");
  for (const id of paused) c.io.out(`  ${id}`);
  return paused.length;
}

// Exception to static imports: optional command modules must not tax each short-lived hook startup.
const COMMANDS: Record<string, (c: Ctx) => number | Promise<number>> = {
  project(c) {
    const [kind, action, path, ...extra] = c.args;
    if (kind !== "docs" || extra.length || !["add", "list", "suggest"].includes(action ?? "") || (action !== "add" && path)) throw new UsageError("use brain project docs add <path>, brain project docs list or brain project docs suggest [-n N]");
    if (action === "add") {
      const added = addProjectDoc(c.home, c.project, need(path, "a repo-relative Markdown path"));
      c.io.out(added ? `added ${path}` : `already listed: ${path}`);
    } else if (action === "suggest") {
      const suggestions = suggestDocs(c.home, c.project, { limit: positiveInt(c.opts.limit, 5) });
      c.io.out(suggestions.length ? suggestions.map(s => `${s.queries} queries · ${s.reads} full reads · ${s.path}  → brain project docs add ${s.path}`).join("\n") : "no suggestions");
    } else {
      const docs = loadProjects(c.home)[c.project.id]?.docs;
      const shown = (d: string) => docFile(c.project, d) ? d : `${d} (missing under ${c.project.docRoot ?? c.project.root ?? "no root"})`;
      c.io.out(Array.isArray(docs) && docs.length ? docs.filter(d => typeof d === "string").map(shown).join("\n") : "no project docs");
    }
    return 0;
  },
  card(c) {
    // A preview of the Claude Code card (no tools, Claude Code's fix fires); OMP renders its own.
    const card = renderCard(c.home, loadVisibleNotes(c.home, c.project.id).notes, c.project, { tools: false, host: "claude-code" });
    if (card) {
      c.io.out(card);
      use(c, "card", card, undefined, undefined, undefined, cardIds(card));
    }
    return 0;
  },

  async recall(c) {
    // Lazy command loading keeps optional judge code off the no-op hook startup path.
    const { recallFor } = await import("./judge.ts");
    const query = need(c.args.join(" "), "a query");
    const { text, hits, ids, judged, judge, dropped, tora, recall } = await recallFor(loadNotes(c.home).notes, query, {
      project: c.project,
      home: c.home,
      tools: false,
      all: c.opts.all === true,
      history: c.opts.history === true,
      limit: positiveInt(c.opts.limit, 3),
    }, c.io.env);
    c.io.out(text);
    use(c, "recall", text, hits, undefined, query, ids, judged, dropped, tora, judge, recall);
    return 0;
  },

  fix(c) {
    const fix = findFix(loadNotes(c.home).notes, need(c.args.join(" "), "error text"), c.project, c.home);
    const text = fix ? renderFix(fix) : "";
    if (text) c.io.out(text);
    use(c, "fix", text, undefined, fix?.id);
    return 0;
  },

  async note(c) {
    const { noteHint } = await import("./tidy.ts");
    const { judgeScorer, typesafePairJudge } = await import("./judge.ts");
    const text = need(c.args.join(" "), "note text");
    const kind = c.opts.kind ?? "note";
    if (!(KINDS as readonly string[]).includes(kind)) throw new UsageError(`unknown kind ${kind} (${KINDS.join(", ")})`);
    if (c.opts.global && c.opts.private) throw new UsageError("--global and --private exclude each other");
    const scope = c.opts.global ? GLOBAL : c.project.id;
    const notes = loadNotes(c.home).notes;
    const replaces = c.opts.replaces;
    const old = replaces === undefined ? undefined : findNote(notes, replaces);
    if (replaces !== undefined && !old) throw new UsageError(`no note ${replaces}`);
    if (old?.retired) throw new UsageError(`${old.id} is already retired`);
    const same = replaces === undefined ? findSameHeadline(notes, text, scope, scope === GLOBAL ? c.opts.tag : c.project.tags, c.opts.private === true) : undefined;
    if (same && differentBody(same, text)) {
      c.io.out(`not saved: ${same.id} has this headline with a different body; use a new headline, or \`brain retire ${same.id}\` first`);
      return 0;
    }
    // As brain_note: a tested global fix fires in every project on both hosts, so the owner confirms it.
    const wantsTested = c.opts.tested === true;
    const tested = wantsTested && (same?.project ?? scope) !== GLOBAL;
    const untested = wantsTested && !tested && !same?.tested ? " (untested: the owner confirms a global fix with `brain tested <id>`)" : "";
    if (same) {
      const changed = upgradeNote(c.home, same, {
        kind: c.opts.kind ? (kind as Kind) : undefined,
        tags: c.opts.tag,
        errors: c.opts.error,
        evidence: c.opts.evidence,
        evidenceRoots: [c.project.root, c.project.docRoot].filter((root): root is string => !!root),
        tested,
        testedBy: "agent",
        staleAfter: c.opts["stale-after"],
      });
      c.io.out(`${changed ? "updated" : "already noted"} ${same.id}${untested}${changed ? fixCutHint(changed) : ""}`);
      use(c, "note", text);
      return 0;
    }
    const note = createNote(c.home, {
      text,
      project: scope,
      kind: kind as Kind,
      tags: c.opts.tag ?? [],
      errors: c.opts.error ?? [],
      evidence: c.opts.evidence ?? autoEvidence(text, c.project.root, c.project.root ? sessionEdits(c.home, c.io.env.BRAIN_SESSION ?? c.io.env.CLAUDE_CODE_SESSION_ID ?? c.io.env.CLAUDE_SESSION_ID ?? "", c.project.root) : []),
      evidenceRoots: [c.project.root, c.project.docRoot].filter((root): root is string => !!root),
      tested,
      testedBy: "agent",
      staleAfter: c.opts["stale-after"],
      private: c.opts.private === true,
      source: "agent",
    });
    if (old) retireNote(c.home, old.id, note.id);
    c.io.out(`saved ${note.id}${old ? ` (retired ${old.id})` : ""}${untested}${fixCutHint(note)}${await noteHint(c.home, note, loadNotes(c.home).notes, typesafePairJudge(c.io.env), judgeScorer(c.io.env))}`);
    use(c, "note", text);
    return 0;
  },

  state(c) {
    if (!c.args.length) {
      c.io.out(workText(readWork(c.home, c.project.id), c.project.root, c.project.docRoot, c.project.docRoot ? projectDocs(c.home, c.project) : []) || "no working state");
      return 0;
    }
    const work = writeWork(c.home, c.project.id, c.args.join(" "));
    c.io.out(stateSaved(work, c.home, c.project));
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
    const retired = retireNote(c.home, id, c.opts.by);
    c.io.out(`retired ${retired.id}${retired.replacedBy ? ` (replaced by ${retired.replacedBy})` : ""}`);
    return 0;
  },

  tested(c) {
    const id = need(c.args[0], "a note id");
    const note = updateNote(c.home, id, (fresh) => {
      const project = fresh.project === GLOBAL ? c.project : projectById(c.home, fresh.project, c.io.cwd);
      // Another repo's files are not this note's evidence: only the note's own checkout resolves.
      const checkout = fresh.project === GLOBAL || (!!project.root && resolveProject(c.home, project.root, {}).id === project.id);
      return markTested(fresh, "owner", (checkout ? [project.root, project.docRoot, c.home] : [c.home]).filter((root): root is string => !!root));
    });
    c.io.out(`tested ${note.id}`);
    return 0;
  },

  move(c) {
    const id = need(c.args[0], "a note id");
    const target = need(c.opts.to, "--to <project|global>");
    const to = slug(target) === GLOBAL ? GLOBAL : projectById(c.home, target, c.io.cwd).id;
    const note = updateNote(c.home, id, (fresh) => ({ ...fresh, project: to }));
    c.io.out(`moved ${note.id} to ${to}`);
    return 0;
  },

  async share(c) {
    const { shareNote } = await import("./sync.ts");
    const id = need(c.args[0], "a note id");
    const tag = need(c.opts.tag?.[0], "--tag");
    const note = shareNote(c.home, id, tag);
    c.io.out(`shared ${note.id} with tag ${note.tags.join(", ")}${note.taggedProject ? `; project ${note.taggedProject} now has tag ${tagKey(tag)}, so it still sees it` : ""}`);
    return 0;
  },

  async review(c) {
    const { silentRecallLines } = await import("./silent.ts");
    const notes = loadNotes(c.home).notes;
    scanEvents(c.home, notes);
    const root = gitRoot(c.io.cwd);
    if (root) scanCommits(c.home, root, c.project.id, notes);
    // This project's and global proposals, as the card counts them; --all lists every project's.
    const all = [...listProposals(c.home), ...listClaudeMemory(c.home, notes, { env: c.io.env, project: c.project })];
    const pending = c.opts.all === true ? all : all.filter((p) => p.project === c.project.id || p.project === GLOBAL);
    const more = all.length > pending.length ? `+${all.length - pending.length} in other projects (brain review --all)` : "";
    const reviewFixes = fixesToReview(c);
    const errors = unmatchedErrors(c.home, notes, { days: 14, project: c.opts.all === true ? undefined : c.project.id, global: true }).slice(0, 5);
    const silent = silentRecallLines(c.home, c.io.cwd, { project: c.opts.all === true ? undefined : c.project.id });
    if (!pending.length && !reviewFixes && !errors.length && !silent.recurring) {
      c.io.out(more ? `nothing to review here; ${more}` : "nothing to review");
      for (const line of silent.lines) c.io.out(line);
      return 0;
    }
    // Bounded: an agent reads this output; -n shows more.
    const shown = pending.slice(0, positiveInt(c.opts.limit, 15));
    for (const p of shown) c.io.out(`${p.id} [${p.kind}${p.tested ? ", tested" : ""}${p.source === "user" || p.source === "claude-memory" ? `, ${p.source}` : ""}] (${p.project})\n${scrub(p.text).text.slice(0, 300)}`);
    if (pending.length > shown.length) c.io.out(`+${pending.length - shown.length} more proposals (brain review${c.opts.all === true ? " --all" : ""} -n ${pending.length})`);
    if (pending.length) c.io.out("accept: brain accept <pid>… · reject: brain reject <pid>…");
    if (errors.length) c.io.out("Unmatched errors (last 14 days):");
    for (const error of errors) {
      c.io.out(`${error.count} × ${error.signature}`);
      if (error.tool || error.then) c.io.out("  " + [error.tool ? `last: ${error.tool}` : "", error.then ? `then: ${error.then}` : ""].filter(Boolean).join(" · "));
      // Double-quoted shell arguments must also escape substitution syntax in error text.
      const pattern = error.pattern ? JSON.stringify(error.pattern).replace(/[$`]/g, "\\$&") : "";
      const signature = JSON.stringify(error.signature).replace(/[$`]/g, "\\$&");
      if (error.candidate) c.io.out(`  named by ${error.candidate}: brain tested ${error.candidate}`);
      const fix = !error.candidate && pattern ? `fix: brain note "<what to do>" --kind gotcha --error ${pattern}  ·  ` : "";
      c.io.out(`  ${fix}ignore: brain dismiss ${signature}`);
    }
    for (const line of silent.lines) c.io.out(line);
    if (more) c.io.out(more);
    return 0;
  },

  dismiss(c) {
    const signature = need(c.args.join(" "), "error signature");
    dismissError(c.home, signature);
    c.io.out(`dismissed ${signature}`);
    return 0;
  },

  accept(c) {
    if (!c.args.length) throw new UsageError("proposal ids are required");
    for (const pid of c.args) c.io.out(`accepted ${pid} → ${acceptProposal(c.home, pid, { env: c.io.env, project: c.project }).id}`);
    return 0;
  },

  reject(c) {
    if (!c.args.length) throw new UsageError("proposal ids are required");
    for (const pid of c.args) {
      rejectProposal(c.home, pid, { env: c.io.env, project: c.project });
      c.io.out(`rejected ${pid}`);
    }
    return 0;
  },

  async sync(c) {
    const { sync } = await import("./sync.ts");
    c.io.out(sync(c.home, { message: c.opts.message, push: c.opts["no-push"] !== true }).message);
    return 0;
  },

  async tidy(c) {
    const { tidyReport } = await import("./tidy.ts");
    const { typesafePairJudge } = await import("./judge.ts");
    const days = positiveInt(c.opts.days, 30);
    const judge = typesafePairJudge(c.io.env);
    const pairBudget = c.opts["pair-budget"] === undefined ? undefined : positiveInt(c.opts["pair-budget"], 20);
    const report = await tidyReport(c.home, loadNotes(c.home).notes, c.project, { days, all: c.opts.all === true, judge, pairBudget });
    let shown = false;
    for (const [title, pairs] of [["Duplicates", report.duplicates], ["Contradictions", report.contradictions], ["Similar (not judged)", report.similar]] as const) {
      if (!pairs.length) continue;
      shown = true;
      c.io.out(title);
      for (const { a, b, via } of pairs) c.io.out("  " + a.id + " ⇄ " + b.id + "  " + headline(a) + " | " + headline(b) + (via === "lexical" || via === "tora" ? "" : ` [${via}]`) + (title === "Similar (not judged)" ? "" : " · brain retire " + a.id + " --by " + b.id));
    }
    if (judge && (report.reviewed || report.unreviewed)) c.io.out(`judged ${report.reviewed} public pairs · ${report.unreviewed} unreviewed${report.unreviewed ? " (--pair-budget N judges more)" : ""}`);
    if (report.unused.length) {
      shown = true;
      c.io.out("Unused " + report.unusedWindow);
      for (const note of report.unused) c.io.out("  " + note.id + "  " + headline(note) + " · brain retire " + note.id);
    }
    if (report.orphans.length) {
      shown = true;
      c.io.out("Global notes no project can see (tags match no registered or inferred project tag)");
      for (const note of report.orphans) c.io.out("  " + note.id + " [" + note.tags.join(", ") + "]  " + headline(note) + " · add the tag to a project in projects.json, or drop it from the note");
    }
    if (!shown) c.io.out("nothing to tidy");
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
    const t = s.tora;
    c.io.out(`tora: ${t.recalls} recalls · ${t.scored} BM25 candidates scored · ${t.judged} sent to the judge · ${t.kept} kept`);
    c.io.out(`judged recalls: ${s.judges.tora} by Tora (local) · ${s.judges.jev} by Jev (paid)`);
    const active = loadNotes(c.home).notes.filter(note => !note.retired);
    const usage = noteUsage(c.home, s.days);
    const used = active.filter(note => usage.notes.has(note.id)).length;
    c.io.out(`notes used (${usageWindow(usage, s.days)}): ${used} of ${active.length} active · never: ${active.length - used} (brain tidy)`);
    c.io.out(`brain tools used in: ${s.toolUse.main.using}/${s.toolUse.main.sessions} main sessions · ${s.toolUse.sub.using}/${s.toolUse.sub.sessions} sub`);
    c.io.out(`tool use by surface: ${s.toolCalls.tool} tool · ${s.toolCalls.cli} cli · ${s.toolCalls.mcp} mcp calls (recall/note/state; unattributed history excluded)`);
    if (s.layer4.epochs) c.io.out(`layer 4 (reversible rendering): ${s.layer4.epochs} epochs · ${s.layer4.elided} outputs elided · ${s.layer4.saved} tokens saved per later request · ${s.layer4.restores} restores`);
    const schemas = toolSchemaUse(c.home, s.days);
    if (schemas) {
      const waste = schemas.unused.reduce((sum, tool) => sum + tool.tokens, 0);
      c.io.out(`tool schemas (OMP, ${schemas.at.slice(0, 10)}): ${schemas.tools} active ≈ ${schemas.tokens} tokens per request · uncalled ${s.days}d: ${schemas.unused.length} ≈ ${waste} tokens`);
      if (schemas.unused.length) c.io.out(`  ${schemas.unused.slice(0, 8).map(tool => `${tool.name} (${tool.source}, ${tool.tokens})`).join(" · ")}${schemas.unused.length > 8 ? " …" : ""}`);
      if (schemas.system.length) {
        const total = schemas.system.reduce((sum, n) => sum + n, 0);
        const largest = schemas.system.map((tokens, i) => ({ i, tokens })).sort((a, b) => b.tokens - a.tokens).slice(0, 3);
        c.io.out(`system prompt (OMP, ${schemas.at.slice(0, 10)}): ${schemas.system.length} blocks ≈ ${total} tokens per request · largest: ${largest.map(b => `#${b.i + 1} ${b.tokens}`).join(" · ")}`);
      }
    }
    // Outcome per owner request, from the hosts' own session files (retrospective, nothing logged).
    const weeks = Math.min(MAX_WEEKS, Math.max(4, Math.ceil(s.days / 7)));
    const now = new Date();
    const everyone = c.opts.all === true;
    const asks = collectAsks(hostSessionRoots(c.io.env), windowStart(now, weeks), cwd => everyone || resolveProject(c.home, cwd, {}).id === c.project.id, join(c.home, "state", "asks-cache.json"));
    c.io.out(`asks by week (main sessions, OMP + Claude Code, UTC weeks, ${everyone ? "all projects" : c.project.id}; turns = model requests per prompt; idle >5 min ends an ask):`);
    for (const row of weeklyAsks(asks, weeks, now)) c.io.out("  " + formatWeek(row));
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
      for (const error of unmatched) c.io.out(`${error.count} × ${error.signature}${error.candidate ? ` — named by ${error.candidate}; brain tested ${error.candidate}` : ""}`);
    }
    return 0;
  },

  check(c) {
    const { notes, errors: noteErrors } = loadNotes(c.home);
    const errors = [...noteErrors, ...configErrors(c.home)];
    for (const n of notes) if (n.host && n.host !== "omp" && n.host !== "claude-code") errors.push(`${n.path}: host ${JSON.stringify(n.host)} is not omp or claude-code; the fix fires on no host`);
    for (const n of notes) {
      const problem = n.staleAfter ? staleAfterProblem(n.staleAfter) : null;
      if (problem) errors.push(`${n.path}: ${problem}; the note never goes stale`);
      if (n.testedBy && !(TESTERS as readonly string[]).includes(n.testedBy)) errors.push(`${n.path}: tested_by ${JSON.stringify(n.testedBy)} is not ${TESTERS.join(", ")}`);
      if (!n.retired) for (const pattern of n.errors) {
        const patternProblem = errorPatternProblem(pattern);
        if (patternProblem) errors.push(`${n.path}: ${patternProblem}; the known fix never fires`);
      }
    }
    const active = notes.filter((n) => !n.retired).length;
    c.io.out(`notes: ${notes.length} (${active} active) · projects: ${Object.keys(loadProjects(c.home)).length}`);
    for (const e of errors) c.io.err(e);
    return errors.length ? 1 : 0;
  },

  async convert(c) {
    const { convertV3 } = await import("./convert.ts");
    const report = convertV3(need(c.opts.from, "--from"), c.home, { dryRun: c.opts["dry-run"] === true });
    c.io.out(`written ${report.written}, skipped ${report.skipped}, projects ${report.projects}${c.opts["dry-run"] ? " (dry run)" : ""}`);
    for (const e of report.errors) c.io.err(e);
    return report.errors.length ? 1 : 0;
  },

  async export(c) {
    const { exportOkf, OKF_VERSION } = await import("./okf.ts");
    if (c.args.length !== 1) throw new UsageError("use brain export <dir>");
    const report = exportOkf(c.home, loadNotes(c.home).notes, resolve(c.io.cwd, c.args[0]!));
    c.io.out(`exported ${report.concepts} notes in ${report.projects} folders (OKF ${OKF_VERSION})${report.private ? `; ${report.private} private left out` : ""}`);
    return 0;
  },

  // Long-lived like mcp, but it needs a home: a stub's recall id is only good while the original is stored.
  async proxy(c) {
    const { startProxy } = await import("./proxy.ts");
    if (c.args.length) throw new UsageError("use brain proxy [--port N]");
    const port = c.opts.port === undefined ? 47830 : Number(c.opts.port);
    if (!/^\d+$/.test(c.opts.port ?? "0") || port > 65535) throw new UsageError(`expected a port from 0 to 65535, got ${c.opts.port}`);
    const proxy = await startProxy({ port, home: c.home });
    c.io.out(`brain proxy listening on http://127.0.0.1:${proxy.port}`);
    const stop = Promise.withResolvers<void>();
    process.once("SIGINT", stop.resolve);
    process.once("SIGTERM", stop.resolve);
    // A host that starts the proxy on a pipe owns its stdin: closing it is the polite way to stop it.
    // A terminal, NUL or a file is no such host, and NUL ends at once: a detached proxy must stay up.
    let piped = false;
    try {
      const stdin = fstatSync(0);
      piped = !stdin.isFile() && !stdin.isCharacterDevice();
    } catch {
      // No stdin handle at all, as for some services: nothing to watch.
    }
    if (piped) process.stdin.once("end", stop.resolve).once("error", stop.resolve).resume();
    await stop.promise;
    process.off("SIGINT", stop.resolve);
    process.off("SIGTERM", stop.resolve);
    if (piped) process.stdin.off("end", stop.resolve).off("error", stop.resolve).pause();
    await proxy.close();
    return 0;
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
  // An id that became an alias resolves to its owner, so notes/<alias>/ and work/<alias>.md are never read.
  const projects = loadProjects(home);
  const owner = new Map<string, string>();
  for (const [id, e] of Object.entries(projects)) {
    for (const alias of Array.isArray(e.aliases) ? e.aliases : []) if (!projects[alias] && !owner.has(alias)) owner.set(alias, id);
  }
  const notesDir = join(home, "notes");
  if (existsSync(notesDir) && !isDir(notesDir)) errors.push(`${notesDir}: not a directory`);
  for (const entry of list(notesDir)) {
    const path = join(notesDir, entry.name);
    if (!entry.isDirectory()) {
      errors.push(`${path}: not in a project folder, never read`);
      continue;
    }
    if (entry.name !== slug(entry.name)) errors.push(`${path}: folder is not a project id (use ${slug(entry.name)}), never read`);
    if (entry.name === slug(entry.name) && entry.name !== GLOBAL && idFor(entry.name) !== entry.name) errors.push(`${path}: reserved device name, never read (brain move <id> --to ${idFor(entry.name)})`);
    const to = owner.get(entry.name);
    // A folder emptied by `brain move` hides nothing (git keeps no empty folders; the disk may).
    if (to && [path, join(path, "private")].some(dir => list(dir).some(file => file.isFile() && file.name.endsWith(".md")))) errors.push(`${path}: ${entry.name} is an alias of ${to}; its notes are visible to no project (brain move <id> --to ${to})`);
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
    } else if (entry.name !== `${GLOBAL}.md` && idFor(entry.name.slice(0, -3)) !== entry.name.slice(0, -3)) {
      errors.push(`${path}: reserved device name, never read (rename it to work/${idFor(entry.name.slice(0, -3))}.md)`);
    } else if (/^(<{7}|>{7}|={7})( |$)/m.test(readFileSync(path, "utf8"))) {
      errors.push(`${path}: holds merge conflict markers`);
    } else if (owner.has(entry.name.slice(0, -3))) {
      const to = owner.get(entry.name.slice(0, -3));
      errors.push(`${path}: ${entry.name.slice(0, -3)} is an alias of ${to}; never read (merge it into work/${to}.md)`);
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

/**
 * The model message that issued tool call `toolUseId`, from the transcript's tail. Claude Code writes
 * each content block of a message as its own row, so parallel calls share one message id. Undefined
 * when the transcript or the call's row is not there (the host writes transcripts asynchronously).
 */
function toolUseMessage(transcript: unknown, toolUseId: unknown): string | undefined {
  if (typeof transcript !== "string" || !transcript || typeof toolUseId !== "string" || !toolUseId) return undefined;
  try {
    for (const line of hookTail(transcript, 262_144).reverse()) {
      if (!line.includes(toolUseId)) continue;
      let row: { type?: unknown; message?: { id?: unknown; content?: unknown } } | null;
      try { row = JSON.parse(line); } catch { continue; }
      const content = row?.message?.content;
      if (row?.type !== "assistant" || typeof row.message?.id !== "string" || !Array.isArray(content)) continue;
      if (content.some((block: { type?: unknown; id?: unknown } | null) => block?.type === "tool_use" && block.id === toolUseId)) return row.message.id;
    }
  } catch { /* an unreadable transcript leaves the call unplaced */ }
  return undefined;
}

/**
 * Rows Claude Code writes as user rows although nobody typed them: task notifications, slash-command
 * wrappers and their output, interrupt markers, and skill expansions (`<create-pr-command>`).
 */
const HARNESS_ASK = /^\s*(?:<(?:task-notification|command-(?:name|message|args)|local-command-[a-z]+|bash-(?:input|stdout|stderr))>|<[a-z][\w-]*-command>|\[Request interrupted)/;
/** A last-prompt row records a typed slash command bare; its user row is a <command-name> wrapper. */
const SLASH_COMMAND = /^\s*\/[\w:-]+(?:\s|$)/;


/** Reuse the append-only capture log: concurrent tool hooks cannot overwrite each other's edits. */
function saveHookAuto(home: string, project: Project, session: string, transcript: unknown, scratchpad: unknown): void {
  const edited = sessionEdits(home, session, project.root, typeof scratchpad === "string" && scratchpad ? [scratchpad] : []);
  const fields: AutoFields = { edited: edited.length ? edited : undefined };
  if (typeof transcript === "string" && transcript) {
    try {
      let lastPrompt: string | undefined, slashPrompt: string | undefined;
      const commands = new Set<string>();
      for (const line of hookTail(transcript, 262_144).reverse()) {
        let row: { type?: unknown; isSidechain?: unknown; isMeta?: unknown; isCompactSummary?: unknown; origin?: unknown; lastPrompt?: unknown; message?: { content?: unknown } } | null;
        try { row = JSON.parse(line); } catch { continue; }
        // Claude Code's own record of the prompt: the prompt row itself may lie beyond the tail
        // (a long tool turn), or be one row larger than the tail (pasted images).
        if (row?.type === "last-prompt" && typeof row.lastPrompt === "string" && row.lastPrompt.trim() && !HARNESS_ASK.test(row.lastPrompt)) {
          if (!SLASH_COMMAND.test(row.lastPrompt)) lastPrompt ??= row.lastPrompt;
          else slashPrompt ??= row.lastPrompt;
        }
        const wrapper = typeof row?.message?.content === "string" ? /<command-name>(\/[^<\s]+)<\/command-name>/.exec(row.message.content) : null;
        if (wrapper) commands.add(wrapper[1]!);
        if (row?.type !== "user" || row.isSidechain === true || row.isMeta === true || row.isCompactSummary === true) continue;
        if (row.origin && typeof row.origin === "object" && (row.origin as { kind?: unknown }).kind !== "human") continue;
        const content = row.message?.content;
        const text = (typeof content === "string" ? content : Array.isArray(content) ? content.map((block: unknown) => {
          const b = block as { type?: unknown; text?: unknown } | null;
          return b?.type === "text" && typeof b.text === "string" ? b.text : "";
        }).filter(Boolean).join("\n") : "").replace(/^(?:\s*<system-reminder>[\s\S]*?<\/system-reminder>)+/, "");
        if (text.trim() && !HARNESS_ASK.test(text)) { fields.ask = text; break; }
      }
      // Slash text is a typed command only when a wrapper names it (or it names a plugin's, a:b).
      const typed = slashPrompt?.trim().split(/\s/)[0] ?? "";
      fields.ask ??= lastPrompt ?? (commands.has(typed) || typed.includes(":") ? undefined : slashPrompt);
    } catch {
      // The host writes transcripts asynchronously; unavailable ask never loses the edits.
    }
  }
  writeAuto(home, project.id, fields);
}

const sha = (text: string): string => createHash("sha256").update(text).digest("hex");

/**
 * Hooks run in separate processes; hash keys so commands and session names never persist. A
 * child's directory sits inside its parent's, so the parent's cleanup also removes it.
 */
function hookFixDir(home: string, session: string | undefined, agent?: string): string {
  return join(home, "state", "pending-fixes", sha(session ?? "claude-code"), ...(agent ? [sha(agent)] : []));
}

/** Claude Code hook input/output: https://code.claude.com/docs/en/hooks */
function claudeCodeHook(io: Io, explicitHome: string | undefined): number {
  // In-process hook latency, including input/loading/rendering; excludes Node/module startup.
  const started = performance.now();
  let output: object = {};
  let home: string | null = null;
  let event: unknown;
  /**
   * Fail open, but never silently: a swallowed error becomes a local telemetry row, so "the card
   * never came" shows up in `brain stats`. As OMP does.
   */
  const failed = (error: unknown): void => {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    if (home) logUse(home, { kind: "error", project: "", tokens: 0, ms: 0, via: "hook", error: `claude-code ${String(event)}: ${scrubCut(message, 200)}` });
  };
  try {
    home = findHome(explicitHome, io.env);
    // A replay through Windows PowerShell with $OutputEncoding = UTF8 starts with a BOM.
    const payload: unknown = JSON.parse(io.stdin().replace(/^﻿/, "") || "{}");
    if (home && payload && typeof payload === "object" && !Array.isArray(payload)) {
      const p = payload as Record<string, unknown>;
      const cwd = typeof p.cwd === "string" && p.cwd ? p.cwd : io.cwd;
      event = p.hook_event_name;
      const session = typeof p.session_id === "string" && p.session_id ? p.session_id : undefined;
      // agent_type alone also occurs for a main session started with --agent.
      const sub = (typeof p.agent_id === "string" && !!p.agent_id) || event === "SubagentStart" || event === "SubagentStop";
      const agent = sub ? String(p.agent_id ?? "unknown") : undefined;
      const key = agent ? `${session ?? "claude-code"}:agent:${agent}` : session ?? "claude-code";
      // A child's telemetry rows name the child, so it never turns its parent into a "sub" session.
      const logSession = sub ? key : session;
      const fixDir = hookFixDir(home, session, agent);
      const project = resolveProject(home, cwd, io.env);
      // A backgrounded Bash launch "succeeds" at once: that says nothing about the command.
      const background = (p.tool_input as { run_in_background?: unknown } | null | undefined)?.run_in_background === true
        || typeof (p.tool_response as { backgroundTaskId?: unknown } | null | undefined)?.backgroundTaskId === "string";
      if (event === "UserPromptSubmit") {
        captureUserRules(home, p.prompt, project, { subagent: sub });
      } else if (event === "SessionStart" && ["startup", "resume", "clear", "compact"].includes(String(p.source ?? "startup"))) {
        try { rmSync(fixDir, { recursive: true, force: true }); }
        catch { /* pending telemetry cleanup must not suppress the card */ }
        // Compaction drops the card; it comes back in full (owner decision 2026-10-15): the summary
        // keeps goal and next (§8 P4) but not the notes and fixes. A resumed transcript already holds
        // one. With nothing to say, a compaction still gets the lean rule.
        if (p.source !== "resume") {
          // No scanEvents here: catching up on earlier sessions' events took ~300 ms of every start
          // card. SessionEnd and PreCompact run it, off any prompt's path.
          // The card shows global and this project's notes only: other projects' files are not read
          // (SessionStart hook ~500 → ~245 ms on a 541-note home).
          const { notes } = loadVisibleNotes(home, project.id);
          const card = renderCard(home, notes, project, { tools: false, subagent: sub, host: "claude-code" });
          const context = card || (p.source === "compact" ? LEAN_LINE : "");
          if (context) output = { hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: context } };
          if (card) logUse(home, { kind: "card", project: project.id, tokens: estimateTokens(card), ms: performance.now() - started, session: logSession, via: "hook", sub, ids: cardIds(card) });
        }
      } else if (event === "SubagentStart") {
        // The documented hook exposes identity, not the brief: registered docs only.
        const { notes } = loadVisibleNotes(home, project.id);
        const parentEdits = session ? sessionEdits(home, session, project.root) : [];
        const card = renderCard(home, notes, project, { tools: false, subagent: true, host: "claude-code", parentEdits });
        if (card) {
          output = { hookSpecificOutput: { hookEventName: "SubagentStart", additionalContext: card } };
          logUse(home, { kind: "card", project: project.id, tokens: estimateTokens(card), ms: performance.now() - started, session: logSession, via: "hook", sub: true, ids: cardIds(card) });
        }
      } else if ((event === "PostToolUse" && !background) || (event === "PostToolUseFailure" && p.is_interrupt !== true)) {
        const fields = toolEventFrom(p.tool_name, p.tool_input, event === "PostToolUseFailure", p.error);
        appendEvent(home, key, cwd, fields);
        const pendingPath = join(fixDir, sha(fields.command || fields.tool) + ".json");
        // The model message that issued this call, read from the transcript at most once and only when needed.
        let issuedBy: string | undefined | null = null;
        const message = (): string | undefined => (issuedBy === null ? (issuedBy = toolUseMessage(p.transcript_path, p.tool_use_id)) : issuedBy);
        if (session) {
          // The exact operation's file first, then the other pending fixes: a compatible retry
          // (a prepared command) scores the fix, a result of another operation leaves it waiting.
          let names: string[] = [];
          try { names = readdirSync(fixDir).filter((n) => n.endsWith(".json")); }
          catch { /* no pending fixes */ }
          const exact = basename(pendingPath);
          for (const name of [exact, ...names.filter((n) => n !== exact)]) {
            const file = join(fixDir, name);
            const claimed = `${file}.${process.pid}.claimed`;
            let done = false;
            try {
              // Claim before reading: overlapping hooks must not score one firing twice.
              renameSync(file, claimed);
              const pending: unknown = JSON.parse(readFileSync(claimed, "utf8"));
              if (pending && typeof pending === "object" && "id" in pending && typeof pending.id === "string" && "project" in pending && typeof pending.project === "string") {
                const outcome = "tool" in pending && typeof pending.tool === "string" ? outcomeOf(pending as PendingFix, fields) : "other";
                if (outcome === "other") {
                  if (!existsSync(file)) renameSync(claimed, file);
                } else {
                  done = true;
                  // A call of the message that received the fix ran in the same batch: the model had not
                  // seen the fix yet, so that is no outcome. The firing waits for a call of a later message.
                  const fired = "message" in pending && typeof pending.message === "string" ? pending.message : undefined;
                  const current = fired === undefined ? undefined : message();
                  if (fired !== undefined && (current === undefined || current === fired)) {
                    if (!existsSync(file)) renameSync(claimed, file);
                  } else if (outcome !== "unknown") {
                    logUse(home, { kind: "fixout", id: pending.id, project: pending.project, outcome, tokens: 0, ms: 0, session: logSession, via: "hook", sub });
                  }
                }
              }
            } catch { /* missing or torn local pending state is unmeasured */ }
            finally {
              try { rmSync(claimed, { force: true }); }
              catch { /* a locked claim must not suppress the next fix */ }
            }
            if (done) break;
          }
        }
        if (!fields.ok && fields.error) {
          const fix = findFix(loadVisibleNotes(home, project.id).notes, fields.error, project, home, "claude-code", fields.command);
          if (fix) {
            // The full fix once per context (the directory is cleared with the context): a repeat
            // of the same error costs a pointer. As OMP does.
            const shown = join(fixDir, sha(fix.id) + ".shown");
            const text = existsSync(shown) ? `Brain: same fix as above [${fix.id}]` : renderFix(fix);
            output = { hookSpecificOutput: { hookEventName: "PostToolUseFailure", additionalContext: text } };
            logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(text), ms: 0, session: logSession, via: "hook", sub, id: fix.id });
            if (session) {
              try {
                writeAtomic(pendingPath, JSON.stringify({ id: fix.id, project: project.id, message: message(), ...operationOf(fields) }));
                writeAtomic(shown, "");
              } catch { /* telemetry state must not suppress the fix */ }
            }
          }
          const hint = fix ? "" : pathHint(fields.tool, fields.path, fields.error, cwd);
          if (hint) {
            output = { hookSpecificOutput: { hookEventName: "PostToolUseFailure", additionalContext: hint } };
            logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(hint), ms: 0, session: logSession, via: "hook", sub, id: "pathhint" });
            if (session) {
              try { writeAtomic(pendingPath, JSON.stringify({ id: "pathhint", project: project.id, message: message(), ...operationOf(fields) })); }
              catch { /* telemetry state must not suppress the hint */ }
            }
          }
        }
      } else if (session && (event === "SessionEnd" || event === "PreCompact" || event === "SubagentStop")) {
        try { rmSync(fixDir, { recursive: true, force: true }); }
        catch { /* pending telemetry cleanup must not suppress auto-save */ }
        if (!sub) {
          saveHookAuto(home, project, session, p.transcript_path, p.scratchpad_dir);
          // Here, not at SessionStart: catching up on earlier sessions' events takes ~300 ms.
          try { scanEvents(home, loadNotes(home).notes); } catch (error) { failed(error); /* capture never breaks the host */ }
        }
      }
      if (!sub && session && (event === "PostToolUse" || event === "Stop") && typeof p.transcript_path === "string") {
        try {
          for (const line of hookTail(p.transcript_path, 262_144).reverse()) {
            let row: { type?: string; isSidechain?: boolean; message?: { usage?: Record<string, unknown> } };
            try { row = JSON.parse(line); } catch { continue; }
            if (row?.type !== "assistant" || row.isSidechain) continue;
            const usage = row.message?.usage;
            if (!usage || typeof usage.input_tokens !== "number") continue;
            const parts = [usage.input_tokens, usage.cache_read_input_tokens ?? 0, usage.cache_creation_input_tokens ?? 0];
            if (!parts.every(value => typeof value === "number" && Number.isFinite(value) && value >= 0)) break;
            const hint = rolloverHint(home, project.id, session, (parts as number[]).reduce((sum, value) => sum + value, 0));
            if (hint) output = event === "Stop" ? { systemMessage: hint } : { hookSpecificOutput: { hookEventName: "PostToolUse", additionalContext: hint } };
            break;
          }
        } catch { /* asynchronously written transcripts are optional evidence */ }
      }
    }
  } catch (error) {
    failed(error);
    output = {}; // fail open: never break the host session
  }
  io.out(JSON.stringify(output));
  return 0;
}

export async function main(argv: string[], ioOverrides: Partial<Io> = {}): Promise<number> {
  const io: Io = { ...defaultIo(), ...ioOverrides };
  const started = performance.now();
  let parsed: { values: Values; positionals: string[] };
  // PowerShell drops a bare `--` before brain.ps1 sees it. No option has a space before any "=", so
  // such an argument ("-bash: x: command not found") is text: it is held out of parseArgs and put
  // back after. Strict parsing stays: otherwise that text would set -h, -n or -m.
  const end = argv.indexOf("--");
  const held: string[] = [];
  const masked = argv.map((arg, i) => ((end < 0 || i < end) && /^-[^=]*\s/.test(arg) ? `\u0000${held.push(arg) - 1}` : arg));
  const back = (s: string) => (s.startsWith("\u0000") ? held[Number(s.slice(1))] ?? s : s);
  // The sh shim turns Git Bash's path conversion off, so a path option may arrive as /c/….
  const drive = (p: string) => (process.platform === "win32" ? p.replace(/^\/([A-Za-z])(\/|$)/, "$1:/") : p);
  try {
    const raw = parseArgs({ args: masked, options: OPTIONS, allowPositionals: true, strict: true });
    const values = Object.fromEntries(Object.entries(raw.values).map(([k, v]) => [k, typeof v === "string" ? back(v) : Array.isArray(v) ? v.map(back) : v])) as Values;
    if (values.home) values.home = drive(values.home);
    if (values.from) values.from = drive(values.from);
    if (values.evidence) values.evidence = values.evidence.map(drive);
    parsed = { values, positionals: raw.positionals.map(back) };
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
  if (command === "mcp") {
    const { runMcp } = await import("./mcp.ts");
    return runMcp({ home: opts.home, env: opts.project ? { ...io.env, BRAIN_PROJECT: opts.project } : io.env });
  }
  const run = Object.hasOwn(COMMANDS, command) ? COMMANDS[command] : undefined;
  if (!run) {
    io.err(`brain: unknown command ${command} (brain help)`);
    return 1;
  }
  const home = findHome(opts.home, io.env);
  if (!home) {
    io.err(`brain: ${noHome(opts.home, io.env)}`);
    return 2;
  }
  const project: Project = opts.project ? projectById(home, opts.project, io.cwd) : resolveProject(home, io.cwd, io.env);
  try {
    return await run({ home, project, args, opts, io, started });
  } catch (error) {
    io.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
}
