/**
 * Behavioural tests for the Second Brain Host plugin.
 *
 * The plugin normally runs a real `brain serve` child. These tests inject the
 * two process primitives (`spawn`, `execFile`), so the real service code — the
 * NDJSON protocol, the pending-call map, the legacy fallback — runs in-process
 * against a fake Brain: no Harness process and no child process needed.
 *
 *   node --test dsh/test/plugin.test.mjs
 */
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough, Writable } from "node:stream";
import { after, afterEach, before, describe, it } from "node:test";
import { setTimeout as sleep } from "node:timers/promises";
import { apply } from "../index.js";

/** How the fake Brain answers one command, in the service and the CLI alike. */
function answer(argv) {
  const command = argv[0];
  if (command === "card") return argv.includes("--subagent")
    ? "Brain child · demo\nKnown here:\n- [decision] a child fact (n-child)"
    : "Brain · demo — what prior sessions learned\nKnown here:\n- [decision] a fact (n-test)";
  if (command === "recall") return "a remembered answer (n-test)";
  if (command === "note") return "saved n-new";
  if (command === "state") return "state saved";
  if (command === "fix") return "restart the shell before retrying [n-fix]";
  if (command === "event") return argv.includes("--fix") ? "Brain: restart the shell before retrying [n-fix]" : "";
  if (command === "rollover") {
    if (argv.includes("--threshold")) return "150000";
    return Number(argv[1]) > 150000
      ? "Brain: context 150k. Save brain_state (Goal/Next/See:) and start a fresh session; the card carries it over."
      : "";
  }
  return "";
}

/** Every process start, request and CLI call, in order. */
let requests = [];
function reset() {
  requests = [];
}

/** One fake `brain serve` child: stdin requests in, NDJSON replies out. */
class FakeService extends EventEmitter {
  constructor({ legacy }) {
    super();
    this.stdout = new PassThrough();
    this.stderrListeners = [];
    this.stderr = { on: (_event, handler) => this.stderrListeners.push(handler) };
    this.stdin = new Writable({
      write: (chunk, _encoding, done) => {
        for (const line of chunk.toString("utf8").split("\n").filter(Boolean)) {
          const request = JSON.parse(line);
          requests.push({
            event: "request",
            argv: request.argv,
            session: request.session ?? null,
            stdin: request.stdin ? JSON.parse(request.stdin) : null,
          });
          if (!legacy) {
            this.stdout.write(JSON.stringify({ id: request.id, code: 0, out: answer(request.argv), err: "" }) + "\n");
          }
        }
        done();
      },
    });
    this.stdin.on("error", () => {});
    if (legacy) {
      // An older checkout never starts: it fails `serve` on stderr and exits.
      process.nextTick(() => {
        for (const handler of this.stderrListeners) handler(Buffer.from("brain: unknown command serve (brain help)\n"));
        this.emit("close", 1, null);
      });
    }
  }

  kill() {
    this.emit("close", 0, null);
  }
}

/** A fake `execFile`: one CLI call, answered through the callback. */
function fakeExecFile() {
  return (_executable, args, _options, callback) => {
    const child = new EventEmitter();
    let input = "";
    child.stdin = new Writable({
      write: (chunk, _encoding, done) => { input += chunk.toString("utf8"); done(); },
    });
    child.stdin.on("error", () => {});
    child.stdin.on("finish", () => {
      requests.push({ event: "cli", argv: args.slice(1), stdin: input || null });
      callback(null, `${answer(args.slice(1))}\n`, "");
    });
    return child;
  };
}

let home;
before(() => {
  home = mkdtempSync(join(tmpdir(), "dsh-second-brain-test-"));
  mkdirSync(join(home, "brain", "bin"), { recursive: true });
  writeFileSync(join(home, "brain", "bin", "brain.mjs"), "// the fake process primitives never run this\n");
});
after(() => rmSync(home, { recursive: true, force: true }));
afterEach(async () => {
  for (const dispose of disposers.splice(0)) dispose();
  await sleep(10);
});

