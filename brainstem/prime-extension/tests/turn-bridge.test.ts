/**
 * E01 turn bridge client tests: the reused-interpreter helper protocol, the
 * bounded one-shot spawn, and every fail-open path. The helper Python process
 * is replaced by a scripted child (the `spawnImpl` seam), so these tests need
 * no interpreter and no wall-clock waiting.
 */
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import type { ChildProcess } from "node:child_process";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getTurnHelper,
  loadTurnBridgeConfig,
  peekTurnHelper,
  prepareTurnWithBridge,
  resetTurnHelpers,
  resolveTurnPython,
  runTurnPrepareOnce,
  stopTurnHelpers,
  TurnHelper,
  TURN_DEFAULT_QUEUE_LIMIT,
  TURN_DEFAULT_TIMEOUT_MS,
  type TurnBridgePayload,
  type TurnBridgeRequest,
  type TurnBridgeSpawner,
} from "../src/turn-bridge";

interface WireRequest {
  id?: number;
  op?: string;
}

type Responder = (request: WireRequest, child: FakeChild) => void;

class FakeChild extends EventEmitter {
  readonly stdin = new PassThrough();
  readonly stdout = new PassThrough();
  readonly stderr = new PassThrough();
  readonly requests: WireRequest[] = [];
  killed = false;
  /** Emitted once after spawn; `undefined` means "never becomes ready". */
  readyLine: unknown = { ok: true, op: "ready", identity: { home: "H" } };

  constructor(private readonly responder: Responder) {
    super();
    this.stdin.setEncoding("utf8");
    this.stdin.on("data", (chunk: string) => {
      for (const raw of chunk.split("\n")) {
        const line = raw.trim();
        if (line.length === 0) continue;
        const request = JSON.parse(line) as WireRequest;
        this.requests.push(request);
        if (request.op === "shutdown") continue;
        this.responder(request, this);
      }
    });
  }

  emitLine(value: unknown): void {
    this.stdout.write(`${JSON.stringify(value)}\n`);
  }

  kill(): boolean {
    this.killed = true;
    this.stdout.end();
    this.emit("exit", null, null);
    return true;
  }

  unref(): void {
    // the fake child holds nothing open
  }
}

/** Spawn the scripted children in order; each emits its ready line post-spawn. */
function scriptedSpawner(children: FakeChild[]): TurnBridgeSpawner {
  const spawner = (): ChildProcess => {
    const child = children.shift();
    if (child === undefined) throw new Error("no scripted child left");
    setImmediate(() => {
      if (child.readyLine !== undefined) child.emitLine(child.readyLine);
    });
    return child as unknown as ChildProcess;
  };
  return spawner as unknown as TurnBridgeSpawner;
}

/** Answer each prepare_turn request from the scripted payload list. */
function answering(answers: (unknown | null)[]): Responder {
  return (request, child) => {
    const next = answers.length > 0 ? answers.shift() : payload();
    if (next === null) {
      child.kill();
      return;
    }
    child.emitLine({ ok: true, op: "prepare_turn", id: request.id, result: next ?? payload() });
  };
}

function payload(overrides: Partial<TurnBridgePayload> = {}): TurnBridgePayload {
  return {
    ok: true,
    session_id: "S",
    capsule: { session_id: "S", changed: true, capsule_sha256: "a", capsule_bytes: 1 },
    active_state: { ok: true, session_id: "S", rendered_text: "[SECOND_BRAIN_HOT_CONTEXT]" },
    autoinject: { decision: "INJECT" },
    autoinject_stdout: '{"decision":"INJECT","packet":"P"}\n',
    capsule_stdout: '{"session_id":"S","changed":true}\n',
    render_stdout: '{"session_id":"S","rendered_text":"[SECOND_BRAIN_HOT_CONTEXT]"}\n',
    ...overrides,
  };
}

const request: TurnBridgeRequest = {
  session: "S",
  task: "A task",
  budgetTokens: 256,
  want: ["capsule", "render", "autoinject"],
};

function helperFor(
  children: FakeChild[],
  overrides: Partial<{ queueLimit: number; timeoutMs: number }> = {},
): TurnHelper {
  return new TurnHelper({
    home: "H",
    python: "python.exe",
    timeoutMs: overrides.timeoutMs ?? TURN_DEFAULT_TIMEOUT_MS,
    maxRequests: 8,
    lifetimeMs: 60_000,
    queueLimit: overrides.queueLimit ?? TURN_DEFAULT_QUEUE_LIMIT,
    spawnImpl: scriptedSpawner(children),
  });
}

