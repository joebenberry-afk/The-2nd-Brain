/**
 * Second Brain for the DeepSeek Harness.
 *
 * One Host plugin, five jobs the Brain's own surfaces cannot do in DSH:
 *
 * 1. **Start card.** Every fresh agent gets the Brain's start card as one
 *    injected context message before its first step, so a session begins where
 *    the last one stopped. Resumed sessions already carry their card, a
 *    compaction that dropped it gets it back, and subagents get the child card.
 * 2. **Tools.** `brain_recall`, `brain_note` and `brain_state` with the Brain's
 *    own when-to-act descriptions. Child agents get the tools but no card, and
 *    `brain_state` is hidden: the working state belongs to the parent session.
 * 3. **Known fix.** A failed tool call gets the one tested fix the Brain knows
 *    for that error appended to its result, or nothing.
 * 4. **Learning.** Every tool outcome is recorded in the Brain's capture log
 *    (`brain event`), so `brain review` and tested-fix learning see DSH
 *    sessions, and repeated owner rules become proposals. At compaction and
 *    session end the plugin asks the Brain to scan them (`brain scan`).
 * 5. **Cost.** The Brain's context hand-off hint (`brain rollover`) reads the
 *    Harness's own token meter and lands before the next step at 150k.
 *
 * Calls go through one warm `brain serve` process per host, with the note cache
 * paid once instead of once per call: a recall or fix costs ~30 ms warm against
 * ~380 ms for a fresh CLI process. If the checkout predates `serve`, the plugin
 * falls back to one process per call and keeps the older feature set.
 *
 * The Brain is optional: without a checkout the plugin logs why and stays inert.
 *
 * @module @local/dsh-second-brain
 */