/** A minimal Cordis-like context that records what the plugin contributes. */
function makeContext({ agents = new Map(), tokens } = {}) {
  const listeners = new Map();
  const tools = new Map();
  const warnings = [];
  const ctx = {
    logger: { warn: (...args) => warnings.push(args.join(" ")) },
    tools: { register: (definition) => { tools.set(definition.name, definition); return () => {}; } },
    workingDirectory: { ensure: async () => process.cwd() },
    agents: { get: (id) => agents.get(id) },
    tokenMeter: { measure: () => ({ surfaceTokens: typeof tokens === "function" ? tokens() : tokens }) },
    effect: (install) => {
      const dispose = install();
      if (typeof dispose === "function") disposers.push(dispose);
      return dispose;
    },
    on: (event, listener) => {
      const list = listeners.get(event) ?? [];
      list.push(listener);
      listeners.set(event, list);
      return () => {};
    },
  };
  return { ctx, listeners, tools, warnings };
}

/** Run every listener of an event in registration order and return the last result. */
async function call(listeners, event, ...args) {
  let last;
  for (const listener of listeners.get(event) ?? []) last = await listener(...args);
  return last;
}

/** A minimal Agent: identity, durable header, empty surface, inbox and restriction spies. */
function makeAgent({ id = "session-1", parent, carded = false } = {}) {
  const injected = [];
  const restrictions = [];
  const agent = {
    id,
    inbox: { prepend: (queue, message) => injected.push({ queue, message }) },
    ctx: {
      effect: (install) => install(),
      tools: { restrict: (filter) => { restrictions.push(filter); return () => {}; } },
    },
    session: {
      header: parent ? { id, parentSession: parent } : { id },
      surface: { nodes: carded ? [0] : [] },
      eventAt: (seq) => (carded && seq === 0
        ? { type: "user/message", data: { source: { kind: "second-brain" } } }
        : undefined),
    },
  };
  return { agent, injected, restrictions };
}

/** A tool execution input as the registry hands it to `execute`. */
function execution(agent, extra = {}) {
  return { agent, signal: new AbortController().signal, name: "tool", arguments: {}, ...extra };
}

const disposers = [];

function startPlugin(overrides = {}, options = {}) {
  reset();
  const { ctx, listeners, tools, warnings } = makeContext(options);
  const legacy = options.legacy === true;
  const deps = {
    spawn: () => {
      requests.push({ event: "start", argv: ["serve"] });
      return new FakeService({ legacy });
    },
    execFile: fakeExecFile(),
  };
  apply(ctx, { home: options.home ?? home, node: "node", ...overrides }, deps);
  return { listeners, tools, warnings };
}

const rows = () => requests;

/** Poll for a fire-and-forget request (a successful capture has no awaited promise). */
async function waitForRequest(command, timeoutMs = 3_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const found = rows().find((row) => row.event === "request" && row.argv[0] === command);
    if (found) return found;
    await sleep(10);
  }
  return undefined;
}

describe("start card", () => {
  it("injects one framed context message into a fresh session, through the warm service", async () => {
    const { listeners } = startPlugin();
    const { agent, injected } = makeAgent();
    await call(listeners, "agent/created", { agent, source: "startup", signal: new AbortController().signal });

    assert.equal(injected.length, 1);
    assert.equal(injected[0].queue, "next-step");
    const { message } = injected[0];
    assert.equal(message.role, "user");
    assert.equal(message.source.kind, "second-brain");
    assert.equal(message.source.form, "notice");
    assert.match(message.content[0].text, /^<second-brain>\nBrain · demo/);
    assert.match(message.content[0].text, /\(n-test\)/);
    assert.equal(typeof message.id, "string");
    // The resident-tools card, not the CLI preview.
    assert.deepEqual(rows().filter((row) => row.event === "request").map((row) => row.argv), [["card", "--tools"]]);
  });

  it("does nothing for a resumed session", async () => {
    const { listeners } = startPlugin();
    const { agent, injected } = makeAgent();
    await call(listeners, "agent/created", { agent, source: "resume", signal: new AbortController().signal });
    assert.equal(injected.length, 0);
  });

  it("gives a child agent the child card with its parent's edits", async () => {
    const { listeners } = startPlugin();
    const { agent, injected } = makeAgent({ parent: "parent-1" });
    await call(listeners, "agent/created", { agent, source: "startup", signal: new AbortController().signal });
    assert.equal(injected.length, 1);
    assert.match(injected[0].message.content[0].text, /Brain child/);
    const argv = rows().filter((row) => row.event === "request").map((row) => row.argv)[0];
    assert.deepEqual(argv, ["card", "--subagent", "--tools", "--parent", "parent-1"]);
  });

  it("does not duplicate a card already in the session", async () => {
    const { listeners } = startPlugin();
    const { agent, injected } = makeAgent({ carded: true });
    await call(listeners, "agent/created", { agent, source: "startup", signal: new AbortController().signal });
    assert.equal(injected.length, 0);
  });

  it("puts the card back when a compaction dropped it", async () => {
    const agents = new Map();
    const { listeners } = startPlugin({}, { agents });
    const live = makeAgent();
    agents.set("session-1", live.agent);
    await call(listeners, "session/event", { id: "session-1" }, { type: "compaction/end" });
    assert.equal(live.injected.length, 1);
    assert.match(live.injected[0].message.content[0].text, /Brain · demo/);
  });

  it("keeps the card a compaction left in place", async () => {
    const agents = new Map();
    const { listeners } = startPlugin({}, { agents });
    const live = makeAgent({ carded: true });
    agents.set("session-1", live.agent);
    await call(listeners, "session/event", { id: "session-1" }, { type: "compaction/end" });
    assert.equal(live.injected.length, 0);
  });

  it("ignores every other session event", async () => {
    const agents = new Map();
    const { listeners } = startPlugin({}, { agents });
    const live = makeAgent();
    agents.set("session-1", live.agent);
    await call(listeners, "session/event", { id: "session-1" }, { type: "turn/end" });
    assert.equal(live.injected.length, 0);
  });

  it("stays inert when disabled or when the checkout is missing", () => {
    const disabled = makeContext();
    apply(disabled.ctx, { home, node: "node", card: false, tools: false, capture: false, rollover: false, fix: false });
    assert.equal(disabled.listeners.size, 0);

    const missing = makeContext();
    apply(missing.ctx, { home: join(home, "absent"), node: "node" });
    assert.match(missing.warnings.join("\n"), /no Brain checkout/);
  });
});

