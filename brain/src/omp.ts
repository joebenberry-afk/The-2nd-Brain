/**
 * Second Brain V4 — Oh My Pi (OMP) extension.
 * In-process extension with no subprocess or network: remembers the last ask, inserts resume
 * cards after compaction, logs tool results, tracks edited paths and failures, and provides
 * brain_recall, brain_note, and brain_state tools. All handlers wrapped in try/catch, never blocks.
 */
import { isAbsolute, relative, resolve } from "node:path";
import { loadNotes } from "./notes.ts";
import { resolveProject } from "./project.ts";
import { brainTools, jsonSchema, type Param } from "./tools.ts";
import { appendEvent, errorSignature, findFix, renderFix, scanEvents, scrubCut, toolEventFrom } from "./capture.ts";
import { renderCard } from "./card.ts";
import { logUse } from "./telemetry.ts";
import { estimateTokens, findHome } from "./util.ts";
import { readWork, renderResume, writeAuto } from "./work.ts";

export const CARD_TYPE = "brain.card";
const EDITING_TOOL = /edit|write|patch|create|replace|apply|notebook|move|rename|delete/i;

export interface HostLike {
  on(event: string, handler: (event: unknown, ctx: unknown) => unknown): void;
  registerTool?: (tool: unknown) => void;
  typebox?: unknown;
}

type Json = Record<string, unknown>;

interface SessionState {
  carded: boolean;
  /** A card went out with a prompt that has not reached the model yet. */
  cardPending?: boolean;
  resume?: { content: string; at: number };
  resumeSeen: boolean;
  edited: string[];
  failure?: string;
  ask?: string;
}

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

function buildCardMessage(content: string, isResume = false): { message: { customType: string; content: string; display: boolean; details: Json } } {
  const details: Json = { v: 4 };
  if (isResume) {
    details.resume = true;
  }
  return {
    message: {
      customType: CARD_TYPE,
      content,
      display: false,
      details,
    },
  };
}

