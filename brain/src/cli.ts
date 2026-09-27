/**
 * The `brain` command-line interface: main entry point that parses arguments and dispatches
 * to commands. Handles global options (--home, --project) and all Brain commands.
 */
import { parseArgs } from "node:util";
import { readFileSync } from "node:fs";
import {
  findHome,
  estimateTokens,
  nowIso,
} from "./util.ts";
import {
  loadNotes,
  findNote,
  saveNote,
  createNote,
  retireNote,
  KINDS,
  headline,
} from "./notes.ts";
import { loadProjects, resolveProject, visibleTo, type Project } from "./project.ts";
import {
  recall,
  renderHit,
} from "./search.ts";
import {
  renderCard,
} from "./card.ts";
import {
  readWork,
  writeWork,
  resumeText,
} from "./work.ts";
import {
  listProposals,
  acceptProposal,
  rejectProposal,
  scanEvents,
  scanCommits,
  findFix,
  renderFix,
  appendEvent,
  toolEventFrom,
  pendingCount,
} from "./capture.ts";
import { loadKits, findKit, draftKit } from "./kits.ts";
import { sync, shareNote } from "./sync.ts";
import { convertV3 } from "./convert.ts";
import { logUse, stats } from "./telemetry.ts";
import { gitRoot, GLOBAL } from "./notes.ts";

export interface Io {
  out: (text: string) => void;
  err: (text: string) => void;
  env: NodeJS.ProcessEnv;
  cwd: string;
  stdin: () => string;
}

const DEFAULT_IO: Io = {
  out: (text: string) => process.stdout.write(text + "\n"),
  err: (text: string) => process.stderr.write(text + "\n"),
  env: process.env,
  cwd: process.cwd(),
  stdin: () => readFileSync(0, "utf8"),
};

function usage(): string {
  return `Brain CLI v4 — advisory memory and agent state management

Usage: brain [--home DIR] [--project ID] <command> [options]

Commands:
  help                          Show this help
  card                          Start card for this session
  recall <words…> [--all] [--history] [-n N]
                                Find notes matching query
  note <text> [--kind K] [--error E]… [--tag T]… [--evidence P]…
       [--tested] [--global] [--private]
                                Create a note
  state                         Show working state
  state <text>                  Set working state
  show <id>                     Show a note
  retire <id> [--by <id>]       Retire a note
  tested <id>                   Mark note as tested
  share <id> --tag <tag>        Share note across projects
  review                        List proposals to review
  accept <pid>…                 Accept proposals and turn into notes
  reject <pid>…                 Reject proposals
  kit list                      List available kits
  kit show <name>               Show a kit
  kit new <name> [--from <project>] [--tag T]…
                                Draft a new kit
  sync [--no-push] [-m <message>]
                                Sync Brain to git
  stats [--days N]              Show usage stats
  check                         Health check
  convert --from <v3 home> [--dry-run]
                                Import from V3
  hook claude-code              Claude Code adapter (internal)`;
}

function parseCliArgs(argv: string[]): { command: string; positional: string[]; options: Record<string, unknown> } {
  const result = parseArgs({
    args: argv,
    options: {
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
      n: { type: "string" },
      by: { type: "string" },
      "no-push": { type: "boolean" },
      m: { type: "string" },
      days: { type: "string" },
      from: { type: "string" },
      "dry-run": { type: "boolean" },
    },
    allowPositionals: true,
    strict: true,
  });

  const positional = result.positionals as string[];
  const command = positional[0] ?? "help";
  const args = positional.slice(1);

  return { command, positional: args, options: result.values };
}