describe("tools", () => {
  it("registers the three Brain tools", () => {
    const { tools } = startPlugin({ card: false });
    assert.deepEqual([...tools.keys()].sort(), ["brain_note", "brain_recall", "brain_state"]);
  });

  it("runs two calls through one warm service process", async () => {
    const { tools } = startPlugin({ card: false });
    const recall = tools.get("brain_recall");
    const { agent } = makeAgent();
    assert.deepEqual(await recall.execute({ query: "what changed" }, execution(agent)), { text: "a remembered answer (n-test)" });
    assert.deepEqual(await recall.execute({ query: "again" }, execution(agent)), { text: "a remembered answer (n-test)" });
    assert.equal(rows().filter((row) => row.event === "start").length, 1);
    assert.deepEqual(rows().filter((row) => row.event === "request").map((row) => row.argv), [["recall", "what changed"], ["recall", "again"]]);
    assert.equal(recall.parameters.required[0], "query");
    assert.equal(recall.parameters.additionalProperties, false);
  });

  it("saves a note with its scope flags and working state", async () => {
    const { tools } = startPlugin({ card: false });
    const { agent } = makeAgent();
    const value = await tools.get("brain_note").execute(
      { text: "a durable thing", kind: "gotcha", tested: true, global: true },
      execution(agent),
    );
    assert.deepEqual(value, { text: "saved n-new" });
    assert.deepEqual(rows().find((row) => row.event === "request").argv.slice(0, 2), ["note", "a durable thing"]);
    assert.deepEqual(
      await tools.get("brain_state").execute({ text: "Goal: do it" }, execution(agent)),
      { text: "state saved" },
    );
  });

  it("refuses to save working state from a child agent", async () => {
    const { tools } = startPlugin({ card: false });
    const state = tools.get("brain_state");
    const { agent } = makeAgent({ parent: "parent-1" });
    const value = await state.execute({ text: "Goal: do it" }, execution(agent));
    assert.match(value.text, /belongs to the parent session/);
  });

  it("hides brain_state from a child agent and keeps it for a main agent", async () => {
    const { listeners } = startPlugin();
    const child = makeAgent({ parent: "parent-1" });
    await call(listeners, "agent/created", { agent: child.agent, source: "startup" });
    assert.deepEqual(child.restrictions, [{ deny: ["brain_state"] }]);

    const main = makeAgent();
    await call(listeners, "agent/created", { agent: main.agent, source: "startup" });
    assert.deepEqual(main.restrictions, []);
  });

  it("surfaces a Brain failure as a tool error", async () => {
    const { tools } = startPlugin({ card: false });
    const recall = tools.get("brain_recall");
    const { agent } = makeAgent();
    await assert.rejects(recall.execute({ query: "   " }, execution(agent)), /query is required/);
  });

  it("omits every tool when disabled", () => {
    const { tools } = startPlugin({ tools: false });
    assert.equal(tools.size, 0);
  });
});