afterEach(() => {
  resetTurnHelpers();
  vi.useRealTimers();
});

describe("turn bridge config", () => {
  it("defaults to the one-shot batched spawn with the documented bounds", () => {
    const cfg = loadTurnBridgeConfig({});
    expect(cfg.mode).toBe("once");
    expect(cfg.helperStart).toBe("lazy");
    expect(cfg.timeoutMs).toBe(TURN_DEFAULT_TIMEOUT_MS);
    expect(cfg.queueLimit).toBe(TURN_DEFAULT_QUEUE_LIMIT);
  });

  it("honours mode/start/bounds env overrides and rejects garbage", () => {
    expect(loadTurnBridgeConfig({ SECOND_BRAIN_TURN_MODE: "current" }).mode).toBe("current");
    expect(loadTurnBridgeConfig({ SECOND_BRAIN_TURN_MODE: "helper" }).mode).toBe("helper");
    expect(loadTurnBridgeConfig({ SECOND_BRAIN_TURN_MODE: "once" }).mode).toBe("once");
    // Unset/garbage never degrades to the pre-E01 path.
    expect(loadTurnBridgeConfig({ SECOND_BRAIN_TURN_MODE: "nonsense" }).mode).toBe("once");
    expect(loadTurnBridgeConfig({ SECOND_BRAIN_TURN_HELPER_START: "session_start" }).helperStart)
      .toBe("session_start");
    expect(loadTurnBridgeConfig({ SECOND_BRAIN_TURN_QUEUE_LIMIT: "0" }).queueLimit)
      .toBe(TURN_DEFAULT_QUEUE_LIMIT);
    expect(loadTurnBridgeConfig({ SECOND_BRAIN_TURN_TIMEOUT_MS: "2500" }).timeoutMs).toBe(2500);
  });

  it("resolves the interpreter from env, then requires it to exist", () => {
    expect(resolveTurnPython("H", { SECOND_BRAIN_PYTHON: "definitely-missing-python" }))
      .toBeUndefined();
    expect(resolveTurnPython(__dirname, {})).toBeUndefined();
  });
});

