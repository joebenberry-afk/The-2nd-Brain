/**
 * Second Brain V4 — Oh My Pi (OMP) extension.
 * In-process extension: remembers the last ask, sends a start card, logs tool results,
 * tracks edited paths, and provides
 * brain_recall, brain_note, and brain_state tools. All handlers wrapped in try/catch, never blocks.
 */
import { isAbsolute, relative, resolve } from "node:path";
import { loadNotes, type Note } from "./notes.ts";
import { folderOnly, resolveProject, type Project } from "./project.ts";
import { brainTools, jsonSchema, type Param } from "./tools.ts";
import { appendEvent, captureUserRules, findFix, hostNoise, renderFix, scanEvents, scrubCut, toolEventFrom } from "./capture.ts";
import { cardIds, cardSemantic, LEAN_LINE, renderCard } from "./card.ts";
import { pathHint } from "./paths.ts";
import { logUse, saveToolSchemas } from "./telemetry.ts";
import { estimateTokens, findHome } from "./util.ts";
import { toraScorer } from "./tora.ts";
import { writeAuto } from "./work.ts";
import { rolloverHint } from "./rollover.ts";

export const CARD_TYPE = "brain.card";
const LEAN_TYPE = "brain.lean";
const EDITING_TOOL = /edit|write|patch|create|replace|apply|notebook|move|rename|delete/i;

export interface HostLike {
  on(event: string, handler: (event: unknown, ctx: unknown) => unknown): void;
  registerTool?: (tool: unknown) => void;
  sendMessage?: (message: { customType: string; content: string; display: boolean }, options: { triggerTurn: boolean; deliverAs: "nextTurn" }) => void;
  typebox?: unknown;
  /** Per session: OMP binds each child session to its own API, so this changes only that child. */
  getActiveTools?: () => string[];
  setActiveTools?: (names: string[]) => Promise<void>;
  /** Every configured tool with its schema; the active ones are sent on each request. */
  getAllTools?: () => { name: string; description: string; parameters: unknown; sourceInfo?: { source?: string } }[];
}

type Json = Record<string, unknown>;

/** A fired fix awaiting its outcome. */
interface PendingFix { id: string; project: string }

interface SessionState {
  carded: boolean;
  edited: string[];
  parentEdits?: string[];
  ask?: string;
  /** The project this session works for, as of its last prompt; an isolated child's subagents inherit it. */
  project?: Project;
  /** Notes whose full fix is already in this context; cleared when compaction drops it. */
  fixed?: Set<string>;
  /** Fixes fired in the batch of tool results the model is still waiting on: it has not seen them. */
  shownFixes?: Map<string, PendingFix>;
  /** The latest fix the model has seen per command/tool (or eval detector), awaiting its next result. */
  pendingFixes?: Map<string, PendingFix>;
  /** Messages in the last context this session sent; a drop means earlier text may be gone. */
  contextLength?: number;
  /** A compaction dropped the card: the next tool result or prompt in this session carries it again. */
  cardDue?: boolean;
}

/** Shared by rebound extension instances; entries are removed when their session shuts down. */
const liveSessions = new Map<string, SessionState>();

function asObject(value: unknown): Json | undefined {
  return value !== null && typeof value === "object" ? (value as Json) : undefined;
}

/** A stable per-session key from whatever the host exposes; falls back to "process". */
function sessionKey(ctx: unknown): string {
  const manager = asObject(asObject(ctx)?.sessionManager);
  for (const name of ["getSessionId", "getSessionFile"]) {
    const fn = manager?.[name];
    if (typeof fn === "function") {
      try {
        const value = (fn as () => unknown).call(manager);
        if (typeof value === "string" && value) return value;
      } catch {
        // try the next accessor
      }
    }
  }
  return "process";
}

function cwdOf(ctx: unknown): string | undefined {
  const cwd = asObject(ctx)?.cwd;
  return typeof cwd === "string" && cwd ? cwd : undefined;
}

function sessionManagerOf(ctx: unknown): Json | undefined {
  return asObject(asObject(ctx)?.sessionManager);
}

function call(target: Json | undefined, name: string): unknown {
  const fn = target?.[name];
  if (typeof fn !== "function") return undefined;
  try {
    return (fn as () => unknown).call(target);
  } catch {
    return undefined;
  }
}

/**
 * A subagent (OMP task tool, eval agent(), /tan clone) runs this extension too. It gets the card,
 * but never writes the project's working state: that is the parent's. OMP ≥ 18.3 reports
 * `ctx.agent.kind`; headless top-level runs (`omp -p`) are "main" there. Older hosts: headless and
 * in a child session.
 */