describe("known fix and learning", () => {
  it("records a failed result and appends its tested fix", async () => {
    const { listeners } = startPlugin({ card: false });
    const { agent } = makeAgent();
    const result = { isError: true, content: [{ type: "text", text: "Error: shell exploded" }] };
    const decision = await call(
      listeners,
      "tools/post-execute",
      execution(agent, { name: "pwsh", arguments: { command: "npm test" } }),
      result,
      async () => ({ kind: "accept" }),
    );
    assert.equal(decision.kind, "accept");
    assert.equal(decision.content.length, 2);
    assert.match(decision.content[1].text, /\nBrain: restart the shell before retrying \[n-fix\]/);
    const request = rows().find((row) => row.event === "request");
    assert.deepEqual(request.argv, ["event", "--fix"]);
    assert.deepEqual(request.stdin, { tool: "pwsh", input: { command: "npm test" }, isError: true, step: 0, content: "Error: shell exploded" });
  });

  it("records a successful result without changing it", async () => {
    const { listeners } = startPlugin({ card: false });
    const { agent } = makeAgent();
    const accepted = { kind: "accept" };
    const decision = await call(
      listeners,
      "tools/post-execute",
      execution(agent, { name: "pwsh", arguments: { command: "npm test" } }),
      { isError: false, content: [{ type: "text", text: "ok" }] },
      async () => accepted,
    );
    assert.equal(decision, accepted);
    const request = await waitForRequest("event");
    assert.ok(request, "the successful call was not recorded");
    assert.deepEqual(request.argv, ["event"]);
    assert.deepEqual(request.stdin, { tool: "pwsh", input: { command: "npm test" }, isError: false, step: 0 });
  });

  it("counts assistant messages so a same-batch sibling does not decide a fix", async () => {
    const { listeners } = startPlugin({ card: false });
    const { agent } = makeAgent();
    const run = (isError) => call(
      listeners,
      "tools/post-execute",
      execution(agent, { name: "pwsh", arguments: { command: "npm test" } }),
      { isError, content: [{ type: "text", text: isError ? "Error: boom" : "ok" }] },
      async () => ({ kind: "accept" }),
    );
    await call(listeners, "session/event", { id: "session-1" }, { type: "assistant/message" });
    await run(true);
    await run(false);
    await call(listeners, "session/event", { id: "session-1" }, { type: "assistant/message" });
    await run(false);
    const started = Date.now();
    while (Date.now() - started < 3_000 && rows().filter((row) => row.event === "request").length < 3) await sleep(10);
    assert.deepEqual(rows().filter((row) => row.event === "request").map((row) => row.stdin.step), [1, 1, 2]);
  });

  it("skips its own tools, background launches, blocked decisions and disabled capture", async () => {
    const { listeners } = startPlugin({ card: false });
    const { agent } = makeAgent();
    const accept = async () => ({ kind: "accept" });
    await call(listeners, "tools/post-execute", execution(agent, { name: "brain_recall" }), { isError: true, content: [] }, accept);
    await call(listeners, "tools/post-execute", execution(agent, { name: "pwsh", arguments: { run_in_background: true } }), { isError: true, content: [] }, accept);
    await call(listeners, "tools/post-execute", execution(agent, { name: "pwsh" }), { isError: true, content: [] }, async () => ({ kind: "block" }));
    assert.equal(rows().filter((row) => row.event === "request").length, 0);

    const quiet = startPlugin({ card: false, capture: false, fix: false });
    await call(quiet.listeners, "tools/post-execute", execution(agent, { name: "pwsh" }), { isError: true, content: [] }, accept);
    assert.equal(rows().filter((row) => row.event === "request").length, 0);
  });

  it("captures a main-session prompt as a rule candidate and ignores its own notices", async () => {
    const agents = new Map();
    const { listeners } = startPlugin({ card: false }, { agents });
    const { agent } = makeAgent();
    agents.set("session-1", agent);
    const prompt = (source, text) => call(listeners, "session/event", { id: "session-1" }, {
      type: "user/message",
      data: { role: "user", source: { kind: source }, content: [{ type: "text", text }] },
    });
    await prompt("second-brain", "Brain · demo card");
    await prompt("user", "always use pnpm for this repo");
    const started = Date.now();
    while (Date.now() - started < 3_000 && !rows().some((row) => row.event === "request" && row.argv[0] === "prompt")) await sleep(10);
    const prompts = rows().filter((row) => row.event === "request" && row.argv[0] === "prompt");
    assert.equal(prompts.length, 1);
    assert.deepEqual(prompts[0].stdin, { text: "always use pnpm for this repo" });
  });
});