describe("TurnHelper protocol", () => {
  it("handshakes once, reuses the interpreter, and routes replies by request id", async () => {
    const child = new FakeChild(answering([payload(), payload({ session_id: "S2" })]));
    const helper = helperFor([child]);
    expect(await helper.ensureStarted()).toBe(true);
    expect(helper.readyIdentity).toEqual({ home: "H" });

    const first = await helper.request({ op: "prepare_turn", session_id: "S" });
    const second = await helper.request({ op: "prepare_turn", session_id: "S" });
    expect((first?.result as TurnBridgePayload).session_id).toBe("S");
    expect((second?.result as TurnBridgePayload).session_id).toBe("S2");
    expect(helper.stats().starts).toBe(1);
    expect(child.requests.filter((r) => r.op === "prepare_turn").length).toBe(2);
  });

  it("assigns a fresh wire id per round trip (a caller id must not strand the reply)", async () => {
    // Regression: the batched request carried its own `id` field, so every
    // round trip after the first waited for a reply whose id could never match.
    const child = new FakeChild(answering([payload(), payload({ session_id: "S2" })]));
    const helper = helperFor([child]);
    const first = await helper.request({ op: "prepare_turn", session_id: "S", id: 1 });
    const second = await helper.request({ op: "prepare_turn", session_id: "S", id: 1 });
    expect((first?.result as TurnBridgePayload).session_id).toBe("S");
    expect((second?.result as TurnBridgePayload).session_id).toBe("S2");
    const ids = child.requests.map((request) => request.id);
    expect(ids).toEqual([1, 2]);
  });

  it("restarts once on identity_changed and answers from the fresh helper", async () => {
    const stale = new FakeChild((request, child) => {
      child.emitLine({ ok: false, op: "prepare_turn", id: request.id, error: "identity_changed" });
    });
    const fresh = new FakeChild(answering([payload()]));
    const helper = helperFor([stale, fresh]);
    const response = await helper.request({ op: "prepare_turn", session_id: "S" });
    expect((response?.result as TurnBridgePayload).session_id).toBe("S");
    expect(stale.killed).toBe(true);
    expect(helper.stats().starts).toBe(2);
  });

  it("fails open (null) on a request timeout and starts a fresh helper afterwards", async () => {
    vi.useFakeTimers();
    const silent = new FakeChild(answering([payload()]));
    silent.readyLine = undefined;
    const recovering = new FakeChild(answering([payload()]));
    const helper = helperFor([silent, recovering], { timeoutMs: 50 });
    const timedOut = helper.request({ op: "prepare_turn", session_id: "S" });
    await vi.advanceTimersByTimeAsync(60);
    expect(await timedOut).toBeNull();
    expect(silent.killed).toBe(true);
    vi.useRealTimers();
    const response = await helper.request({ op: "prepare_turn", session_id: "S" });
    expect(response).not.toBeNull();
    expect(helper.stats().starts).toBe(2);
  });

  it("returns null on a dead helper instead of throwing", async () => {
    const dyingResponder: Responder = (_, child) => child.kill();
    const helper = helperFor([new FakeChild(dyingResponder), new FakeChild(dyingResponder)]);
    expect(await helper.request({ op: "prepare_turn", session_id: "S" })).toBeNull();
  });

  it("bounds the queue: an over-limit concurrent request resolves null, the first still answers", async () => {
    const child = new FakeChild(answering([payload()]));
    const helper = helperFor([child], { queueLimit: 1 });
    const first = helper.request({ op: "prepare_turn", session_id: "S" });
    const second = helper.request({ op: "prepare_turn", session_id: "S" });
    expect(await second).toBeNull();
    expect(helper.stats().last_failure).toBe("queue_full");
    expect(await first).not.toBeNull();
  });

  it("dispose writes a shutdown line and kills the child after the grace period", async () => {
    const child = new FakeChild(answering([payload()]));
    const helper = helperFor([child]);
    await helper.ensureStarted();
    vi.useFakeTimers();
    helper.dispose("session_shutdown");
    expect(child.requests.some((r) => r.op === "shutdown")).toBe(true);
    expect(child.killed).toBe(false);
    await vi.advanceTimersByTimeAsync(300);
    expect(child.killed).toBe(true);
  });

  it("keeps one helper per (home, interpreter) and clears it on stop", () => {
    const child = new FakeChild(answering([payload()]));
    const spawner = scriptedSpawner([child]);
    const cfg = loadTurnBridgeConfig({});
    const a = getTurnHelper({ home: "H1", python: "p", cfg, spawnImpl: spawner });
    const b = getTurnHelper({ home: "H1", python: "p", cfg, spawnImpl: spawner });
    expect(a).toBe(b);
    expect(peekTurnHelper("H1", "p")).toBe(a);
    stopTurnHelpers("test");
    expect(peekTurnHelper("H1", "p")).toBeUndefined();
  });
});

