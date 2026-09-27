/**
 * Second Brain V4 — Oh My Pi (OMP) extension.
 * In-process extension with no subprocess or network: remembers the last ask, inserts resume
 * cards after compaction, logs tool results, tracks edited paths and failures, and provides
 * brain_recall, brain_note, and brain_state tools. All handlers wrapped in try/catch, never blocks.
 */
import { createNote, loadNotes, type Kind } from "./notes.ts";
import { resolveProject, type Project } from "./project.ts";
import { recall, renderHit } from "./search.ts";
import { appendEvent, errorSignature, findFix, renderFix, toolEventFrom } from "./capture.ts";
import { renderCard } from "./card.ts";
import { logUse } from "./telemetry.ts";
import { estimateTokens, findHome, nowIso, writeAtomic } from "./util.ts";
import { writeAuto, writeWork, readWork, type AutoFields } from "./work.ts";
import { join } from "node:path";

export const CARD_TYPE = "brain.card";

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

function buildCardMessage(content: string): { message: { customType: string; content: string; display: boolean; details: Json } } {
  return {
    message: {
      customType: CARD_TYPE,
      content,
      display: false,
      details: { v: 4, resume: true },
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

export default function secondBrain(pi: HostLike, env: NodeJS.ProcessEnv = process.env): void {
  const home = findHome(undefined, env);
  if (!home) {
    // No home: register nothing and return
    return;
  }

  const sessions = new Map<string, SessionState>();

  // Helper to get or create session state
  function getSession(key: string): SessionState {
    let state = sessions.get(key);
    if (!state) {
      state = { carded: false, resumeSeen: false, edited: [], ask: undefined, failure: undefined };
      sessions.set(key, state);
    }
    return state;
  }

  // Helper to make timestamp value stable for cache (milliseconds)
  function resumeTimestamp(): number {
    return Date.now();
  }

  // Handle before_agent_start
  pi.on("before_agent_start", (event, ctx) => {
    try {
      const key = sessionKey(ctx);
      const state = getSession(key);
      const eventObj = asObject(event);

      // Capture the prompt (whitespace-collapsed, cut to 200 tokens = 800 chars)
      const prompt = eventObj?.prompt;
      if (typeof prompt === "string" && prompt.trim()) {
        const collapsed = prompt.replace(/\s+/g, " ").trim();
        state.ask = collapsed.length > 800 ? collapsed.slice(0, 799).trimEnd() + "…" : collapsed;
      }

      // Return card on first call only, or fallback if resume was never seen
      if (!state.carded) {
        const { notes } = loadNotes(home);
        const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
        const cardContent = renderCard(home, notes, project, { tools: typeof pi.registerTool === "function" });

        if (cardContent) {
          state.carded = true;
          logUse(home, { kind: "card", project: project.id, tokens: estimateTokens(cardContent), ms: 0, session: key });
          return buildCardMessage(cardContent);
        }
        state.carded = true;
        return undefined;
      }

      // After compaction, if resume was never seen, deliver it as fallback
      if (state.resume && !state.resumeSeen) {
        const msg = buildCardMessage(state.resume.content);
        state.resume = undefined;
        state.resumeSeen = true;
        return msg;
      }

      return undefined;
    } catch {
      return undefined;
    }
  });

  // Handle context (before every LLM call, after compaction)
  pi.on("context", (event, ctx) => {
    try {
      const key = sessionKey(ctx);
      const state = getSession(key);

      // Only insert if we have a resume card, haven't seen it yet, and event.messages is an array
      if (!state.resume) return undefined;
      if (state.resumeSeen) return undefined;

      const messages = asObject(event)?.messages;
      if (!Array.isArray(messages)) return undefined;

      // Check if a resume card is already present
      for (const msg of messages) {
        const m = asObject(msg);
        if (m?.customType === CARD_TYPE && m?.details?.resume === true) {
          // Already present, don't add
          return undefined;
        }
      }

      // Insert the resume card at index 0 with the saved timestamp
      const resumeMsg = buildResumeMessage(state.resume.content, state.resume.at);
      state.resumeSeen = true;
      return { messages: [resumeMsg, ...messages] };
    } catch {
      return undefined;
    }
  });

  // Handle session_before_compact
  pi.on("session_before_compact", (_event, ctx) => {
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
  pi.on("session_compact", (_event, ctx) => {
    try {
      const key = sessionKey(ctx);
      const state = getSession(key);

      // Build fresh card and freeze as resume
      const { notes } = loadNotes(home);
      const project = resolveProject(home, cwdOf(ctx) ?? process.cwd(), env);
      const cardContent = renderCard(home, notes, project, { tools: typeof pi.registerTool === "function" });

      if (cardContent) {
        const now = Date.now();
        state.resume = { content: cardContent, at: now };
        state.resumeSeen = false;
        logUse(home, { kind: "resume", project: project.id, tokens: estimateTokens(cardContent), ms: 0, session: key });
      } else {
        state.resume = undefined;
      }

      return undefined;
    } catch {
      return undefined;
    }
  });

  // Handle tool_result
  pi.on("tool_result", (event, ctx) => {
    try {
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
      if (fields.ok && fields.path) {
        const path = fields.path;
        // Check if path is inside project.root; if so, make it relative
        let normalizedPath = path;
        if (project.root) {
          try {
            // Simple relative path computation for forward slashes
            if (path.startsWith(project.root)) {
              normalizedPath = path.slice(project.root.length).replace(/^[\\/]+/, "").replace(/\\/g, "/");
            }
          } catch {
            // Keep original path on error
          }
        }

        // Keep last 20 unique edited paths
        if (!state.edited.includes(normalizedPath)) {
          state.edited.push(normalizedPath);
          if (state.edited.length > 20) {
            state.edited.shift();
          }
        }
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
          const contentArray = Array.isArray(content) ? content : [];
          const resultContent = [...contentArray, { type: "text", text: fixText }];
          logUse(home, { kind: "fix", project: project.id, tokens: estimateTokens(fixText), ms: 0, session: key });
          return { content: resultContent };
        }
      }

      return undefined;
    } catch {
      return undefined;
    }
  });

  // Handle session_shutdown
  pi.on("session_shutdown", (_event, ctx) => {
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

  // Register tools if supported and enabled
  if (typeof pi.registerTool === "function" && env.BRAIN_TOOLS !== "off") {
    // Helper to build parameters schema
    function buildParams(typebox: unknown) {
      if (!typebox || typeof typebox !== "object") {
        // No typebox: return plain JSON schema
        return {
          type: "object",
          properties: {
            query: { type: "string" },
            all: { type: "boolean" },
          },
          required: ["query"],
          additionalProperties: false,
        };
      }

      const tb = typebox as Record<string, unknown>;
      // If typebox has Type, build with it
      if (typeof tb.Type === "object" && tb.Type !== null) {
        const Type = tb.Type as Record<string, unknown>;
        try {
          // Try to build: Type.Object({ query: Type.String(), all: Type.Optional(Type.Boolean()) })
          // For now, return plain schema as fallback
          return {
            type: "object",
            properties: {
              query: { type: "string" },
              all: { type: "boolean" },
            },
            required: ["query"],
            additionalProperties: false,
          };
        } catch {
          return {
            type: "object",
            properties: {
              query: { type: "string" },
              all: { type: "boolean" },
            },
            required: ["query"],
            additionalProperties: false,
          };
        }
      }

      return {
        type: "object",
        properties: {
          query: { type: "string" },
          all: { type: "boolean" },
        },
        required: ["query"],
        additionalProperties: false,
      };
    }

    // brain_recall tool
    const recallTool = {
      name: "brain_recall",
      label: "Brain recall",
      description: "Search long-term memory from earlier sessions and projects. Returns up to 3 one-line answers, or \"no match\".",
      parameters: buildParams(pi.typebox),
      execute(...args: unknown[]) {
        try {
          // Extract params and cwd defensively
          let query: string | undefined;
          let all = false;
          let cwd: string | undefined;

          // Try to find params in second argument if it's an object
          if (args.length > 1) {
            const second = asObject(args[1]);
            if (second) {
              if (typeof second.query === "string") query = second.query;
              if (typeof second.all === "boolean") all = second.all;
            }
          }

          // If not found, look in first object argument
          if (!query) {
            for (const arg of args) {
              const obj = asObject(arg);
              if (obj && typeof obj.query === "string") {
                query = obj.query;
                break;
              }
            }
          }

          // Find cwd from last object argument
          for (let i = args.length - 1; i >= 0; i--) {
            const obj = asObject(args[i]);
            if (obj && typeof obj.cwd === "string") {
              cwd = obj.cwd;
              break;
            }
          }

          if (!query) {
            return { content: [{ type: "text", text: "brain: query required" }], details: {} };
          }

          const { notes } = loadNotes(home);
          const project = resolveProject(home, cwd ?? process.cwd(), env);
          const start = Date.now();
          const hits = recall(notes, query, { project, all: all === true, limit: 3 });
          const ms = Date.now() - start;

          const text =
            hits.length > 0
              ? hits.map((h) => renderHit(h)).join("\n")
              : "no match";

          logUse(home, { kind: "recall", project: project.id, tokens: estimateTokens(text), ms, session: sessionKey(asObject(args[args.length - 1])) });

          return { content: [{ type: "text", text }], details: {} };
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error);
          return { content: [{ type: "text", text: `brain: ${msg}` }], details: {} };
        }
      },
    };

    // brain_note tool
    const noteTool = {
      name: "brain_note",
      label: "Brain note",
      description:
        "Save a durable learning for future sessions (decision, gotcha, procedure or fact). First line is the headline.",
      parameters: {
        type: "object",
        properties: {
          text: { type: "string" },
          kind: { type: "string" },
          error: { type: "string" },
          tested: { type: "boolean" },
          global: { type: "boolean" },
        },
        required: ["text"],
        additionalProperties: false,
      },
      execute(...args: unknown[]) {
        try {
          let text: string | undefined;
          let kind: string | undefined;
          let error: string | undefined;
          let tested: boolean | undefined;
          let global: boolean | undefined;
          let cwd: string | undefined;

          // Look for params in second argument
          if (args.length > 1) {
            const second = asObject(args[1]);
            if (second) {
              if (typeof second.text === "string") text = second.text;
              if (typeof second.kind === "string") kind = second.kind;
              if (typeof second.error === "string") error = second.error;
              if (typeof second.tested === "boolean") tested = second.tested;
              if (typeof second.global === "boolean") global = second.global;
            }
          }

          // If not found, search all arguments
          if (!text) {
            for (const arg of args) {
              const obj = asObject(arg);
              if (obj && typeof obj.text === "string") {
                text = obj.text;
                break;
              }
            }
          }

          // Find cwd
          for (let i = args.length - 1; i >= 0; i--) {
            const obj = asObject(args[i]);
            if (obj && typeof obj.cwd === "string") {
              cwd = obj.cwd;
              break;
            }
          }

          if (!text) {
            return { content: [{ type: "text", text: "brain: text required" }], details: {} };
          }

          const project = resolveProject(home, cwd ?? process.cwd(), env);
          const start = Date.now();
          const noteKind = (kind as Kind | undefined) || "note";
          const note = createNote(home, {
            text,
            project: global ? "global" : project.id,
            kind: noteKind,
            errors: error ? [error] : [],
            tested: tested === true,
            source: "agent",
          });
          const ms = Date.now() - start;

          const msg = `saved ${note.id}`;
          logUse(home, { kind: "note", project: project.id, tokens: estimateTokens(msg), ms, session: sessionKey(asObject(args[args.length - 1])) });

          return { content: [{ type: "text", text: msg }], details: {} };
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error);
          return { content: [{ type: "text", text: `brain: ${msg}` }], details: {} };
        }
      },
    };

    // brain_state tool
    const stateTool = {
      name: "brain_state",
      label: "Brain state",
      description:
        "Replace this project's working state (goal, done, next, watch out) so work resumes after compaction or in the next session. Update it when the plan changes; under 120 words.",
      parameters: {
        type: "object",
        properties: {
          text: { type: "string" },
        },
        required: ["text"],
        additionalProperties: false,
      },
      execute(...args: unknown[]) {
        try {
          let text: string | undefined;
          let cwd: string | undefined;

          // Look for params in second argument
          if (args.length > 1) {
            const second = asObject(args[1]);
            if (second && typeof second.text === "string") {
              text = second.text;
            }
          }

          // If not found, search all arguments
          if (!text) {
            for (const arg of args) {
              const obj = asObject(arg);
              if (obj && typeof obj.text === "string") {
                text = obj.text;
                break;
              }
            }
          }

          // Find cwd
          for (let i = args.length - 1; i >= 0; i--) {
            const obj = asObject(args[i]);
            if (obj && typeof obj.cwd === "string") {
              cwd = obj.cwd;
              break;
            }
          }

          if (!text) {
            return { content: [{ type: "text", text: "brain: text required" }], details: {} };
          }

          const project = resolveProject(home, cwd ?? process.cwd(), env);
          const start = Date.now();
          const work = writeWork(home, project.id, text);
          const ms = Date.now() - start;

          const msg = `state saved (${estimateTokens(work.text)} tokens)`;
          logUse(home, { kind: "state", project: project.id, tokens: estimateTokens(msg), ms, session: sessionKey(asObject(args[args.length - 1])) });

          return { content: [{ type: "text", text: msg }], details: {} };
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error);
          return { content: [{ type: "text", text: `brain: ${msg}` }], details: {} };
        }
      },
    };

    pi.registerTool(recallTool);
    pi.registerTool(noteTool);
    pi.registerTool(stateTool);
  }
}