import { execFile, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";

/** Loader row name and the services the plugin cannot work without. */
export const name = "second-brain";
export const inject = ["tools", "workingDirectory", "agents"];

/** A Brain command that may judge recall; a working directory or a slow judge can take seconds. */
const CALL_TIMEOUT_MS = 30_000;
/** The start card, a known fix and the context hint are best-effort: never hold a session or a result. */
const HINT_TIMEOUT_MS = 8_000;
/** Recording one tool outcome is local file work; a busy service must not delay the model. */
const EVENT_TIMEOUT_MS = 4_000;
/** A failed result's diagnostic, not a whole log, is what a fix matches on. */
const MAX_ERROR_CHARS = 4_000;

/** JSON schema shared by the three tools' output declaration. */
const TEXT_OUTPUT = {
  type: "object",
  additionalProperties: false,
  properties: { text: { type: "string" } },
  required: ["text"],
};

/** Render one tool value as the model-facing text block. */
function renderText(_args, value) {
  return [{ type: "text", text: value.text }];
}

/** Normalize an agent identity for telemetry. */
function sessionOf(agent) {
  return typeof agent?.id === "string" ? agent.id : "dsh";
}

/** Child agents may read and write notes, but never overwrite the parent's plan. */
function isChild(agent) {
  return typeof agent?.session?.header?.parentSession === "string";
}

/** A message the model reads as context, framed so it cannot be mistaken for the user's words. */
function notice(text, kind, summary) {
  return {
    id: randomUUID(),
    role: "user",
    content: [{ type: "text", text: `<second-brain>\n${text}\n</second-brain>` }],
    source: { kind, form: "notice", summary },
  };
}

/** A session that already holds a card (seed, fork) must not get a second one. */
function hasCard(agent) {
  const nodes = agent?.session?.surface?.nodes;
  if (!Array.isArray(nodes)) return false;
  return nodes.some((seq) => {
    const event = agent.session.eventAt(seq);
    return event?.type === "user/message" && event.data?.source?.kind === "second-brain";
  });
}

/** Join the text blocks of a content list. */
function textOf(content) {
  if (!Array.isArray(content)) return "";
  return content
    .filter((block) => block?.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("\n")
    .trim();
}

/** A fix already carries its `Brain: ` prefix; a legacy `brain fix` answer does not. */
function fixBlock(text) {
  return text.startsWith("Brain: ") ? `\n${text}` : `\nBrain: ${text}`;
}

/** A message for a swallowed plugin failure, never for the model. */
function messageOf(error) {
  return error instanceof Error ? error.message : String(error);
}

/**
 * One warm `brain serve` process (NDJSON requests) plus a per-call fallback.
 *
 * Requests are written in call order and answered in order; a Brain call that
 * outlives its timeout kills the process, and the next call starts a fresh one.
 * A checkout without `serve` is detected once, then every call runs the CLI as
 * before. Failures resolve as `{ok: false}`; only the host decides what to show.
 */
class BrainService {
  constructor({ executable, cli, home, log, spawnProcess, execFileProcess }) {
    this.executable = executable;
    this.cli = cli;
    this.home = home;
    this.log = log;
    this.spawnProcess = spawnProcess;
    this.execFileProcess = execFileProcess;
    this.child = null;
    this.pending = new Map();
    this.writes = Promise.resolve();
    this.nextId = 1;
    this.stderr = "";
    this.legacy = false;
    this.closed = false;
  }

  /** Stop the process and release every waiter; used when the plugin is disposed. */
  close() {
    if (this.closed) return;
    this.closed = true;
    this.stop(new Error("second-brain: service closed"));
  }

  start() {
    if (this.child || this.legacy || this.closed) return;
    let child;
    try {
      child = this.spawnProcess(this.executable, [this.cli, "serve"], {
        cwd: this.home,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env, SECOND_BRAIN_HOME: this.home },
      });
    } catch (error) {
      this.rejectAll(new Error(`brain serve could not start: ${messageOf(error)}`));
      return;
    }
    this.child = child;
    this.stderr = "";
    // A child that died mid-write must not raise an unhandled stream error in the host.
    child.stdin?.on("error", () => {});
    child.stderr?.on("data", (chunk) => {
      this.stderr = (this.stderr + chunk.toString("utf8")).slice(-4_000);
    });
    child.on("error", (error) => this.exited(child, `brain serve failed: ${messageOf(error)}`));
    // `close`, not `exit`: stderr is complete by then, which is how an older checkout is recognized.
    child.on("close", (code, signal) => this.exited(child, `brain serve exited (${code ?? signal ?? "?"})`));
    createInterface({ input: child.stdout, crlfDelay: Infinity }).on("line", (line) => this.receive(line));
  }

  exited(child, detail) {
    if (this.child !== child) return;
    this.child = null;
    if (!this.legacy && /unknown command serve/.test(this.stderr)) {
      this.legacy = true;
      this.log("this Brain checkout has no serve command; using one process per call");
    }
    this.rejectAll(new Error(detail));
  }

  rejectAll(error) {
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer);
      this.pending.delete(id);
      entry.reject(error);
    }
  }

  stop(error) {
    const child = this.child;
    this.child = null;
    this.rejectAll(error);
    if (child) {
      try {
        child.stdin?.end();
        child.kill();
      } catch { /* an already dead process is fine */ }
    }
  }

  receive(line) {
    let reply;
    try {
      reply = JSON.parse(line);
    } catch {
      return;
    }
    const entry = this.pending.get(reply?.id);
    if (!entry) return;
    this.pending.delete(reply.id);
    clearTimeout(entry.timer);
    if (reply.code === 0) {
      entry.resolve({ ok: true, text: String(reply.out ?? "").trim() });
    } else {
      entry.resolve({ ok: false, text: String(reply.err || reply.out || "brain command failed").trim() });
    }
  }

  request(argv, { cwd, session, stdin, timeout = CALL_TIMEOUT_MS, signal, killOnTimeout = false }) {
    this.start();
    const child = this.child;
    if (!child) return Promise.reject(new Error("brain serve unavailable"));
    const id = this.nextId++;
    const payload = JSON.stringify({
      id,
      argv,
      ...(cwd ? { cwd } : {}),
      ...(session ? { session } : {}),
      ...(stdin === undefined ? {} : { stdin }),
    });
    return new Promise((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timer);
        signal?.removeEventListener?.("abort", onAbort);
      };
      const timer = setTimeout(() => {
        this.pending.delete(id);
        // A wedged tool call is worth replacing; a best-effort card or capture call is not: killing
        // the service would also fail whatever else it is serving.
        if (killOnTimeout) this.stop(new Error("second-brain: brain call timed out"));
        reject(new Error("second-brain: brain call timed out"));
      }, timeout);
      const onAbort = () => {
        this.pending.delete(id);
        cleanup();
        reject(new Error("second-brain: brain call cancelled"));
      };
      if (signal) {
        if (signal.aborted) {
          clearTimeout(timer);
          reject(new Error("second-brain: brain call cancelled"));
          return;
        }
        signal.addEventListener("abort", onAbort, { once: true });
      }
      this.pending.set(id, {
        timer,
        resolve: (value) => { cleanup(); resolve(value); },
        reject: (error) => { cleanup(); reject(error); },
      });
      this.writes = this.writes.then(() => {
        if (this.child !== child) return;
        try {
          child.stdin.write(`${payload}\n`);
        } catch { /* the exit handler answers this call */ }
      }, () => {});
    });
  }

  /** Run one Brain command, warm when possible, one CLI process when the checkout is older. */
  async call(argv, options = {}) {
    if (!this.legacy) {
      try {
        return await this.request(argv, options);
      } catch (error) {
        if (this.legacy) return this.runCli(legacyArgv(argv), options);
        if (options.signal?.aborted) return { ok: false, text: "second-brain: brain call cancelled" };
        return { ok: false, text: messageOf(error) };
      }
    }
    return this.runCli(legacyArgv(argv), options);
  }

  runCli(args, { cwd, session, stdin, timeout = CALL_TIMEOUT_MS, signal }) {
    if (!args) return Promise.resolve({ ok: false, text: "second-brain: this Brain checkout predates the command" });
    return new Promise((resolve) => {
      let settled = false;
      const settle = (value) => {
        if (!settled) {
          settled = true;
          resolve(value);
        }
      };
      try {
        const child = this.execFileProcess(
          this.executable,
          [this.cli, ...args],
          {
            cwd,
            timeout,
            windowsHide: true,
            maxBuffer: 8 * 1024 * 1024,
            env: { ...process.env, SECOND_BRAIN_HOME: this.home, ...(session ? { BRAIN_SESSION: session } : {}) },
            ...(signal ? { signal } : {}),
          },
          (error, stdout, stderr) => {
            if (error) {
              settle({ ok: false, text: String(stderr || stdout || error.message || "").trim() || "brain command failed" });
            } else {
              settle({ ok: true, text: String(stdout || "").trim() });
            }
          },
        );
        child.stdin?.end(stdin === undefined ? "" : stdin);
        child.on("error", () => settle({ ok: false, text: "brain command could not start" }));
      } catch (error) {
        settle({ ok: false, text: messageOf(error) });
      }
    });
  }
}