function buildResumeMessage(content: string, at: number): { role: string; customType: string; content: string; display: boolean; details: Json; timestamp: number } {
  return {
    role: "custom",
    customType: CARD_TYPE,
    content,
    display: false,
    details: { v: 4, resume: true },
    timestamp: at,
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
  const home = findHome(undefined, env);
  if (!home) {
    // No home: register nothing and return
    return;
  }

  const sessions = new Map<string, SessionState>();
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
      state = { carded: false, resumeSeen: false, edited: [], ask: undefined, failure: undefined };
      sessions.set(key, state);
    }
    return state;
  }

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
        execute(...args: unknown[]) {
          const started = performance.now();
          try {
            const required = Object.keys(definition.params).find((k) => !definition.params[k]?.optional) ?? "";
            const { params, cwd, ctx } = toolArgs(args, required);
            const session = sessionKey(ctx);
            const sub = isSubagent(ctx);
            const result = definition.run(params, { home, cwd, env, session, sub });
            if (result.kind) logUse(home, { kind: result.kind, project: result.project, tokens: estimateTokens(result.text), ms: performance.now() - started, session, sub, hits: result.hits, via: "tool" });
            return { content: [{ type: "text", text: result.text }], details: {} };
          } catch (error) {
            return { content: [{ type: "text", text: `brain: ${error instanceof Error ? error.message : String(error)}` }], details: {} };
          }
        },
      });
    }
  }

  // Handle before_agent_start
  on("before_agent_start", (event, ctx) => {
    try {
      const started = performance.now();
      const key = sessionKey(ctx);
      const state = getSession(key);
      const eventObj = asObject(event);

      // Remember the prompt as the last ask (whitespace-collapsed, 200 chars)
      const prompt = eventObj?.prompt;
      if (typeof prompt === "string" && prompt.trim()) state.ask = cutAsk(prompt);

      // Fallback: if resume exists and was never seen by context, deliver it now
      if (state.resume && !state.resumeSeen) {
        const msg = buildCardMessage(state.resume.content, true);
        state.resume = undefined;
        state.resumeSeen = true;
        state.carded = true; // Mark card as sent so later calls return nothing
        state.cardPending = true;
        return msg;
      }

      // Return card on first call only (unless resume was already delivered via context)
      if (!state.carded && !state.resumeSeen) {
        const { notes } = loadNotes(home);
        const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
        const subagent = isSubagent(ctx);
        // Only the parent scans earlier sessions; children share its proposals without rescanning.
        if (!subagent) {
          try {
            scanEvents(home, notes);
          } catch {
            // the card matters more than the count
          }
        }
        const cardContent = renderCard(home, notes, project, { tools: toolsOn, subagent, prompt: typeof prompt === "string" ? prompt : undefined });

        if (cardContent) {
          state.carded = true;
          state.cardPending = true;
          logUse(home, { kind: "card", project: project.id, tokens: estimateTokens(cardContent), ms: performance.now() - started, session: key, sub: subagent });
          return buildCardMessage(cardContent);
        }
        state.carded = true;
        return undefined;
      }

      if (!state.carded) {
        state.carded = true;
      }

      return undefined;
    } catch {
      return undefined;
    }
  });

  // Handle context (before every LLM call, after compaction)
  on("context", (event, ctx) => {
    try {
      const key = sessionKey(ctx);
      const state = getSession(key);
      state.cardPending = false;

      // Only insert if we have a resume card and event.messages is an array
      if (!state.resume) return undefined;

      const messages = asObject(event)?.messages;
      if (!Array.isArray(messages)) return undefined;

      // After the compaction summary: Anthropic's native compaction drops every block before it.
      const at = messages.findLastIndex((m) => asObject(m)?.role === "compactionSummary") + 1;
      // A resume card already there (delivered with a prompt) is enough.
      if (messages.slice(at).some((m) => asObject(m)?.customType === CARD_TYPE && asObject(asObject(m)?.details)?.resume === true)) {
        state.resumeSeen = true;
        return undefined;
      }

      // Same object values on every call, so the prompt cache prefix stays stable.
      const resumeMsg = buildResumeMessage(state.resume.content, state.resume.at);
      state.resumeSeen = true;
      return { messages: [...messages.slice(0, at), resumeMsg, ...messages.slice(at)] };
    } catch {
      return undefined;
    }
  });

  /** Save this session's edits, last failure and last ask into the project's working state. */
  const saveAuto = (ctx: unknown): void => {
    if (isSubagent(ctx)) return;
    const state = getSession(sessionKey(ctx));
    const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
    writeAuto(home, project.id, { edited: state.edited.length ? state.edited : undefined, failure: state.failure, ask: lastUserAsk(ctx) ?? state.ask });
  };

  // /new, /resume, /fork and /branch leave this session without a shutdown: save it first. A fork
  // or branch continues the same work, so it carries the state (and the card) over.
  let carry: SessionState | undefined;
  const leaving = (event: unknown, ctx: unknown) => {
    try {
      saveAuto(ctx);
      const reason = asObject(event)?.reason;
      const state = getSession(sessionKey(ctx));
      carry = reason === undefined || reason === "fork" ? { ...state, edited: [...state.edited], resume: reason === "fork" ? state.resume : undefined, resumeSeen: reason === "fork" ? state.resumeSeen : false, cardPending: false } : undefined;
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
      const started = performance.now();
      const key = sessionKey(ctx);
      const state = getSession(key);
      // Written here, not in session_before_compact: /handoff skips that event, and handling it
      // turns off OMP's background compaction.
      saveAuto(ctx);
      // A card sent with the prompt this compaction runs before is still ahead of the model.
      if (state.cardPending) {
        state.resume = undefined;
        return undefined;
      }

      // Freeze only working state; compaction never resends notes, kits or the tool footer.
      const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
      const cardContent = isSubagent(ctx) ? "" : renderResume(readWork(home, project.id));

      if (cardContent) {
        const now = Date.now();
        state.resume = { content: cardContent, at: now };
        state.resumeSeen = false;
        logUse(home, { kind: "resume", project: project.id, tokens: estimateTokens(cardContent), ms: performance.now() - started, session: key });
      } else {
        state.resume = undefined;
      }

      return undefined;
    } catch {
      return undefined;
    }
  });
  // A host without session_compact still gets the working state saved before it compacts.
  if (!compactCovered) {
    on("session_before_compact", (_event, ctx) => {
      try {
        saveAuto(ctx);
      } catch {
        // never block the host's compaction
      }
      return undefined;
    });
  }

  // Handle tool_result
  on("tool_result", (event, ctx) => {
    try {
      const started = performance.now();
      const key = sessionKey(ctx);
      const state = getSession(key);
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

      // Log the event
      appendEvent(home, key, cwd, fields);

      // Track edited path on success
      // Only tools that change files count as edits; reads and searches also carry a path.
      if (fields.ok && EDITING_TOOL.test(fields.tool)) {
        const project = resolveProject(home, cwd, env);
        // Relative to the project root when inside it; the last 20 distinct files, most recent last
        const paths = editedPaths(input).map((p) => displayPath(p, project.root, cwd));
        state.edited = [...state.edited.filter((f) => !paths.includes(f)), ...paths].slice(-20);
      }

      // Track last failure
      if (!fields.ok && fields.error) {
        const tool = fields.tool || "unknown";
        const cmd = fields.command;
        // Masked before the signature cuts it: a cut must not keep half a secret.
        const sig = errorSignature(scrubCut(fields.error, 2000));
        if (cmd) {
          state.failure = `${cmd} → ${sig}`;
        } else {
          state.failure = `${tool} → ${sig}`;
        }
      }

      // On failed result, find and append a fix if available
      if (!fields.ok && fields.error) {
        const project = resolveProject(home, cwd, env);
        const { notes } = loadNotes(home);
        const fix = findFix(notes, fields.error, project);

        if (fix) {
          const fixText = renderFix(fix);
          const contentArray = Array.isArray(content) ? content : typeof content === "string" && content ? [{ type: "text", text: content }] : [];
          const resultContent = [...contentArray, { type: "text", text: fixText }];
          logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(fixText), ms: performance.now() - started, session: key, sub: isSubagent(ctx) });
          return { content: resultContent };
        }
      }

      return undefined;
    } catch {
      return undefined;
    }
  });

  // Handle session_shutdown
  on("session_shutdown", (_event, ctx) => {
    try {
      saveAuto(ctx);
    } catch {
      // never block the host's exit
    }
    return undefined;
  });
}