function isSubagent(ctx: unknown): boolean {
  const kind = asObject(asObject(ctx)?.agent)?.kind;
  if (kind === "main" || kind === "sub") return kind === "sub";
  if (asObject(ctx)?.hasUI !== false) return false;
  const manager = sessionManagerOf(ctx);
  return !call(manager, "getSessionFile") || typeof asObject(call(manager, "getHeader"))?.parentSession === "string";
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.map((part) => (asObject(part)?.type === "text" && typeof asObject(part)?.text === "string" ? (asObject(part)?.text as string) : "")).join(" ");
}

/** The last thing the user typed, from the session's own history (not OMP's synthetic continue prompts). */
function lastUserAsk(ctx: unknown): string | undefined {
  const branch = call(sessionManagerOf(ctx), "getBranch");
  if (!Array.isArray(branch)) return undefined;
  for (let i = branch.length - 1; i >= 0; i--) {
    const message = asObject(asObject(branch[i])?.message);
    if (asObject(branch[i])?.type === "message" && message?.role === "user") return cutAsk(textOf(message.content)) || undefined;
  }
  return undefined;
}

/** The session's persisted branch already holds a Brain card after its last compaction. */
function cardSinceCompaction(ctx: unknown): boolean {
  const branch = call(sessionManagerOf(ctx), "getBranch");
  if (!Array.isArray(branch)) return false;
  for (let i = branch.length - 1; i >= 0; i--) {
    const entry = asObject(branch[i]);
    if (entry?.type === "compaction") return false;
    if (entry?.customType === CARD_TYPE) return true;
  }
  return false;
}

function cutAsk(text: string): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > 200 ? collapsed.slice(0, 199).trimEnd() + "…" : collapsed;
}