/** The same command, without parts an older checkout does not know. `null` means unavailable. */
function legacyArgv(argv) {
  switch (argv[0]) {
    case "card":
      return ["card"];
    case "event":
    case "prompt":
    case "scan":
    case "rollover":
      return null;
    default:
      return argv;
  }
}

/**
 * @param ctx - the Cordis host context.
 * @param config - the plugin row's configuration.
 * @param deps - process primitives, injectable so the protocol can be tested in-process.
 */
export function apply(ctx, config = {}, deps = {}) {
  const spawnProcess = deps.spawn ?? spawn;
  const execFileProcess = deps.execFile ?? execFile;
  const home = String(config.home || process.env.SECOND_BRAIN_HOME || "").trim();
  const cli = home ? join(home, "brain", "bin", "brain.mjs") : "";
  if (!home || !existsSync(cli)) {
    ctx.logger?.warn?.(
      `second-brain: no Brain checkout (home=${home || "unset"}); set SECOND_BRAIN_HOME or config.home to enable it`,
    );
    return;
  }
  const executable = String(config.node || process.env.DSH_SECOND_BRAIN_NODE || "node");
  const enabled = {
    card: config.card !== false,
    tools: config.tools !== false,
    fix: config.fix !== false,
    capture: config.capture !== false,
    rollover: config.rollover !== false,
    childCard: config.childCard !== false,
  };
  const log = (message) => ctx.logger?.warn?.(`second-brain: ${message}`);
  const service = new BrainService({ executable, cli, home, log, spawnProcess, execFileProcess });
  try {
    ctx.effect?.(() => () => service.close(), "second-brain.service");
  } catch (error) {
    log(`service cleanup not installed: ${messageOf(error)}`);
  }

  /** Resolve the calling session's directory; non-agent callers run in the host's. */
  async function cwdFor(exec) {
    if (!exec?.agent) return process.cwd();
    return ctx.workingDirectory.ensure(exec.agent, exec.signal);
  }

  /** The number of assistant messages so far: calls of one message share a step. */
  const steps = new Map();

  if (enabled.tools) {
    ctx.tools.register({
      name: "brain_recall",
      description:
        "Before exploring unfamiliar ground, choosing a tool/stack, or retrying a failing command; call it in the same batch as your first search or read, since a recall alone costs a full turn. A note id returns the full note.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          query: { type: "string", description: "a question, keywords, or a note id" },
          all: { type: "boolean", description: "search every project" },
        },
        required: ["query"],
      },
      output: { schema: TEXT_OUTPUT, render: renderText },
      async execute(args, exec) {
        const query = typeof args.query === "string" ? args.query.trim() : "";
        if (!query) throw new Error("query is required");
        const argv = ["recall", query];
        if (args.all === true) argv.push("--all");
        const result = await service.call(argv, { cwd: await cwdFor(exec), session: sessionOf(exec.agent), signal: exec.signal, killOnTimeout: true });
        if (!result.ok) throw new Error(result.text);
        return { text: result.text || "no match" };
      },
    });

    ctx.tools.register({
      name: "brain_note",
      description:
        "Save what the repo cannot tell you: a decision and why, an environment gotcha with its error line, what failed before, an owner preference. Not facts readable from code.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          text: { type: "string", description: "the learning; first line is the headline" },
          kind: {
            type: "string",
            description: "one of note, fact, decision, gotcha, procedure",
          },
          error: { type: "string", description: "the error message this fixes" },
          tested: { type: "boolean", description: "you verified it works" },
          global: { type: "boolean", description: "useful beyond this project" },
          replaces: { type: "string", description: "id of a note this corrects" },
        },
        required: ["text"],
      },
      output: { schema: TEXT_OUTPUT, render: renderText },
      async execute(args, exec) {
        const text = typeof args.text === "string" ? args.text.trim() : "";
        if (!text) throw new Error("text is required");
        const argv = ["note", text];
        if (typeof args.kind === "string" && args.kind.trim()) argv.push("--kind", args.kind.trim());
        if (typeof args.error === "string" && args.error.trim()) argv.push("--error", args.error.trim());
        if (args.tested === true) argv.push("--tested");
        if (args.global === true) argv.push("--global");
        if (typeof args.replaces === "string" && args.replaces.trim()) argv.push("--replaces", args.replaces.trim());
        const result = await service.call(argv, { cwd: await cwdFor(exec), session: sessionOf(exec.agent), signal: exec.signal, killOnTimeout: true });
        if (!result.ok) throw new Error(result.text);
        return { text: result.text || "saved" };
      },
    });

    ctx.tools.register({
      name: "brain_state",
      description:
        "When the goal or next step changes, save working state: Goal:/Next:/Watch out:/Done:, under 60 words. See: path#heading keeps it anchored to the repo plan.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          text: { type: "string", description: "goal, done, next, watch out" },
        },
        required: ["text"],
      },
      output: { schema: TEXT_OUTPUT, render: renderText },
      async execute(args, exec) {
        if (isChild(exec.agent)) {
          return { text: "not saved: working state belongs to the parent session" };
        }
        const text = typeof args.text === "string" ? args.text.trim() : "";
        if (!text) throw new Error("text is required");
        const result = await service.call(["state", text], { cwd: await cwdFor(exec), session: sessionOf(exec.agent), signal: exec.signal, killOnTimeout: true });
        if (!result.ok) throw new Error(result.text);
        return { text: result.text || "state saved" };
      },
    });
  }

  if (enabled.tools) {
    // A child's plan is the parent's: hide the tool instead of showing one that can only refuse.
    ctx.on("agent/created", ({ agent }) => {
      if (!isChild(agent) || !agent?.ctx?.tools?.restrict) return;
      try {
        agent.ctx.effect(() => agent.ctx.tools.restrict({ deny: ["brain_state"] }), "second-brain.child-state");
      } catch (error) {
        log(`child tool restriction skipped: ${messageOf(error)}`);
      }
    });
  }

  /** Ask the Brain to catch up on this session's captured events (tested fixes learn themselves). */
  function requestScan() {
    if (!enabled.capture) return;
    void service.call(["scan"], { cwd: process.cwd(), timeout: HINT_TIMEOUT_MS }).catch(() => {});
  }

  /** Read the start card for one agent and queue it for the next step. */
  async function injectCard(agent, signal) {
    if (isChild(agent) || hasCard(agent)) return;
    const cwd = await ctx.workingDirectory.ensure(agent, signal);
    const result = await service.call(["card", "--tools"], { cwd, session: sessionOf(agent), signal, timeout: HINT_TIMEOUT_MS });
    if (!result.ok || !result.text) return;
    agent?.inbox?.prepend?.("next-step", notice(result.text, "second-brain", "Second Brain start card"));
  }

  /** The Brain's child card: the parent plan's watch-outs, standing rules, fixes and doc headings. */
  async function injectChildCard(agent, signal) {
    if (!enabled.childCard || hasCard(agent)) return;
    const cwd = await ctx.workingDirectory.ensure(agent, signal);
    const parent = typeof agent?.session?.header?.parentSession === "string" ? agent.session.header.parentSession : "";
    const argv = ["card", "--subagent", "--tools", ...(parent ? ["--parent", parent] : [])];
    const result = await service.call(argv, { cwd, session: sessionOf(agent), signal, timeout: HINT_TIMEOUT_MS });
    if (!result.ok || !result.text) return;
    agent?.inbox?.prepend?.("next-step", notice(result.text, "second-brain", "Second Brain child card"));
  }

  if (enabled.card) {
    ctx.on("agent/created", async ({ agent, source, signal }) => {
      // A resumed session already carries the card it started with.
      if (source === "resume") return;
      try {
        if (isChild(agent)) await injectChildCard(agent, signal);
        else await injectCard(agent, signal);
      } catch (error) {
        log(`start card skipped: ${messageOf(error)}`);
      }
    });

    // Compaction rewrites the surface; when it dropped the card, put it back before the next step.
    ctx.on("session/event", async (session, event) => {
      if (event?.type !== "compaction/end") return;
      try {
        const agent = ctx.agents.get(session.id);
        if (agent) await injectCard(agent, undefined);
        requestScan();
      } catch (error) {
        log(`card after compaction skipped: ${messageOf(error)}`);
      }
    });
  }

  // One counter for the fix outcome: a call from the message that received the fix ran before it was read.
  if (enabled.fix || enabled.capture) {
    ctx.on("session/event", (session, event) => {
      if (event?.type === "assistant/message") steps.set(session.id, (steps.get(session.id) ?? 0) + 1);
    });
  }

  if (enabled.fix || enabled.capture) {
    ctx.on("tools/post-execute", async (exec, result, next) => {
      const decision = await next();
      try {
        if (!exec?.agent || decision?.kind !== "accept") return decision;
        const tool = typeof exec.name === "string" ? exec.name : "";
        if (tool.startsWith("brain_")) return decision;
        const input = exec.arguments && typeof exec.arguments === "object" ? exec.arguments : {};
        if (input.run_in_background === true) return decision;
        const failed = result?.isError === true;
        if (!failed && !enabled.capture) return decision;
        const cwd = await cwdFor(exec);
        const session = sessionOf(exec.agent);
        const content = decision.content ?? result.content;
        const step = steps.get(exec.agent.id) ?? 0;
        const record = (fix) => {
          const stdin = JSON.stringify({
            tool,
            input,
            isError: failed,
            step,
            ...(failed ? { content: textOf(content).slice(0, MAX_ERROR_CHARS) } : {}),
          });
          return service.call(fix ? ["event", "--fix"] : ["event"], {
            cwd,
            session,
            stdin,
            // The answer rides on a failed result, so it follows that call's cancellation; a
            // background capture has no caller left to cancel it.
            ...(fix ? { signal: exec.signal } : {}),
            timeout: failed ? HINT_TIMEOUT_MS : EVENT_TIMEOUT_MS,
          });
        };
        const withFix = (answer) => (
          answer.ok && answer.text
            ? { ...decision, content: [...(content ?? []), { type: "text", text: fixBlock(answer.text) }] }
            : decision
        );
        // A successful result is recorded in the background: capture must never hold the model.
        if (!failed) {
          void record(false).catch(() => {});
          return decision;
        }
        // The fix is model-facing, so it must arrive with the result: one event call answers both.
        if (enabled.fix && enabled.capture && !service.legacy) return withFix(await record(true));
        // Capture off or an older checkout: record nothing, ask the plain fix command.
        if (!enabled.fix) {
          void record(false).catch(() => {});
          return decision;
        }
        const answer = await service.call(["fix", textOf(content).slice(0, MAX_ERROR_CHARS)], { cwd, session, signal: exec.signal, timeout: HINT_TIMEOUT_MS });
        return withFix(answer);
      } catch (error) {
        log(`capture skipped: ${messageOf(error)}`);
        return decision;
      }
    });
  }

  if (enabled.capture) {
    // Durable owner rules: main-session prompts only, never the plugin's own notices or a child's brief.
    ctx.on("session/event", (session, event) => {
      if (event?.type !== "user/message") return;
      const data = event.data ?? {};
      const message = data.message ?? data;
      const source = message?.source?.kind ?? data.source?.kind ?? "";
      if (typeof source === "string" && source.startsWith("second-brain")) return;
      if (message?.role && message.role !== "user") return;
      const text = textOf(message?.content ?? data.content);
      if (!text.trim()) return;
      const agent = ctx.agents.get(session.id);
      if (!agent || isChild(agent)) return;
      void (async () => {
        try {
          const cwd = await ctx.workingDirectory.ensure(agent, undefined);
          await service.call(["prompt"], { cwd, session: session.id, stdin: JSON.stringify({ text }), timeout: EVENT_TIMEOUT_MS });
        } catch (error) {
          log(`rule capture skipped: ${messageOf(error)}`);
        }
      })();
    });

    // Session end or plugin disposal: scan the captured events off any prompt's path.
    ctx.on("agent/disposed", ({ agent }) => {
      if (!agent || isChild(agent)) return;
      steps.delete(agent.id);
      requestScan();
    });
  }

  if (enabled.rollover) {
    // The Harness's own measurement decides; the Brain owns the threshold, latch and wording. One
    // threshold read per session, one call per threshold crossing: a project may configure `rollover`.
    const thresholds = new Map();
    const shownAt = new Map();
    ctx.on("session/event", async (session, event) => {
      if (event?.type !== "assistant/message") return;
      const agent = ctx.agents.get(session.id);
      if (!agent || isChild(agent)) return;
      try {
        let threshold = thresholds.get(session.id);
        if (threshold === undefined) {
          const cwd = await ctx.workingDirectory.ensure(agent, undefined);
          const known = await service.call(["rollover", "--threshold"], { cwd, session: session.id, timeout: HINT_TIMEOUT_MS });
          threshold = known.ok ? Number(known.text) : Number.NaN;
          thresholds.set(session.id, threshold);
        }
        if (!Number.isFinite(threshold) || threshold <= 0) return;
        const measured = ctx.tokenMeter?.measure?.(session);
        const tokens = measured?.surfaceTokens ?? measured?.totalTokens;
        if (typeof tokens !== "number" || !Number.isFinite(tokens)) return;
        const multiple = Math.floor(tokens / threshold);
        if (multiple < 1 || multiple <= (shownAt.get(session.id) ?? 0)) return;
        const cwd = await ctx.workingDirectory.ensure(agent, undefined);
        const answer = await service.call(["rollover", String(tokens)], { cwd, session: session.id, timeout: HINT_TIMEOUT_MS });
        if (!answer.ok || !answer.text) return;
        shownAt.set(session.id, multiple);
        agent.inbox.prepend("next-step", notice(answer.text, "second-brain-rollover", "Second Brain context hand-off"));
      } catch (error) {
        log(`context hand-off skipped: ${messageOf(error)}`);
      }
    });
    ctx.on("agent/disposed", ({ agent }) => {
      if (!agent) return;
      thresholds.delete(agent.id);
      shownAt.delete(agent.id);
    });
  }
}
