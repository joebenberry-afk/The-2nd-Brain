/**
 * Second Brain V4 — Oh My Pi (OMP) extension.
 * In-process extension with no subprocess or network: remembers the last ask, inserts resume
 * cards after compaction, logs tool results, tracks edited paths and failures, and provides
 * brain_recall, brain_note, and brain_state tools. All handlers wrapped in try/catch, never blocks.
 */
import { isAbsolute, relative, resolve } from "node:path";
import { createNote, findSameHeadline, GLOBAL, KINDS, loadNotes, type Kind } from "./notes.ts";
import { resolveProject } from "./project.ts";
import { answer } from "./search.ts";
import { appendEvent, errorSignature, findFix, renderFix, toolEventFrom } from "./capture.ts";
import { renderCard } from "./card.ts";
import { logUse, type UseKind } from "./telemetry.ts";
import { estimateTokens, findHome } from "./util.ts";
import { writeAuto, writeWork, type AutoFields } from "./work.ts";

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

interface Param {
  type: "string" | "boolean";
  description: string;
  optional?: boolean;
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
  return {
    type: "object",
    properties: Object.fromEntries(Object.entries(props).map(([k, p]) => [k, { type: p.type, description: p.description }])),
    required: Object.entries(props).filter(([, p]) => !p.optional).map(([k]) => k),
    additionalProperties: false,
  };
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

function requireString(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${name} is required`);
  return value;
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
  const on = (event: string, handler: (event: unknown, ctx: unknown) => unknown): void => {
    try {
      pi.on(event, handler);
    } catch {
      // an event this host version does not know: that moment is simply not covered
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
    const tool = (
      name: string,
      label: string,
      description: string,
      props: Record<string, Param>,
      run: (params: Json, cwd: string, session: string) => { text: string; kind: UseKind; project: string },
    ) => ({
      name,
      label,
      description,
      parameters: schema(pi.typebox, props),
      execute(...args: unknown[]) {
        const started = performance.now();
        try {
          const required = Object.keys(props).find((k) => !props[k]?.optional) ?? "";
          const { params, cwd, ctx } = toolArgs(args, required);
          const session = sessionKey(ctx);
          const result = run(params, cwd, session);
          logUse(home, { kind: result.kind, project: result.project, tokens: estimateTokens(result.text), ms: performance.now() - started, session });
          return { content: [{ type: "text", text: result.text }], details: {} };
        } catch (error) {
          return { content: [{ type: "text", text: `brain: ${error instanceof Error ? error.message : String(error)}` }], details: {} };
        }
      },
    });

    register(
      tool(
        "brain_recall",
        "Brain recall",
        'Search long-term memory from earlier sessions and projects: up to 3 answers, or "no match". Pass a note id to read that note in full.',
        { query: { type: "string", description: "a question, keywords, or a note id" }, all: { type: "boolean", description: "search every project", optional: true } },
        (params, cwd) => {
          const query = requireString(params.query, "query");
          const project = resolveProject(home, cwd, env);
          return { text: answer(loadNotes(home).notes, query, { project, all: params.all === true }), kind: "recall", project: project.id };
        },
      ),
    );
    register(
      tool(
        "brain_note",
        "Brain note",
        "Save a durable learning for future sessions (decision, gotcha, procedure or fact). First line is the headline.",
        {
          text: { type: "string", description: "the learning; first line is the headline" },
          kind: { type: "string", description: `one of ${KINDS.join(", ")}`, optional: true },
          error: { type: "string", description: "the error message this fixes", optional: true },
          tested: { type: "boolean", description: "you verified it works", optional: true },
          global: { type: "boolean", description: "useful beyond this project", optional: true },
        },
        (params, cwd) => {
          const text = requireString(params.text, "text");
          const kind = typeof params.kind === "string" && (KINDS as readonly string[]).includes(params.kind) ? (params.kind as Kind) : "note";
          const error = typeof params.error === "string" && params.error.trim() ? params.error.trim() : undefined;
          const project = resolveProject(home, cwd, env);
          const scope = params.global === true ? GLOBAL : project.id;
          const same = findSameHeadline(loadNotes(home).notes, text, scope, project.tags);
          if (same) return { text: `already noted ${same.id}`, kind: "note", project: project.id };
          const note = createNote(home, {
            text,
            project: scope,
            kind,
            errors: error ? [error] : [],
            tested: params.tested === true,
            source: "agent",
          });
          return { text: `saved ${note.id}`, kind: "note", project: project.id };
        },
      ),
    );
    register(
      tool(
        "brain_state",
        "Brain state",
        "Replace this project's working state (goal, done, next, watch out) so work resumes after compaction or in the next session. Update it when the plan changes; under 120 words.",
        { text: { type: "string", description: "goal, done, next, watch out" } },
        (params, cwd) => {
          const project = resolveProject(home, cwd, env);
          const work = writeWork(home, project.id, requireString(params.text, "text"));
          return { text: `state saved (${estimateTokens(work.text)} tokens)`, kind: "state", project: project.id };
        },
      ),
    );
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
      if (typeof prompt === "string" && prompt.trim()) {
        const collapsed = prompt.replace(/\s+/g, " ").trim();
        state.ask = collapsed.length > 200 ? collapsed.slice(0, 199).trimEnd() + "…" : collapsed;
      }

      // Fallback: if resume exists and was never seen by context, deliver it now
      if (state.resume && !state.resumeSeen) {
        const msg = buildCardMessage(state.resume.content, true);
        state.resume = undefined;
        state.resumeSeen = true;
        state.carded = true; // Mark card as sent so later calls return nothing
        return msg;
      }

      // Return card on first call only (unless resume was already delivered via context)
      if (!state.carded && !state.resumeSeen) {
        const { notes } = loadNotes(home);
        const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
        const cardContent = renderCard(home, notes, project, { tools: toolsOn });

        if (cardContent) {
          state.carded = true;
          logUse(home, { kind: "card", project: project.id, tokens: estimateTokens(cardContent), ms: performance.now() - started, session: key });
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

      // Only insert if we have a resume card and event.messages is an array
      if (!state.resume) return undefined;

      const messages = asObject(event)?.messages;
      if (!Array.isArray(messages)) return undefined;

      // Check if a resume card is already present
      for (const msg of messages) {
        const m = asObject(msg);
        const details = asObject(m?.details);
        if (m?.customType === CARD_TYPE && details?.resume === true) {
          // Already present, don't add
          return undefined;
        }
      }

      // Insert the resume card at index 0 with the saved timestamp (same object values for cache)
      const resumeMsg = buildResumeMessage(state.resume.content, state.resume.at);
      state.resumeSeen = true;
      return { messages: [resumeMsg, ...messages] };
    } catch {
      return undefined;
    }
  });

  // Handle session_before_compact
  on("session_before_compact", (_event, ctx) => {
    try {
      const key = sessionKey(ctx);
      const state = getSession(key);

      // Write auto section with edited paths, last failure, last ask
      const autoFields: AutoFields = {
        edited: state.edited.length > 0 ? state.edited : undefined,
        failure: state.failure,
        ask: state.ask,
      };

      const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
      writeAuto(home, project.id, autoFields);

      return undefined;
    } catch {
      return undefined;
    }
  });

  // Handle session_compact
  on("session_compact", (_event, ctx) => {
    try {
      const started = performance.now();
      const key = sessionKey(ctx);
      const state = getSession(key);

      // Build fresh card and freeze as resume
      const { notes } = loadNotes(home);
      const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
      const cardContent = renderCard(home, notes, project, { tools: toolsOn });

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

  // Handle tool_result
  on("tool_result", (event, ctx) => {
    try {
      const started = performance.now();
      const key = sessionKey(ctx);
      const state = getSession(key);
      const eventObj = asObject(event);
      const cwd = cwdOf(ctx) ?? process.cwd();
      const project = resolveProject(home, cwd, env);

      // Extract tool event fields
      const toolName = eventObj?.toolName;
      const input = eventObj?.input;
      const isError = eventObj?.isError;
      const content = eventObj?.content;

      const fields = toolEventFrom(toolName, input, isError, content);

      // Log the event
      appendEvent(home, key, cwd, fields);

      // Track edited path on success
      // Only tools that change files count as edits; reads and searches also carry a path.
      if (fields.ok && fields.path && EDITING_TOOL.test(fields.tool)) {
        const path = fields.path;
        // Check if path is inside project.root; if so, make it relative
        const normalizedPath = displayPath(path, project.root, cwd);

        // The last 20 distinct files, most recently edited last
        state.edited = [...state.edited.filter((f) => f !== normalizedPath), normalizedPath].slice(-20);
      }

      // Track last failure
      if (!fields.ok && fields.error) {
        const tool = fields.tool || "unknown";
        const cmd = fields.command;
        const sig = errorSignature(fields.error);
        if (cmd) {
          state.failure = `${cmd} → ${sig}`;
        } else {
          state.failure = `${tool} → ${sig}`;
        }
      }

      // On failed result, find and append a fix if available
      if (!fields.ok && fields.error) {
        const { notes } = loadNotes(home);
        const fix = findFix(notes, fields.error, project);

        if (fix) {
          const fixText = renderFix(fix);
          const contentArray = Array.isArray(content) ? content : typeof content === "string" && content ? [{ type: "text", text: content }] : [];
          const resultContent = [...contentArray, { type: "text", text: fixText }];
          logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(fixText), ms: performance.now() - started, session: key });
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
      const key = sessionKey(ctx);
      const state = getSession(key);
      const cwd = cwdOf(ctx) ?? process.cwd();
      const project = resolveProject(home, cwd, env);

      // Write auto section (same as before compaction)
      const autoFields: AutoFields = {
        edited: state.edited.length > 0 ? state.edited : undefined,
        failure: state.failure,
        ask: state.ask,
      };

      writeAuto(home, project.id, autoFields);

      return undefined;
    } catch {
      return undefined;
    }
  });

}