describe("turn bridge designs", () => {
  it("once: parses the payload and fails open on error exit / malformed / spawn failure", async () => {
    const ok = await runTurnPrepareOnce({
      home: "H",
      python: "p",
      request,
      timeoutMs: 1000,
      spawnImpl: onceSpawner({ stdout: `${JSON.stringify(payload())}\n`, code: 0 }),
    });
    expect(ok?.autoinject_stdout).toBe(payload().autoinject_stdout);

    const failed = await runTurnPrepareOnce({
      home: "H",
      python: "p",
      request,
      timeoutMs: 1000,
      spawnImpl: onceSpawner({ stdout: "", code: 2 }),
    });
    expect(failed).toBeNull();

    const malformed = await runTurnPrepareOnce({
      home: "H",
      python: "p",
      request,
      timeoutMs: 1000,
      spawnImpl: onceSpawner({ stdout: "not json", code: 0 }),
    });
    expect(malformed).toBeNull();

    const unspawnable = await runTurnPrepareOnce({
      home: "H",
      python: "p",
      request,
      timeoutMs: 1000,
      spawnImpl: (() => {
        throw new Error("ENOENT");
      }) as unknown as TurnBridgeSpawner,
    });
    expect(unspawnable).toBeNull();
  });

  it("forwards the reduced phase set and keeps a partial (exit 1) batch", async () => {
    // Regression: without --phases the one-shot child reruns the AutoInject
    // decision on an emit-cache hit and can commit unseen deliveries; without
    // parsing exit 1 a partial batch is discarded and its packet lost.
    const argv: string[][] = [];
    const spawnImpl = ((_command: string, args: string[]) => {
      argv.push(args);
      const child = new EventEmitter() as EventEmitter & { stdout: PassThrough; kill: () => boolean };
      child.stdout = new PassThrough();
      child.kill = () => true;
      setImmediate(() => {
        child.stdout.write(`${JSON.stringify(payload({ ok: false }))}\n`);
        child.stdout.end();
        child.emit("exit", 1, null);
      });
      return child as unknown as ChildProcess;
    }) as unknown as TurnBridgeSpawner;

    const partial = await runTurnPrepareOnce({
      home: "H",
      python: "p",
      request: { ...request, want: ["capsule", "render"] },
      timeoutMs: 1000,
      spawnImpl,
    });
    expect(partial?.ok).toBe(false); // still consumed, not discarded
    expect(argv[0]).toContain("--phases");
    expect(argv[0][argv[0].indexOf("--phases") + 1]).toBe("capsule,render");

    const allPhases = await runTurnPrepareOnce({
      home: "H",
      python: "p",
      request: { ...request, want: undefined },
      timeoutMs: 1000,
      spawnImpl,
    });
    expect(allPhases).not.toBeNull();
    expect(argv[1]).not.toContain("--phases");
  });

  it("disposal is terminal: an in-flight retry never spawns a replacement", async () => {
    vi.useFakeTimers();
    const silent = new FakeChild(() => undefined); // ready, but never answers
    const spare = new FakeChild(answering([payload()]));
    let spawns = 0;
    const spawner = (() => {
      spawns += 1;
      const next = spawns === 1 ? silent : spare;
      setImmediate(() => {
        if (next.readyLine !== undefined) next.emitLine(next.readyLine);
      });
      return next as unknown as ChildProcess;
    }) as unknown as TurnBridgeSpawner;
    const helper = new TurnHelper({
      home: "H",
      python: "p",
      timeoutMs: 50,
      maxRequests: 8,
      lifetimeMs: 60_000,
      queueLimit: 2,
      spawnImpl: spawner,
    });

    const pending = helper.request({ op: "prepare_turn", session_id: "S" });
    await vi.advanceTimersByTimeAsync(0); // spawn + handshake, request in flight
    expect(spawns).toBe(1);

    helper.dispose("session_shutdown");
    expect(await pending).toBeNull();
    expect(spawns).toBe(1); // the retry loop must not revive the disposed helper
    expect(helper.stats().state).toBe("dead");
    expect(await helper.request({ op: "prepare_turn", session_id: "S" })).toBeNull();
    expect(spawns).toBe(1);
    vi.useRealTimers();
  });

  it("helper mode falls back to one bounded spawn when the helper never becomes ready", async () => {
    // A helper that never answers the handshake (wrong interpreter, hung
    // start). The 50 ms per-call timeout keeps this deterministic; the
    // fallback spawn must still deliver the payload.
    const unusable = new FakeChild(answering([payload()]));
    unusable.readyLine = undefined;
    const result = await prepareTurnWithBridge({
      cfg: loadTurnBridgeConfig({
        SECOND_BRAIN_TURN_MODE: "helper",
        SECOND_BRAIN_TURN_TIMEOUT_MS: "50",
      }),
      home: "H",
      python: "p",
      request,
      spawnImpl: helperThenOnceSpawner(unusable),
    });
    expect(result?.session_id).toBe("S");
    expect(unusable.killed).toBe(true);
  });

  it("current mode prepares nothing (the caller keeps the per-phase path)", async () => {
    const result = await prepareTurnWithBridge({
      cfg: loadTurnBridgeConfig({ SECOND_BRAIN_TURN_MODE: "current" }),
      home: "H",
      python: "p",
      request,
    });
    expect(result).toBeNull();
  });
});

/** One-shot spawner: emits scripted stdout, then exits with `code`. */
function onceSpawner(script: { stdout: string; code: number }): TurnBridgeSpawner {
  return (() => {
    const child = new EventEmitter() as EventEmitter & {
      stdout: PassThrough;
      kill: () => boolean;
    };
    child.stdout = new PassThrough();
    child.kill = () => true;
    setImmediate(() => {
      child.stdout.write(script.stdout);
      child.stdout.end();
      child.emit("exit", script.code, null);
    });
    return child as unknown as ChildProcess;
  }) as unknown as TurnBridgeSpawner;
}

/** Spawn 1 is the (unusable) helper, every later spawn is the one-shot call. */
function helperThenOnceSpawner(child: FakeChild): TurnBridgeSpawner {
  let calls = 0;
  const fallback = onceSpawner({ stdout: `${JSON.stringify(payload())}\n`, code: 0 });
  return ((...args: Parameters<TurnBridgeSpawner>) => {
    calls += 1;
    if (calls === 1) return child as unknown as ChildProcess;
    return fallback(...args);
  }) as unknown as TurnBridgeSpawner;
}