/** Files an editing tool changed: path-like fields and OMP's `paths` list; never tool URIs (xd://, local://). */
export function editedPaths(input: unknown): string[] {
  const obj = asObject(input);
  if (!obj) return [];
  const found: string[] = [];
  for (const key of ["path", "file_path", "filePath", "file", "paths"]) {
    const value = obj[key];
    for (const item of Array.isArray(value) ? value : [value]) if (typeof item === "string" && item.trim()) found.push(item.trim());
  }
  if (typeof obj.input === "string") {
    for (const match of obj.input.matchAll(/^(?:\[([^\]\r\n]+)#[0-9A-Fa-f]{4}\]|MV ([^\r\n]+))\r?$/gm)) found.push((match[1] ?? match[2]!).trim());
  }
  return [...new Set(found)].filter((p) => !/^[a-z][a-z0-9+.-]*:\/\//i.test(p));
}

function buildCardMessage(content: string, customType = CARD_TYPE): { message: { customType: string; content: string; display: boolean; details: Json } } {
  const details: Json = { v: 4 };
  return {
    message: {
      customType,
      content,
      display: false,
      details,
    },
  };
}

/** Tool parameters: built with the host's TypeBox shim when it has one, else plain JSON schema. */
export function schema(typebox: unknown, props: Record<string, Param>): unknown {
  const tb = asObject(typebox);
  const T = asObject(tb?.Type) ?? tb;
  const fn = (name: string) => (typeof T?.[name] === "function" ? (T[name] as (...a: unknown[]) => unknown).bind(T) : undefined);
  const [obj, str, bool, opt] = [fn("Object"), fn("String"), fn("Boolean"), fn("Optional")];
  if (obj && str && bool && opt) {
    const fields: Record<string, unknown> = {};
    for (const [key, p] of Object.entries(props)) {
      const base = (p.type === "string" ? str : bool)({ description: p.description });
      fields[key] = p.optional ? opt(base) : base;
    }
    return obj(fields);
  }
  return jsonSchema(props);
}

/**
 * Hosts pass (toolCallId, params, signal, onUpdate, ctx) or other orders: params are the second
 * argument when it is an object, else the first object holding `key`; ctx is the last object
 * with a string `cwd`.
 */
export function toolArgs(args: unknown[], key: string): { params: Json; cwd: string; ctx: unknown } {
  const second = asObject(args[1]);
  const params = second && key in second ? second : (args.map(asObject).find((a) => a !== undefined && key in a) ?? second ?? {});
  const ctx = [...args].reverse().find((a) => typeof asObject(a)?.cwd === "string");
  return { params, cwd: cwdOf(ctx) ?? process.cwd(), ctx };
}

/** Tools whose calls routinely outlive an eval cell's 30 s default. */
const SLOW_EVAL_CALL = /\btool\.(?:task|wait|find|web_search)\s*\(|\btool\.read\s*\(\s*\{[^}]*https?:\/\/|\b(?:agent|workpool)\s*\(/;
const BASH_TIMEOUT = /\btool\.bash\s*\([^;]{0,600}?\btimeout\s*:\s*(\d+)/g;

/**
 * An OMP JS eval cell that awaits slow tools yet sets no `timeout` of its own: the host force-kills
 * it at 30 s and every kernel variable is lost. Python cells are never flagged.
 */
export function slowEvalCell(language: unknown, code: unknown, timeout: unknown): boolean {
  if (language !== "js" && language !== "javascript") return false;
  if (typeof code !== "string" || (timeout !== undefined && timeout !== null)) return false;
  if (SLOW_EVAL_CALL.test(code)) return true;
  return [...code.matchAll(BASH_TIMEOUT)].some((m) => Number(m[1]) > 30);
}

/**
 * JavaScript source with `\b` inside a cooked string ('…', "…" or a template without String.raw):
 * a backspace at runtime, never the regex word boundary its author meant. A small lexical scan
 * skips comments, regex literals and String.raw templates, and follows `${…}` interpolation.
 */
export function hasBackspaceEscape(code: string): boolean {
  let i = 0;
  // What precedes a `/`: after a value it divides, otherwise it starts a regex literal.
  let afterValue = false;
  const templates: { depth: number; raw: boolean }[] = []; // each open `${`: brace depth, raw?
  let depth = 0;
  const cooked = (end: string, raw: boolean): boolean => {
    // Scans a string body from i (just past its opening quote); true on a cooked `\b`.
    while (i < code.length) {
      const ch = code[i]!;
      if (ch === "\\") {
        if (!raw && code[i + 1] === "b") return true;
        i += 2;
        continue;
      }
      if (ch === end) {
        i += 1;
        return false;
      }
      if (end === "`" && ch === "$" && code[i + 1] === "{") {
        templates.push({ depth, raw });
        depth += 1;
        i += 2;
        return false;
      }
      if (end !== "`" && ch === "\n") return false;
      i += 1;
    }
    return false;
  };
  while (i < code.length) {
    const ch = code[i]!;
    const next = code[i + 1];
    if (ch === "/" && next === "/") {
      i = code.indexOf("\n", i);
      if (i < 0) break;
      continue;
    }
    if (ch === "/" && next === "*") {
      i = code.indexOf("*/", i + 2);
      if (i < 0) break;
      i += 2;
      continue;
    }
    if (ch === "/" && !afterValue) {
      // Regex literal: skip to its unescaped closing slash, outside character classes.
      let inClass = false;
      for (i += 1; i < code.length && code[i] !== "\n"; i++) {
        if (code[i] === "\\") i += 1;
        else if (code[i] === "[") inClass = true;
        else if (code[i] === "]") inClass = false;
        else if (code[i] === "/" && !inClass) break;
      }
      i += 1;
      afterValue = true;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === "`") {
      const raw = ch === "`" && /String\.raw\s*$/.test(code.slice(Math.max(0, i - 16), i));
      i += 1;
      if (cooked(ch, raw)) return true;
      afterValue = true;
      continue;
    }
    if (ch === "}" && templates.length && templates[templates.length - 1]!.depth === depth - 1) {
      // End of `${…}`: back inside the template text, raw or cooked as it opened.
      const { raw } = templates.pop()!;
      depth -= 1;
      i += 1;
      if (cooked("`", raw)) return true;
      afterValue = true;
      continue;
    }
    if (ch === "{") depth += 1;
    else if (ch === "}") depth -= 1;
    if (!/\s/.test(ch)) afterValue = /[\w$)\]]/.test(ch);
    i += 1;
  }
  return false;
}

/** The pending-fix key of an eval hint: its detector, never a cell's code (a command cannot start with NUL). */
const detectorKey = (id: string): string => "\0eval:" + id;

/**
 * How a JS eval cell answers an eval hint, or undefined when it is not a cell the hint's detector
 * judges: `rawhint` is judged by every JS cell, `evaltimeout` by cells that await slow tools.
 */
export function evalHintOutcome(id: string, language: unknown, code: unknown, timeout: unknown): "helped" | "missed" | undefined {
  if ((language !== "js" && language !== "javascript") || typeof code !== "string") return undefined;
  if (id === "rawhint") return hasBackspaceEscape(code) ? "missed" : "helped";
  if (!slowEvalCell(language, code, undefined)) return undefined;
  return timeout === undefined || timeout === null ? "missed" : "helped";
}

/** A path as the agent should read it: relative to the project root when inside it, forward slashes. */
export function displayPath(path: string, root: string | null, cwd: string): string {
  const absolute = isAbsolute(path) ? path : resolve(cwd, path);
  if (root) {
    const rel = relative(root, absolute);
    const inside = rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
    if (inside) return rel.replace(/\\/g, "/");
  }
  return path.replace(/\\/g, "/");
}

export default function secondBrain(pi: HostLike, env: NodeJS.ProcessEnv = process.env): void {
  // BRAIN=off: the host runs exactly as without the Brain (the benchmark's baseline, or a quick
  // way to rule the Brain out when something misbehaves).
  const home = env.BRAIN === "off" ? undefined : findHome(undefined, env);
  if (!home) {
    // No home: register nothing and return
    return;
  }

  const sessions = new Map<string, SessionState>();
  /**
   * Fail open, but never silently: a swallowed handler error becomes a local telemetry row, so
   * "the card never came" shows up in `brain stats` instead of vanishing.
   */
  const failed = (where: string, error: unknown): void => {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    logUse(home, { kind: "error", project: "", tokens: 0, ms: 0, error: `${where}: ${scrubCut(message, 200)}` });
  };
  const on = (event: string, handler: (event: unknown, ctx: unknown) => unknown): boolean => {
    try {
      pi.on(event, handler);
      return true;
    } catch {
      // an event this host version does not know: that moment is simply not covered
      return false;
    }
  };


  // Helper to get or create session state
  function getSession(key: string): SessionState {
    let state = sessions.get(key);
    if (!state) {
      state = { carded: false, edited: [], ask: undefined };
      sessions.set(key, state);
    }
    return state;
  }
  // Extension factories are rebound for children; share live references, never project auto state.
  function rememberSession(ctx: unknown, state: SessionState): void {
    const id = asObject(asObject(ctx)?.agent)?.id;
    const file = call(sessionManagerOf(ctx), "getSessionFile");
    for (const alias of [sessionKey(ctx), file, id]) if (typeof alias === "string" && alias) liveSessions.set(home + "\0" + alias, state);
  }
  /** The live parent session of a child (as parentEdits finds it), from the host's header or agent id. */
  function liveParent(ctx: unknown): SessionState | undefined {
    const agent = asObject(asObject(ctx)?.agent);
    const header = asObject(call(sessionManagerOf(ctx), "getHeader"));
    for (const alias of [header?.parentSession, agent?.parentId]) {
      if (typeof alias !== "string" || !alias) continue;
      const parent = liveSessions.get(home + "\0" + alias);
      if (parent) return parent;
    }
    return undefined;
  }
  function parentEdits(ctx: unknown): string[] | undefined {
    return liveParent(ctx)?.edited.slice(-8);
  }
  /**
   * An isolated subagent runs in a scratch copy of its parent's checkout (~/.omp/wt/<id>/m) that names
   * no project: its folder is called "m" for every parent, and no note belongs to "m". Such a child
   * works for its live parent's project. A child whose project is declared, or backed by a git
   * remote, or the parent's own, keeps it.
   */
  const inheritedProject = (ctx: unknown, cwd: string): Project | undefined => {
    if (!isSubagent(ctx)) return undefined;
    const parent = liveParent(ctx)?.project;
    if (!parent) return undefined;
    const own = resolveProject(home, cwd, env);
    return own.id !== parent.id && folderOnly(home, own) ? parent : undefined;
  };


  // Tools: one argument each; descriptions stay short because they cost tokens in every context.
  let toolsOn = false;
  if (typeof pi.registerTool === "function" && env.BRAIN_TOOLS !== "off") {
    const register = (definition: unknown): void => {
      try {
        pi.registerTool?.(definition);
        toolsOn = true;
      } catch {
        // a host that rejects the definition keeps the card, the fixes and the CLI
      }
    };
    for (const definition of brainTools) {
      register({
        name: definition.name,
        label: "Brain " + definition.name.slice("brain_".length),
        description: definition.description,
        // OMP moves extension tools behind xd:// unless they are essential; the card names them directly.
        loadMode: "essential",
        approval: definition.name === "brain_recall" ? "read" : "write",
        parameters: schema(pi.typebox, definition.params),
        async execute(...args: unknown[]) {
          const started = performance.now();
          try {
            const required = Object.keys(definition.params).find((k) => !definition.params[k]?.optional) ?? "";
            const { params, cwd, ctx } = toolArgs(args, required);
            const session = sessionKey(ctx);
            const sub = isSubagent(ctx);
            const inherited = inheritedProject(ctx, cwd);
            const result = await definition.run(params, { home, cwd, env: inherited ? { ...env, BRAIN_PROJECT: inherited.id } : env, session, sub, edited: getSession(session).edited });
            if (result.kind) logUse(home, { kind: result.kind, project: result.project, tokens: estimateTokens(result.text), ms: performance.now() - started, session, sub, hits: result.hits, query: result.query, ids: result.ids, judged: result.judged, dropped: result.dropped, tora: result.tora, via: "tool" });
            return { content: [{ type: "text", text: result.text }], details: {} };
          } catch (error) {
            return { content: [{ type: "text", text: `brain: ${error instanceof Error ? error.message : String(error)}` }], details: {} };
          }
        },
      });
    }
  }

  // Observe only actual owner input, never extension continuations or child task instructions.
  on("input", (event, ctx) => {
    try {
      const input = asObject(event);
      if (isSubagent(ctx) || input?.source === "extension") return undefined;
      const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
      captureUserRules(home, input?.text, project);
    } catch (error) { failed("input", error); }
    return undefined;
  });

  /** One session's card: the same at its first prompt and after each compaction. */
  const sessionCard = (ctx: unknown, state: SessionState, project: Project, notes: Note[], prompt: string | undefined, semantic?: Map<string, number>): string => {
    const subagent = isSubagent(ctx);
    // agentbench `on+nochild`: the child-card cost trial's control arm (plan §8.7 kill rule).
    if (subagent && (env.BRAIN_EXPERIMENT ?? "").split(",").includes("nochild")) return "";
    return renderCard(home, notes, project, { tools: toolsOn, subagent, host: "omp", prompt, semantic, parentEdits: subagent ? parentEdits(ctx) ?? state.parentEdits : undefined });
  };
  /**
   * After a compaction the whole card comes back (owner decision 2026-10-15), not only the lean
   * line: OMP's summary keeps goal and next (§8 P4) but drops the notes, recurring fixes and plan
   * anchor. With nothing to say, the lean rule still comes back.
   */
  const compactionCard = (ctx: unknown, state: SessionState, project: Project, notes: Note[], prompt: string | undefined, started: number, semantic?: Map<string, number>): string => {
    const card = sessionCard(ctx, state, project, notes, prompt, semantic);
    if (card) logUse(home, { kind: "card", project: project.id, tokens: estimateTokens(card), ms: performance.now() - started, session: sessionKey(ctx), sub: isSubagent(ctx), ids: cardIds(card) });
    return card || LEAN_LINE;
  };
  /**
   * Renders with Tora's prompt ranking when a live Tora answers within its card budget; with no live
   * Tora (or a prompt naming no topic) it renders at once, so such a host never waits. A failed render
   * is logged and `fallback` returned: the hook never throws into the host.
   */
  const rankedCard = <T>(notes: Note[], project: Project, prompt: string | undefined, render: (semantic?: Map<string, number>) => T, fallback: T, where: string): T | Promise<T> => {
    const pending = cardSemantic(notes, project, prompt, toraScorer(env));
    if (!pending) return render();
    return pending.then(render).catch((error: unknown) => {
      failed(where, error);
      return fallback;
    });
  };

  // Handle before_agent_start
  on("before_agent_start", (event, ctx) => {
    try {
      const started = performance.now();
      const key = sessionKey(ctx);
      const state = getSession(key);
      rememberSession(ctx, state);
      const eventObj = asObject(event);

      // Remember the prompt as the last ask (whitespace-collapsed, 200 chars)
      const prompt = eventObj?.prompt;
      if (typeof prompt === "string" && prompt.trim()) state.ask = cutAsk(prompt);
      // Resolved at every prompt, before the card check: a resumed session skips its card, yet a
      // child it spawns inherits this project.
      const cwd = cwdOf(ctx) ?? process.cwd();
      const project = (state.project = inheritedProject(ctx, cwd) ?? resolveProject(home, cwd, env));

      // Return the card on the first call only.
      // A session resumed in a new process (restart, /resume) already holds its card since the
      // last compaction: a second one repeats the same lines and echoes this session's own ask.
      if (!state.carded && cardSinceCompaction(ctx)) state.carded = true;
      if (!state.carded) {
        state.cardDue = false;
        const { notes } = loadNotes(home);
        const subagent = isSubagent(ctx);
        // Only the parent scans earlier sessions; children share its proposals without rescanning.
        // After the card, not before: catching up on a long session's events took ~400 ms on the
        // first prompt's path. The card's proposal count is then at most one scan behind.
        if (!subagent) {
          setTimeout(() => {
            try {
              scanEvents(home, notes);
            } catch (error) {
              failed("scanEvents", error);
            }
            // What every request pays in tool schemas and system prompt, for `brain stats` to set
            // against actual use. At the first prompt, not session_start: MCP servers have connected
            // by then. The host's enabled list includes tools mounted under xd://, which ship a route
            // line, not a schema; the system prompt names those routes, so they are left out.
            try {
              if (typeof pi.getActiveTools === "function" && typeof pi.getAllTools === "function") {
                const enabled = new Set(pi.getActiveTools());
                const blocks: string[] = Array.isArray(eventObj?.systemPrompt) ? eventObj.systemPrompt.filter((b: unknown): b is string => typeof b === "string") : [];
                const system = blocks.join("\n");
                saveToolSchemas(home, pi.getAllTools().filter(tool => enabled.has(tool.name) && !system.includes(`xd://${tool.name}`)).map(tool => ({
                  name: tool.name,
                  source: tool.sourceInfo?.source ?? "unknown",
                  tokens: estimateTokens(tool.name + tool.description + JSON.stringify(tool.parameters ?? {})),
                })), undefined, blocks.map(estimateTokens));
              }
            } catch (error) {
              failed("toolSchemas", error);
            }
          }, 0);
        }
        const ask = typeof prompt === "string" ? prompt : undefined;
        return rankedCard(notes, project, ask, semantic => {
          const cardContent = sessionCard(ctx, state, project, notes, ask, semantic);
          state.carded = true;
          if (!cardContent) return undefined;
          logUse(home, { kind: "card", project: project.id, tokens: estimateTokens(cardContent), ms: performance.now() - started, session: key, sub: subagent, ids: cardIds(cardContent) });
          return buildCardMessage(cardContent);
        }, undefined, "before_agent_start");
      }
      // A compaction no tool result followed: this prompt brings the card back, ranked by it.
      if (state.cardDue) {
        state.cardDue = false;
        const ask = typeof prompt === "string" ? prompt : undefined;
        const notes = loadNotes(home).notes;
        return rankedCard(notes, project, ask, semantic => {
          const text = compactionCard(ctx, state, project, notes, ask, started, semantic);
          return buildCardMessage(text, text === LEAN_LINE ? LEAN_TYPE : CARD_TYPE);
        }, undefined, "before_agent_start");
      }

      return undefined;
    } catch (error) {
      failed("before_agent_start", error);
      return undefined;
    }
  });

  // Handle context (before every LLM call, after compaction)
  const contextCovered = on("context", (event, ctx) => {
    try {
      const key = sessionKey(ctx);
      const state = getSession(key);

      const messages = asObject(event)?.messages;
      if (!Array.isArray(messages)) return undefined;
      // A context that shrank (/clear, tree navigation, compaction) may have lost a fix shown
      // earlier: the next matching failure gets the full text again, not a dangling pointer.
      if (messages.length < (state.contextLength ?? 0)) {
        state.fixed = undefined;
        state.pendingFixes = undefined;
        state.shownFixes = undefined;
      }
      state.contextLength = messages.length;
      // The model sees the fixes fired since its last call only now: results that ran before this
      // (siblings in the same batch, cells nested in one eval) cannot have followed them.
      if (state.shownFixes) {
        state.pendingFixes = new Map([...(state.pendingFixes ?? []), ...state.shownFixes]);
        state.shownFixes = undefined;
      }
    } catch (error) {
      failed("context", error);
      return undefined;
    }
  });

  on("turn_end", (_event, ctx) => {
    try {
      if (isSubagent(ctx) || !pi.sendMessage) return;
      const usage = asObject(call(asObject(ctx), "getContextUsage"));
      const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
      const hint = rolloverHint(home, project.id, sessionKey(ctx), usage?.tokens);
      if (hint) pi.sendMessage({ customType: "brain.rollover", content: hint, display: false }, { triggerTurn: false, deliverAs: "nextTurn" });
    } catch (error) { failed("turn_end", error); }
  });

  /** Save this session's edits and last ask into the project's working state. */
  const saveAuto = (ctx: unknown): void => {
    if (isSubagent(ctx)) return;
    const state = getSession(sessionKey(ctx));
    const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
    writeAuto(home, project.id, { edited: state.edited.length ? state.edited : undefined, ask: lastUserAsk(ctx) ?? state.ask });
  };

  // /new, /resume, /fork and /branch leave this session without a shutdown: save it first. A fork
  // or branch continues the same work, so it carries the state (and the card) over.
  let carry: SessionState | undefined;
  const leaving = (event: unknown, ctx: unknown) => {
    try {
      saveAuto(ctx);
      const reason = asObject(event)?.reason;
      const state = getSession(sessionKey(ctx));
      state.pendingFixes = state.shownFixes = undefined;
      carry = reason === undefined || reason === "fork" ? { ...state, edited: [...state.edited], fixed: reason === "fork" && state.fixed ? new Set(state.fixed) : undefined } : undefined;
    } catch {
      carry = undefined;
    }
    return undefined;
  };
  const arrived = (_event: unknown, ctx: unknown) => {
    try {
      if (carry) sessions.set(sessionKey(ctx), { ...carry });
    } catch {
      // the new session starts fresh
    }
    carry = undefined;
    return undefined;
  };
  on("session_before_switch", leaving);
  on("session_before_branch", leaving);
  on("session_switch", (event, ctx) => (asObject(event)?.reason === "fork" ? arrived(event, ctx) : ((carry = undefined), undefined)));
  on("session_branch", arrived);

  // Handle session_compact
  const compactCovered = on("session_compact", (_event, ctx) => {
    try {
      const state = getSession(sessionKey(ctx));
      // Written here, not in session_before_compact: /handoff skips that event, and handling it
      // turns off OMP's background compaction.
      saveAuto(ctx);
      state.pendingFixes = state.shownFixes = undefined;
      state.fixed = undefined;
      // The card comes back where the session goes on: inside a run (OMP compacts mid-loop) on the
      // first tool result after this, else with the next prompt. Never as a message of its own: one
      // queued after a run's last step makes OMP start a turn to deliver it, and the Brain never
      // continues host work (V4 §3.2 rule 4).
      state.cardDue = true;

      return undefined;
    } catch (error) {
      failed("session_compact", error);
      return undefined;
    }
  });
  // A host without session_compact still gets the working state saved before it compacts.
  if (!compactCovered) {
    on("session_before_compact", (_event, ctx) => {
      try {
        saveAuto(ctx);
        const state = getSession(sessionKey(ctx));
        state.pendingFixes = state.shownFixes = undefined;
      } catch (error) {
        failed("session_before_compact", error);
        // never block the host's compaction
      }
      return undefined;
    });
  }

  /**
   * A fired fix awaits its outcome only once the model has seen it: after the next `context` event.
   * A host without that event cannot say when, so the next result counts.
   */
  const arm = (state: SessionState, key: string, fix: PendingFix): void => {
    if (contextCovered) (state.shownFixes ??= new Map()).set(key, fix);
    else (state.pendingFixes ??= new Map()).set(key, fix);
  };

  // Handle tool_result
  const toolResult = (event: unknown, ctx: unknown): { content: unknown[] } | undefined => {
    try {
      const started = performance.now();
      const key = sessionKey(ctx);
      const state = getSession(key);
      rememberSession(ctx, state);
      const eventObj = asObject(event);
      const sessionCwd = cwdOf(ctx) ?? process.cwd();

      // Extract tool event fields
      const toolName = eventObj?.toolName;
      const input = eventObj?.input;
      const isError = eventObj?.isError;
      const content = eventObj?.content;
      const shellCwd = toolName === "bash" ? asObject(input)?.cwd : undefined;
      const cwd = typeof shellCwd === "string" && shellCwd ? resolve(sessionCwd, shellCwd) : sessionCwd;

      const fields = toolEventFrom(toolName, input, isError, content);
      // An isolated subagent's scratch copy is no project: its events and fixes belong to its parent's.
      const inherited = inheritedProject(ctx, cwd);
      const projectOfCall = (): Project => inherited ?? resolveProject(home, cwd, env);

      // Log the event
      appendEvent(home, key, inherited?.root ?? cwd, fields);

      // Track edited path on success
      // Only tools that change files count as edits; reads and searches also carry a path.
      if (fields.ok && EDITING_TOOL.test(fields.tool)) {
        const project = resolveProject(home, cwd, env);
        // Relative to the project root when inside it; the last 20 distinct files, most recent last
        const paths = editedPaths(input).map((p) => displayPath(p, project.root, cwd));
        state.edited = [...state.edited.filter((f) => !paths.includes(f)), ...paths].slice(-20);
      }

      const code = asObject(input)?.code;
      const language = asObject(input)?.language;

      // Record whether a fix the model has seen helped, on the next command/tool result.
      const failureKey = fields.command || fields.tool || "unknown";
      const pending = state.pendingFixes?.get(failureKey);
      if (pending && (fields.ok || !hostNoise(fields.tool, fields.error ?? ""))) {
        state.pendingFixes!.delete(failureKey);
        logUse(home, { kind: "fixout", ...pending, outcome: fields.ok ? "helped" : "missed", tokens: 0, ms: 0, session: key, sub: isSubagent(ctx), via: "tool" });
      }
      // Eval hints are keyed by detector, not by the cell's code: the next JS cell the detector can
      // judge scores them, whatever it runs.
      if (toolName === "eval") {
        for (const id of ["evaltimeout", "rawhint"]) {
          const hint = state.pendingFixes?.get(detectorKey(id));
          const outcome = hint ? evalHintOutcome(id, language, code, asObject(input)?.timeout) : undefined;
          if (!hint || !outcome) continue;
          state.pendingFixes!.delete(detectorKey(id));
          logUse(home, { kind: "fixout", ...hint, outcome, tokens: 0, ms: 0, session: key, sub: isSubagent(ctx), via: "tool" });
        }
      }

      // On failed result, find and append a fix if available
      if (!fields.ok && fields.error) {
        const project = projectOfCall();
        const { notes } = loadNotes(home);
        const fix = findFix(notes, fields.error, project, home, "omp");

        if (fix) {
          // The full fix once per context: a repeat of the same error costs a pointer, not the text.
          const fixed = (state.fixed ??= new Set());
          const fixText = fixed.has(fix.id) ? `Brain: same fix as above [${fix.id}]` : renderFix(fix);
          fixed.add(fix.id);
          const contentArray = Array.isArray(content) ? content : typeof content === "string" && content ? [{ type: "text", text: content }] : [];
          // Hosts join text blocks without a separator: the fix must start on its own line.
          const resultContent = [...contentArray, { type: "text", text: `\n${fixText}` }];
          logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(fixText), ms: performance.now() - started, session: key, sub: isSubagent(ctx), id: fix.id });
          arm(state, failureKey, { id: fix.id, project: project.id });
          return { content: resultContent };
        }
        const hint = pathHint(fields.tool, fields.path, fields.error, cwd);
        if (hint) {
          const contentArray = Array.isArray(content) ? content : typeof content === "string" && content ? [{ type: "text", text: content }] : [];
          logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(hint), ms: performance.now() - started, session: key, sub: isSubagent(ctx), id: "pathhint" });
          arm(state, failureKey, { id: "pathhint", project: project.id });
          return { content: [...contentArray, { type: "text", text: `\n${hint}` }] };
        }
      }

      // `'\b'` inside a plain JS string in an eval script is a backspace, so a grep for a word
      // boundary silently matches nothing and agents chase a "tool bug" (benchmark autopsy: 15 of
      // 44 GPT runs). With this line the next script dropped the broken pattern every time.
      // JavaScript only: in Python r'\bword\b' is right, and String.raw is not Python.
      if (toolName === "eval" && (language === "js" || language === "javascript") && typeof code === "string" && hasBackspaceEscape(code)) {
        const fixed = (state.fixed ??= new Set());
        const hint = fixed.has("rawhint") ? "Brain: quoted '\\b' is a backspace again (see above)." : "Brain: in this script a quoted '\\b' is a backspace, not a word boundary; write String.raw`\\bword\\b` or '\\\\b'.";
        fixed.add("rawhint");
        const contentArray = Array.isArray(content) ? content : typeof content === "string" && content ? [{ type: "text", text: content }] : [];
        const project = projectOfCall().id;
        logUse(home, { kind: "fix", project, tokens: estimateTokens(hint), ms: performance.now() - started, session: key, sub: isSubagent(ctx), id: "rawhint" });
        arm(state, detectorKey("rawhint"), { id: "rawhint", project });
        return { content: [...contentArray, { type: "text", text: `\n${hint}` }] };
      }

      // The cell dies at 30 s unless the eval call sets `timeout`; a kill resets every variable.
      // A failed result whose fix already fired returned above, so the text is never doubled.
      if (toolName === "eval" && slowEvalCell(language, code, asObject(input)?.timeout) && !(state.fixed ??= new Set()).has("evaltimeout")) {
        state.fixed.add("evaltimeout");
        const hint = "Brain: this eval cell can be force-killed at 30 s, losing its variables; pass eval `timeout` (seconds).";
        const contentArray = Array.isArray(content) ? content : typeof content === "string" && content ? [{ type: "text", text: content }] : [];
        const project = projectOfCall().id;
        logUse(home, { kind: "fix", project, tokens: estimateTokens(hint), ms: performance.now() - started, session: key, sub: isSubagent(ctx), id: "evaltimeout" });
        arm(state, detectorKey("evaltimeout"), { id: "evaltimeout", project });
        return { content: [...contentArray, { type: "text", text: `\n${hint}` }] };
      }

      return undefined;
    } catch (error) {
      failed("tool_result", error);
      return undefined;
    }
  };
  // After a compaction inside a run, the card rides on the first tool result: the model reads it at
  // its next call, and the Brain queues no message of its own. Inside a tool result it is no
  // brain.card entry, so a process restarted before the next compaction cards once more.
  on("tool_result", (event, ctx) => {
    const result = toolResult(event, ctx);
    try {
      const state = getSession(sessionKey(ctx));
      if (!state.cardDue) return result;
      state.cardDue = false;
      const started = performance.now();
      const cwd = cwdOf(ctx) ?? process.cwd();
      const project = state.project ?? inheritedProject(ctx, cwd) ?? resolveProject(home, cwd, env);
      const original = asObject(event)?.content;
      const content = result?.content ?? (Array.isArray(original) ? original : typeof original === "string" && original ? [{ type: "text", text: original }] : []);
      const notes = loadNotes(home).notes;
      return rankedCard(notes, project, state.ask, semantic => ({ content: [...content, { type: "text", text: `\n${compactionCard(ctx, state, project, notes, state.ask, started, semantic)}` }] }), result, "tool_result");
    } catch (error) {
      failed("tool_result", error);
      return result;
    }
  });

  // session_start has no prompt. Capture live parent paths here; before_agent_start supplies the brief.
  on("session_start", async (_event, ctx) => {
    try {
      const state = getSession(sessionKey(ctx));
      rememberSession(ctx, state);
      if (!isSubagent(ctx)) return undefined;
      state.parentEdits = parentEdits(ctx);
      if (!toolsOn || typeof pi.getActiveTools !== "function" || typeof pi.setActiveTools !== "function") return undefined;
      const active = pi.getActiveTools();
      const keep = active.filter((name) => name !== "brain_note" && name !== "brain_state");
      if (keep.length !== active.length) await pi.setActiveTools(keep);
    } catch (error) {
      failed("session_start", error);
    }
    return undefined;
  });

  // Handle session_shutdown
  on("session_shutdown", (_event, ctx) => {
    try {
      saveAuto(ctx);
      const state = getSession(sessionKey(ctx));
      state.pendingFixes = state.shownFixes = undefined;
    } catch (error) {
      failed("session_shutdown", error);
      // never block the host's exit
    } finally {
      const state = sessions.get(sessionKey(ctx));
      for (const [alias, live] of liveSessions) if (live === state) liveSessions.delete(alias);
    }
    return undefined;
  });
}