describe("context hand-off", () => {
  it("lands the Brain's rollover hint before the next step at 150k", async () => {
    const agents = new Map();
    const { listeners } = startPlugin({ card: false }, { agents, tokens: 160000 });
    const { agent, injected } = makeAgent();
    agents.set("session-1", agent);
    await call(listeners, "session/event", { id: "session-1" }, { type: "assistant/message" });
    assert.equal(injected.length, 1);
    assert.equal(injected[0].message.source.kind, "second-brain-rollover");
    assert.match(injected[0].message.content[0].text, /context 150k/);
    assert.deepEqual(
      rows().filter((row) => row.event === "request").map((row) => row.argv),
      [["rollover", "--threshold"], ["rollover", "160000"]],
    );
  });

  it("asks once per crossing, not once per step", async () => {
    const agents = new Map();
    let tokens = 160000;
    const { listeners } = startPlugin({ card: false }, { agents, tokens: () => tokens });
    const { agent, injected } = makeAgent();
    agents.set("session-1", agent);
    const step = () => call(listeners, "session/event", { id: "session-1" }, { type: "assistant/message" });
    await step();
    tokens = 200000;
    await step();
    assert.equal(injected.length, 1);
    tokens = 301000;
    await step();
    assert.equal(injected.length, 2);
    assert.equal(rows().filter((row) => row.event === "request" && row.argv[0] === "rollover" && row.argv[1] !== "--threshold").length, 2);
  });

  it("stays silent below the threshold, in children, and when disabled", async () => {
    const agents = new Map();
    const { listeners } = startPlugin({ card: false }, { agents, tokens: 100000 });
    const { agent, injected } = makeAgent();
    agents.set("session-1", agent);
    await call(listeners, "session/event", { id: "session-1" }, { type: "assistant/message" });
    assert.equal(injected.length, 0);
    // The threshold is read once; no hint call is made below it.
    assert.deepEqual(rows().filter((row) => row.event === "request").map((row) => row.argv), [["rollover", "--threshold"]]);

    const childAgents = new Map();
    const child = startPlugin({ card: false }, { agents: childAgents, tokens: 160000 });
    const kid = makeAgent({ parent: "parent-1" });
    childAgents.set("session-1", kid.agent);
    await call(child.listeners, "session/event", { id: "session-1" }, { type: "assistant/message" });
    assert.equal(kid.injected.length, 0);
    assert.equal(rows().filter((row) => row.event === "request").length, 0);

    const off = startPlugin({ card: false, rollover: false }, { tokens: 160000 });
    await call(off.listeners, "session/event", { id: "session-1" }, { type: "assistant/message" });
    assert.equal(rows().filter((row) => row.event === "request").length, 0);
  });
});

describe("older checkout", () => {
  it("falls back to one process per call and keeps the older feature set", async () => {
    const { tools, listeners } = startPlugin({}, { legacy: true });
    const { agent, injected } = makeAgent();
    await call(listeners, "agent/created", { agent, source: "startup", signal: new AbortController().signal });
    assert.match(injected[0].message.content[0].text, /Brain · demo/);

    const value = await tools.get("brain_recall").execute({ query: "old" }, execution(agent));
    assert.deepEqual(value, { text: "a remembered answer (n-test)" });

    const decision = await call(
      listeners,
      "tools/post-execute",
      execution(agent, { name: "pwsh" }),
      { isError: true, content: [{ type: "text", text: "Error: shell exploded" }] },
      async () => ({ kind: "accept" }),
    );
    assert.match(decision.content[1].text, /\nBrain: restart the shell before retrying/);
    // One failed serve attempt for the whole plugin lifetime, then plain CLI calls.
    assert.equal(rows().filter((row) => row.event === "start").length, 1);
    assert.ok(rows().some((row) => row.event === "cli" && row.argv[0] === "recall"));
    assert.ok(rows().some((row) => row.event === "cli" && row.argv[0] === "fix"));
  });
});