async function main(argv: string[], io?: Partial<Io>): Promise<number> {
  const ioImpl: Io = { ...DEFAULT_IO, ...io };
  const start = Date.now();

  try {
    const { command, positional, options } = parseCliArgs(argv);

    // Global options
    const home = findHome(options.home as string | undefined, ioImpl.env);
    if (!home) {
      ioImpl.err("brain: no Brain home (set SECOND_BRAIN_HOME)");
      return 2;
    }

    let project: Project;
    if (options.project) {
      const projects = loadProjects(home);
      project = { id: options.project as string, tags: projects[options.project as string]?.tags ?? [], root: null };
    } else {
      project = resolveProject(home, ioImpl.cwd, ioImpl.env);
    }

    const { notes, errors: noteErrors } = loadNotes(home);

    // Dispatch commands
    switch (command) {
      case "help":
      case undefined:
        ioImpl.out(usage());
        return 0;

      case "card": {
        const card = renderCard(home, notes, project, { tools: false });
        if (card) ioImpl.out(card);
        if (card) {
          const elapsed = Date.now() - start;
          logUse(home, { kind: "card", project: project.id, tokens: estimateTokens(card), ms: elapsed });
        }
        return 0;
      }

      case "recall": {
        const query = positional.join(" ");
        if (!query.trim()) {
          ioImpl.err("brain: recall requires a query");
          return 1;
        }
        const limit = options.n ? parseInt(options.n as string, 10) : undefined;
        const hits = recall(notes, query, {
          project: options.all ? null : project,
          all: (options.all as boolean) ?? false,
          history: (options.history as boolean) ?? false,
          limit,
        });
        if (hits.length === 0) {
          ioImpl.out("no match");
        } else {
          for (const hit of hits) {
            ioImpl.out(renderHit(hit));
          }
        }
        const elapsed = Date.now() - start;
        const totalTokens = hits.reduce((sum, h) => sum + estimateTokens(renderHit(h)), 0);
        logUse(home, { kind: "recall", project: project.id, tokens: totalTokens, ms: elapsed });
        return 0;
      }

      case "note": {
        const text = positional.join(" ");
        if (!text.trim()) {
          ioImpl.err("brain: note requires text");
          return 1;
        }
        const kindOpt = options.kind as string | undefined;
        if (kindOpt && !KINDS.includes(kindOpt as any)) {
          ioImpl.err(`brain: unknown kind ${kindOpt}`);
          return 1;
        }
        const isGlobal = (options.global as boolean) ?? false;
        const isPrivate = (options.private as boolean) ?? false;
        if (isGlobal && isPrivate) {
          ioImpl.err("brain: cannot use both --global and --private");
          return 1;
        }

        const noteProject = isGlobal ? GLOBAL : project.id;
        const note = createNote(home, {
          text,
          project: noteProject,
          kind: (kindOpt ?? "note") as any,
          tags: (options.tag as string[]) ?? [],
          errors: (options.error as string[]) ?? [],
          evidence: (options.evidence as string[]) ?? [],
          tested: (options.tested as boolean) ?? false,
          private: isPrivate,
        });

        ioImpl.out(`saved ${note.id}`);
        const elapsed = Date.now() - start;
        logUse(home, { kind: "note", project: project.id, tokens: estimateTokens(text), ms: elapsed });
        return 0;
      }

      case "state": {
        if (positional.length === 0) {
          const work = readWork(home, project.id);
          const resume = resumeText(work);
          if (resume) {
            ioImpl.out(resume);
          } else {
            ioImpl.out("no working state");
          }
          return 0;
        } else {
          const text = positional.join(" ");
          try {
            writeWork(home, project.id, text);
            const elapsed = Date.now() - start;
            const tokens = estimateTokens(text);
            ioImpl.out(`state saved (${tokens} tokens)`);
            logUse(home, { kind: "state", project: project.id, tokens, ms: elapsed });
            return 0;
          } catch (error) {
            ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
            return 1;
          }
        }
      }

      case "show": {
        if (positional.length === 0) {
          ioImpl.err("brain: show requires an id");
          return 1;
        }
        const id = positional[0] as string;
        const note = findNote(notes, id);
        if (!note) {
          ioImpl.err(`brain: unknown note ${id}`);
          return 1;
        }
        const text = readFileSync(note.path, "utf8");
        ioImpl.out(text);
        return 0;
      }

      case "retire": {
        if (positional.length === 0) {
          ioImpl.err("brain: retire requires an id");
          return 1;
        }
        const id = positional[0] as string;
        const byId = options.by as string | undefined;
        try {
          retireNote(home, id, byId);
          ioImpl.out(`retired ${id}`);
          return 0;
        } catch (error) {
          ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
          return 1;
        }
      }

      case "tested": {
        if (positional.length === 0) {
          ioImpl.err("brain: tested requires an id");
          return 1;
        }
        const id = positional[0] as string;
        const note = findNote(notes, id);
        if (!note) {
          ioImpl.err(`brain: unknown note ${id}`);
          return 1;
        }
        saveNote(home, { ...note, tested: true });
        ioImpl.out(`tested ${id}`);
        return 0;
      }

      case "share": {
        if (positional.length === 0) {
          ioImpl.err("brain: share requires an id");
          return 1;
        }
        const id = positional[0] as string;
        const tag = options.tag as string | undefined;
        if (!tag) {
          ioImpl.err("brain: share requires --tag");
          return 1;
        }
        try {
          shareNote(home, id, tag);
          ioImpl.out(`shared ${id} with tag ${tag}`);
          return 0;
        } catch (error) {
          ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
          return 1;
        }
      }

      case "review": {
        const props = [...scanEvents(home, notes), ...(gitRoot(ioImpl.cwd) ? scanCommits(home, gitRoot(ioImpl.cwd) as string, project.id, notes) : [])];
        if (props.length === 0) {
          ioImpl.out("nothing to review");
          return 0;
        }
        const lines = props.map((p) => {
          const kindStr = p.kind !== "note" ? ` [${p.kind}]` : "";
          const first = p.text.split("\n")[0] ?? "";
          return `${p.id}${kindStr} ${first} (${p.project})`;
        });
        for (const line of lines) {
          ioImpl.out(line);
        }
        ioImpl.out(`accept: brain accept ${props.map((p) => p.id).join(" ")} · reject: brain reject ${props.map((p) => p.id).join(" ")}`);
        return 0;
      }

      case "accept": {
        if (positional.length === 0) {
          ioImpl.err("brain: accept requires proposal ids");
          return 1;
        }
        for (const pid of positional) {
          try {
            const note = acceptProposal(home, pid);
            ioImpl.out(`accepted ${pid} → ${note.id}`);
          } catch (error) {
            ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
            return 1;
          }
        }
        return 0;
      }

      case "reject": {
        if (positional.length === 0) {
          ioImpl.err("brain: reject requires proposal ids");
          return 1;
        }
        for (const pid of positional) {
          try {
            rejectProposal(home, pid);
            ioImpl.out(`rejected ${pid}`);
          } catch (error) {
            ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
            return 1;
          }
        }
        return 0;
      }

      case "kit": {
        const subcommand = positional[0] ?? "";
        const args = positional.slice(1);
        const kits = loadKits(home);

        if (subcommand === "list") {
          if (kits.length === 0) {
            ioImpl.out("no kits");
          } else {
            for (const kit of kits) {
              ioImpl.out(`${kit.name} — ${kit.description}`);
            }
          }
          return 0;
        }

        if (subcommand === "show") {
          if (args.length === 0) {
            ioImpl.err("brain: kit show requires a name");
            return 1;
          }
          const kit = findKit(kits, args[0] as string);
          if (!kit) {
            ioImpl.err(`brain: unknown kit ${args[0]}`);
            return 1;
          }
          ioImpl.out(kit.body);
          return 0;
        }

        if (subcommand === "new") {
          if (args.length === 0) {
            ioImpl.err("brain: kit new requires a name");
            return 1;
          }
          const name = args[0] as string;
          const fromProject = options.from as string | undefined;
          const tagList = (options.tag as string[]) ?? [];
          try {
            const kit = draftKit(home, name, fromProject ?? project.id, notes, tagList.length > 0 ? tagList : undefined);
            ioImpl.out(`drafted ${kit.path}`);
            return 0;
          } catch (error) {
            ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
            return 1;
          }
        }

        ioImpl.err("brain: unknown kit subcommand");
        return 1;
      }

      case "sync": {
        try {
          const result = sync(home, { message: options.m as string | undefined, push: !(options["no-push"] as boolean) });
          ioImpl.out(result.message);
          return 0;
        } catch (error) {
          ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
          return 1;
        }
      }

      case "stats": {
        const days = options.days ? parseInt(options.days as string, 10) : 7;
        const s = stats(home, days);
        ioImpl.out(`last ${s.days} days · ${s.sessions} sessions`);
        for (const kind of Object.keys(s.byKind).sort()) {
          const { count, tokens } = s.byKind[kind] as any;
          ioImpl.out(`${kind}: ${count} (${tokens} tokens)`);
        }
        return 0;
      }

      case "check": {
        let hasErrors = false;
        const activeNotes = notes.filter((n) => !n.retired).length;
        ioImpl.out(`notes: ${notes.length} (${activeNotes} active) · projects: ${Object.keys(loadProjects(home)).length} · kits: ${loadKits(home).length}`);
        if (noteErrors.length > 0) {
          for (const err of noteErrors) {
            ioImpl.err(err);
          }
          hasErrors = true;
        }
        return hasErrors ? 1 : 0;
      }

      case "convert": {
        const fromHome = options.from as string | undefined;
        if (!fromHome) {
          ioImpl.err("brain: convert requires --from");
          return 1;
        }
        try {
          const report = convertV3(fromHome, home, { dryRun: (options["dry-run"] as boolean) ?? false });
          ioImpl.out(`written ${report.written}, skipped ${report.skipped}, projects ${report.projects}`);
          for (const err of report.errors) {
            ioImpl.err(err);
          }
          return report.errors.length > 0 ? 1 : 0;
        } catch (error) {
          ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
          return 1;
        }
      }

      case "hook": {
        const subcommand = positional[0] ?? "";
        if (subcommand === "claude-code") {
          return handleClaudeCodeHook(home, notes, project, ioImpl);
        }
        ioImpl.err("brain: unknown hook");
        return 1;
      }

      default:
        ioImpl.err(`brain: unknown command ${command}`);
        return 1;
    }
  } catch (error) {
    if (error instanceof Error && error.message.includes("Unknown option")) {
      ioImpl.err("brain: " + error.message);
      return 1;
    }
    ioImpl.err(`brain: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
}

function handleClaudeCodeHook(home: string, notes: Note[], project: Project, io: Io): number {
  try {
    const stdin = io.stdin();
    let payload: any;
    try {
      payload = JSON.parse(stdin);
    } catch {
      io.out("{}");
      return 0;
    }

    // SessionStart hook
    if (payload.hook_event_name === "SessionStart") {
      const source = payload.source ?? "startup";
      if (!["startup", "resume", "clear", "compact"].includes(source)) {
        io.out("{}");
        return 0;
      }

      const cwd = payload.payload?.cwd ?? io.cwd;
      const { notes: allNotes } = loadNotes(home);
      let hookProject = project;
      try {
        hookProject = resolveProject(home, cwd, io.env);
      } catch {
        // Use default project
      }

      const card = renderCard(home, allNotes, hookProject, { tools: false });
      if (card) {
        const output = {
          hookSpecificOutput: {
            hookEventName: "SessionStart",
            additionalContext: card,
          },
        };
        io.out(JSON.stringify(output));
      } else {
        io.out("{}");
      }
      return 0;
    }

    // PostToolUseFailure hook
    if (payload.hook_event_name === "PostToolUseFailure") {
      const isInterrupt = payload.is_interrupt === true;
      const error = payload.error;
      const toolName = payload.tool_name;
      const toolInput = payload.tool_input ?? {};

      if (!isInterrupt && error && typeof error === "string") {
        const sessionId = payload.session_id ?? "claude-code";
        const cwd = payload.cwd ?? io.cwd;
        const toolCommand = toolInput.command;
        const toolPath = toolInput.file_path;

        appendEvent(home, sessionId, cwd, {
          tool: toolName ?? "unknown",
          command: toolCommand,
          path: toolPath,
          ok: false,
          error,
        });

        const { notes: allNotes } = loadNotes(home);
        const fix = findFix(allNotes, error, project);

        if (fix) {
          const fixText = renderFix(fix);
          const output = {
            hookSpecificOutput: {
              hookEventName: "PostToolUseFailure",
              additionalContext: fixText,
            },
          };
          io.out(JSON.stringify(output));
          return 0;
        }
      }

      io.out("{}");
      return 0;
    }

    io.out("{}");
    return 0;
  } catch {
    io.out("{}");
    return 0;
  }
}

export { main };
