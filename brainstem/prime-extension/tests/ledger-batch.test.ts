/**
 * LedgerBatch: the `mirrorFireAndForget` queue must ship mirrored events in ONE
 * Python spawn per host boundary instead of one spawn per event, without ever
 * losing an event, reordering a session's stream, or blocking the host.
 *
 * Everything here drives the REAL mirror with a mocked `node:child_process`, so
 * the assertions are about argv, stdin payloads and spawn counts — the three
 * things the ledger and the measurement harness actually observe.
 */
import { EventEmitter } from "node:events";
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

const execFileMock = vi.hoisted(() => vi.fn());
const execFileSyncMock = vi.hoisted(() => vi.fn());
const spawnMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({
  execFile: execFileMock,
  execFileSync: execFileSyncMock,
  spawn: spawnMock,
}));

import {
  MIRROR_BATCH_MAX_EVENTS,
  MIRROR_FLUSH_DEBOUNCE_MS,
  MIRROR_MAX_SESSION_QUEUES,
  MIRROR_RETRY_DELAY_MS,
  flushMirrorQueue,
  mirrorEvent,
  mirrorFireAndForget,
  pendingMirrorEvents,
  resetMirrorInitCache,
  runLedgerCheckpoint,
  runLedgerSegmentRollover,
} from "../src/ledger-mirror";

const OK_BATCH = '{"appended":[1],"errors":[],"skipped":0}';

interface Spawn {
  args: string[];
  stdin: string;
  /** Spawn options, for the detached path's own contract. */
  options?: Record<string, unknown>;
  /** Detached terminal flush: the handoff file and the bytes it held at spawn. */
  handoff?: { path: string; payload: string };
}

let spawns: Spawn[] = [];
let detachedChildren: Array<EventEmitter & { unref: Mock }> = [];
let respond: (args: string[]) => { error?: Error; stdout?: string } = () => ({
  stdout: OK_BATCH,
});
/** Completion callbacks of async spawns the test deliberately holds open. */
let held: Array<() => void> = [];
let holdNextSpawn = false;

beforeEach(() => {
  spawns = [];
  detachedChildren = [];
  held = [];
  holdNextSpawn = false;
  execFileMock.mockReset();
  execFileSyncMock.mockReset();
  spawnMock.mockReset();
  resetMirrorInitCache();
  respond = () => ({ stdout: OK_BATCH });
  execFileMock.mockImplementation((_python, args, _opts, cb) => {
    const entry = { args: args as string[], stdin: "" };
    spawns.push(entry);
    const outcome = respond(args as string[]);
    const child = {
      stdin: {
        write: (chunk: string) => {
          entry.stdin += chunk;
        },
        end: () => {},
      },
    };
    const done = () => cb(outcome.error ?? null, outcome.stdout ?? "");
    if (holdNextSpawn) {
      holdNextSpawn = false;
      held.push(done); // released explicitly by the test (deterministic ordering)
    } else {
      done();
    }
    return child as never;
  });
  execFileSyncMock.mockImplementation((_python, args, opts) => {
    const options = opts as { input?: string };
    const entry = { args: args as string[], stdin: options.input ?? "" };
    spawns.push(entry);
    const outcome = respond(args as string[]);
    if (outcome.error) throw outcome.error;
    return outcome.stdout ?? "";
  });
  spawnMock.mockImplementation((_python, args, options) => {
    const argv = args as string[];
    const fileIndex = argv.indexOf("--batch-file");
    const path = fileIndex >= 0 ? argv[fileIndex + 1]! : "";
    spawns.push({
      args: argv,
      stdin: "",
      options: options as Record<string, unknown>,
      handoff: path ? { path, payload: readFileSync(path, "utf8") } : undefined,
    });
    const child = Object.assign(new EventEmitter(), { unref: vi.fn() });
    detachedChildren.push(child);
    return child as never;
  });
});

afterEach(() => {
  vi.useRealTimers();
});

async function fakeHome(): Promise<{ home: string; python: string }> {
  const home = await mkdtemp(join(tmpdir(), "sb-batch-"));
  const bin = join(home, ".venv", "Scripts");
  mkdirSync(bin, { recursive: true });
  writeFileSync(join(bin, "python.exe"), "");
  return { home, python: join(bin, "python.exe") };
}

/** Handoff files a detached flush left under <home>/state/tmp. */
function handoffFiles(home: string): string[] {
  try {
    return readdirSync(join(home, "state", "tmp")).sort();
  } catch {
    return [];
  }
}

function payloadLines(spawn: Spawn): Array<Record<string, unknown>> {
  return (spawn.handoff?.payload ?? spawn.stdin)
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

/** The event kinds a typical turn mirrors, in the order index.ts emits them. */
function turnEvents(
  turnIndex: number,
  toolCalls: number,
): Array<{ kind: string; fields: Record<string, unknown> }> {
  const events: Array<{ kind: string; fields: Record<string, unknown> }> = [
    { kind: "user_task", fields: { task_sha256: "abc", prompt_chars: 3 } },
  ];
  for (let i = 0; i < toolCalls; i += 1) {
    events.push({ kind: "tool_requested", fields: { tool: "bash", input_bytes: 4 } });
    events.push({ kind: "tool_completed", fields: { tool: "bash", output_bytes: 8 } });
  }
  events.push({ kind: "turn_end", fields: { turn_index: turnIndex, tool_result_count: toolCalls } });
  return events;
}

describe("LedgerBatch queue: spawn count per turn (before/after)", () => {
  it("mirrors a 3-turn session in 3 spawns instead of 19", async () => {
    const { home, python } = await fakeHome();
    const session = "batch-turns";
    const turns = [turnEvents(0, 2), turnEvents(1, 2), turnEvents(2, 2)];

    // BEFORE (the retained per-event path the old mirrorFireAndForget used):
    // one `ledger init` + one `ledger append` spawn per event (18 events).
    for (const turn of turns.flat()) {
      await mirrorEvent({ home, hostSessionId: session, record: { kind: turn.kind, fields: turn.fields }, python });
    }
    const legacySpawns = spawns.length;
    expect(legacySpawns).toBe(19); // 1 init + 18 events

    resetMirrorInitCache();
    spawns = [];

    // AFTER: one batch spawn per turn boundary (turn_end), init folded in.
    for (const turn of turns) {
      for (const event of turn) {
        void mirrorFireAndForget({
          home,
          hostSessionId: session,
          record: { kind: event.kind, fields: event.fields },
          python,
        });
      }
      await flushMirrorQueue(session);
    }
    expect(spawns.length).toBe(3);
    expect(spawns.every((spawn) => spawn.args.includes("--batch"))).toBe(true);
    expect(spawns.map((spawn) => payloadLines(spawn).length)).toEqual([6, 6, 6]);
    // Only the first flush of the session carries --init (init + append, one process).
    expect(spawns[0].args).toContain("--init");
    expect(spawns[1].args).not.toContain("--init");
    expect(spawns[2].args).not.toContain("--init");
  });

  it("ships one turn as one spawn with the events in mirror order", async () => {
    const { home, python } = await fakeHome();
    const session = "batch-one-turn";
    const events = turnEvents(0, 2);

    // BEFORE: the same 6-event turn through the per-event path (1 init + 1
    // append per event) = 7 spawns.
    for (const event of events) {
      await mirrorEvent({ home, hostSessionId: session, record: { kind: event.kind, fields: event.fields }, python });
    }
    expect(spawns.length).toBe(7);
    resetMirrorInitCache();
    spawns = [];

    for (const event of events) {
      void mirrorFireAndForget({
        home,
        hostSessionId: session,
        record: { kind: event.kind, fields: event.fields },
        python,
      });
    }
    await flushMirrorQueue(session);

    expect(spawns.length).toBe(1); // AFTER: the same turn, one spawn
    expect(spawns[0].args).toEqual([
      "-m", "second_brain", "ledger", "append",
      "--session", session, "--batch", "--init", "--host", "prime",
    ]);
    expect(payloadLines(spawns[0]).map((event) => event.event_type)).toEqual([
      "user_task",
      "tool_requested",
      "tool_completed",
      "tool_requested",
      "tool_completed",
      "turn_end",
    ]);
    // Stateless as before: the ledger assigns seq, the adapter never guesses one.
    for (const event of payloadLines(spawns[0])) expect(event.seq).toBeUndefined();
  });

  it("keeps per-session streams separate and ordered", async () => {
    const { home, python } = await fakeHome();
    const root = "batch-root";
    const child = "batch-child";
    void mirrorFireAndForget({ home, hostSessionId: root, record: { kind: "user_task", fields: {} }, python });
    void mirrorFireAndForget({ home, hostSessionId: child, record: { kind: "user_task", fields: {} }, python });
    void mirrorFireAndForget({ home, hostSessionId: root, record: { kind: "turn_end", fields: {} }, python });
    void mirrorFireAndForget({ home, hostSessionId: child, record: { kind: "turn_end", fields: {} }, python });
    await flushMirrorQueue(root);
    await flushMirrorQueue(child);

    const rootPayload = spawns.filter((spawn) => spawn.args.includes(root)).flatMap(payloadLines);
    const childPayload = spawns.filter((spawn) => spawn.args.includes(child)).flatMap(payloadLines);
    expect(rootPayload.map((event) => event.event_type)).toEqual(["user_task", "turn_end"]);
    expect(childPayload.map((event) => event.event_type)).toEqual(["user_task", "turn_end"]);
  });

  it("no venv -> silent no-op, nothing queued forever", async () => {
    void mirrorFireAndForget({
      home: "H:/no-such-home",
      hostSessionId: "batch-novenv",
      record: { kind: "turn_end", fields: {} },
      python: "H:/no-such-home/.venv/Scripts/python.exe",
    });
    await flushMirrorQueue("batch-novenv");
    expect(spawns.length).toBe(0);
    expect(pendingMirrorEvents("batch-novenv")).toBe(0);
  });
});

describe("LedgerBatch queue bound (eviction)", () => {
  it("never evicts a session queue whose pump is still in flight", async () => {
    const { home, python } = await fakeHome();
    vi.useFakeTimers();
    const busy = "evict-busy";
    const isBusy = (args: string[]): boolean =>
      args.includes("--session") && args[args.indexOf("--session") + 1] === busy;
    respond = (args) =>
      isBusy(args) ? { error: new Error("ledger locked") } : { stdout: OK_BATCH };

    // 1. A batch whose spawn is held open. While the pump awaits it the queue
    //    holds NO events and NO timer — it looks idle to a length/timer test
    //    even though dropping it would orphan the pump.
    holdNextSpawn = true;
    const settled = mirrorFireAndForget({
      home,
      hostSessionId: busy,
      record: { kind: "turn_end", fields: {} },
      python,
    });
    await vi.advanceTimersByTimeAsync(0); // let the immediate flush start
    expect(held.length).toBe(1); // genuinely in flight
    expect(pendingMirrorEvents(busy)).toBe(0); // spliced out: looks idle

    // 2. Fill the map to its cap with genuinely settled queues. `busy` is the
    //    OLDEST entry, so an idle-only predicate evicts exactly it.
    for (let i = 0; i < MIRROR_MAX_SESSION_QUEUES - 1; i += 1) {
      const session = `evict-idle-${i}`;
      void mirrorFireAndForget({
        home,
        hostSessionId: session,
        record: { kind: "turn_end", fields: {} },
        python,
      });
      await flushMirrorQueue(session);
    }

    // 3. One more session reaches the cap: eviction runs with `busy` in flight.
    await mirrorFireAndForget({
      home,
      hostSessionId: "evict-new",
      record: { kind: "turn_end", fields: {} },
      python,
    });

    // 4. The held spawn fails (and so does its one immediate retry): the batch
    //    is requeued. It must land in a queue that is still REACHABLE — the live
    //    map entry, not an object eviction already dropped.
    held.shift()?.();
    await vi.advanceTimersByTimeAsync(MIRROR_RETRY_DELAY_MS + 1);
    expect(held.length).toBe(0);
    expect(pendingMirrorEvents(busy)).toBe(1);

    // 5. The deferred pump still ships it: no event was lost to the eviction.
    respond = () => ({ stdout: OK_BATCH });
    await flushMirrorQueue(busy);
    await settled;
    expect(pendingMirrorEvents(busy)).toBe(0);
    expect(spawns.filter((spawn) => isBusy(spawn.args)).length).toBe(3); // held + retry + deferred
  });
});

describe("LedgerBatch flush triggers", () => {
  it("turn_end / agent_ended / the compaction pair flush immediately; other kinds wait out the debounce", async () => {
    vi.useFakeTimers();
    const { home, python } = await fakeHome();
    for (const kind of ["turn_end", "agent_ended", "compaction_started", "compaction_completed"]) {
      const session = `immediate-${kind}`;
      void mirrorFireAndForget({ home, hostSessionId: session, record: { kind, fields: {} }, python });
      await vi.advanceTimersByTimeAsync(0);
      expect(spawns.length, `${kind} must flush without the debounce`).toBe(1);
      await flushMirrorQueue(session);
      spawns = [];
      resetMirrorInitCache();
    }

    const quiet = "debounced";
    void mirrorFireAndForget({ home, hostSessionId: quiet, record: { kind: "tool_requested", fields: {} }, python });
    await vi.advanceTimersByTimeAsync(MIRROR_FLUSH_DEBOUNCE_MS - 1);
    expect(spawns.length).toBe(0); // still idle-debouncing
    await vi.advanceTimersByTimeAsync(2);
    expect(spawns.length).toBe(1);
    await flushMirrorQueue(quiet);
  });

  it("the debounce restarts on each enqueue (idle, not fixed-interval)", async () => {
    vi.useFakeTimers();
    const { home, python } = await fakeHome();
    const session = "debounce-reset";
    void mirrorFireAndForget({ home, hostSessionId: session, record: { kind: "tool_requested", fields: {} }, python });
    await vi.advanceTimersByTimeAsync(MIRROR_FLUSH_DEBOUNCE_MS - 200);
    void mirrorFireAndForget({ home, hostSessionId: session, record: { kind: "tool_completed", fields: {} }, python });
    await vi.advanceTimersByTimeAsync(400);
    expect(spawns.length).toBe(0);
    await vi.advanceTimersByTimeAsync(MIRROR_FLUSH_DEBOUNCE_MS);
    expect(spawns.length).toBe(1);
    expect(payloadLines(spawns[0]).length).toBe(2);
    await flushMirrorQueue(session);
  });

  it("the queue flushes on reaching MIRROR_BATCH_MAX_EVENTS", async () => {
    const { home, python } = await fakeHome();
    const session = "batch-max";
    for (let i = 0; i < MIRROR_BATCH_MAX_EVENTS - 1; i += 1) {
      void mirrorFireAndForget({ home, hostSessionId: session, record: { kind: "tool_completed", fields: { i } }, python });
    }
    await Promise.resolve();
    expect(spawns.length).toBe(0);
    expect(pendingMirrorEvents(session)).toBe(MIRROR_BATCH_MAX_EVENTS - 1);

    void mirrorFireAndForget({ home, hostSessionId: session, record: { kind: "tool_completed", fields: { i: -1 } }, python });
    await flushMirrorQueue(session);
    expect(spawns.length).toBe(1);
    expect(payloadLines(spawns[0]).length).toBe(MIRROR_BATCH_MAX_EVENTS);
  });
});

describe("LedgerBatch terminal flush (session shutdown)", () => {
  it("session_inactive hands the batch to a DETACHED append: the promise is settled when the handler returns", async () => {
    const { home, python } = await fakeHome();
    const session = "shutdown-detached";
    void mirrorFireAndForget({ home, hostSessionId: session, record: { kind: "tool_completed", fields: {} }, python });
    const settled = mirrorFireAndForget({
      home,
      hostSessionId: session,
      record: { kind: "session_inactive", fields: { reason: "quit" } },
      python,
    });

    // No await: the handoff must already be complete for the process to be
    // allowed to exit right after the final handler returns.
    expect(execFileSyncMock).not.toHaveBeenCalled(); // the blocking spawn is gone
    expect(execFileMock).not.toHaveBeenCalled(); // and the async pump is not used either
    expect(spawnMock).toHaveBeenCalledTimes(1);
    const handoff = spawns[spawns.length - 1];
    expect(handoff.args).toEqual([
      "-m", "second_brain", "ledger", "append",
      "--session", session, "--batch", "--init", "--host", "prime",
      "--batch-file", handoff.handoff?.path,
    ]);
    expect(handoff.options).toEqual(
      expect.objectContaining({
        cwd: home,
        detached: true,
        stdio: "ignore",
        windowsHide: true,
        env: expect.objectContaining({ SECOND_BRAIN_HOME: home }),
      }),
    );
    expect(detachedChildren[0]!.unref).toHaveBeenCalledTimes(1);
    // Without a listener, a later spawn failure would be an uncaught exception.
    expect(detachedChildren[0]!.listenerCount("error")).toBe(1);
    expect(payloadLines(handoff).map((event) => event.event_type)).toEqual([
      "tool_completed",
      "session_inactive",
    ]);
    expect(pendingMirrorEvents(session)).toBe(0);
    await settled;
  });

  it("a shutdown flush that cannot be started is recorded through onError (never throws, nothing pending)", async () => {
    const { home, python } = await fakeHome();
    spawnMock.mockImplementation(() => {
      throw new Error("spawn ENOENT");
    });
    const onError = vi.fn();
    const settled = mirrorFireAndForget({
      home,
      hostSessionId: "shutdown-fail",
      record: { kind: "session_inactive", fields: {} },
      python,
      onError,
    });
    expect(pendingMirrorEvents("shutdown-fail")).toBe(0);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(String(onError.mock.calls[0][0])).toContain("not mirrored");
    expect(String(onError.mock.calls[0][0])).toContain("not started");
    // The batch it could not start stays on disk: it is the only record of what
    // the session was about to write.
    expect(handoffFiles(home)).toHaveLength(1);
    await settled;
  });

  it("a session with no Brain runtime is a silent no-op: no child, no handoff, no error", async () => {
    const { home } = await fakeHome();
    const onError = vi.fn();
    const settled = mirrorFireAndForget({
      home,
      hostSessionId: "shutdown-no-venv",
      record: { kind: "session_inactive", fields: {} },
      python: join(home, "elsewhere", "python.exe"),
      onError,
    });

    expect(spawnMock).not.toHaveBeenCalled();
    expect(handoffFiles(home)).toHaveLength(0);
    expect(onError).not.toHaveBeenCalled();
    expect(pendingMirrorEvents("shutdown-no-venv")).toBe(0);
    await settled;
  });

  it("a shutdown batch carrying a NEW parent re-runs --init with it (detached == async)", async () => {
    const { home, python } = await fakeHome();
    const session = "shutdown-parent";
    // Parentless init, cached by the async path: the session key exists with no
    // parent, so "no requested parent" no longer forces --init.
    await mirrorFireAndForget({
      home,
      hostSessionId: session,
      record: { kind: "turn_end", fields: {} },
      python,
    });
    expect(spawns[0].args).not.toContain("--parent-session");
    spawns = [];

    // A batch-carried parent is the authoritative one: the DETACHED shutdown
    // flush must re-run --init with it, like the async pump does — otherwise the
    // ancestry is never persisted at all (and nothing can cache it afterwards:
    // the host is exiting and there is no result to read).
    const settled = mirrorFireAndForget({
      home,
      hostSessionId: session,
      parentSessionId: "root-sync",
      record: { kind: "session_inactive", fields: { reason: "quit" } },
      python,
    });
    const detachedSpawn = spawns[spawns.length - 1];
    expect(detachedSpawn.args).toContain("--init");
    expect(detachedSpawn.args[detachedSpawn.args.indexOf("--parent-session") + 1]).toBe("root-sync");
    await settled;

    // Known-initialized: a later terminal batch WITHOUT a parent must not re-init.
    spawns = [];
    const later = mirrorFireAndForget({
      home,
      hostSessionId: session,
      record: { kind: "session_inactive", fields: { reason: "quit" } },
      python,
    });
    expect(spawns[spawns.length - 1].args).not.toContain("--init");
    await later;

    // One file per handoff: a restarted host may flush again while an earlier
    // child is still reading its own batch.
    expect(handoffFiles(home)).toHaveLength(2);
  });
});

describe("LedgerBatch compaction barriers", () => {
  it("the pre-compaction checkpoint flushes queued events BEFORE `ledger segment checkpoint`", async () => {
    const { home, python } = await fakeHome();
    const session = "compact-barrier";
    respond = (args) => (args.includes("checkpoint") ? { stdout: '{"ok":true,"integrity":{}}' } : { stdout: OK_BATCH });
    holdNextSpawn = true;

    void mirrorFireAndForget({
      home,
      hostSessionId: session,
      record: { kind: "compaction_started", fields: { branch_entries: 0 } },
      python,
    });
    void mirrorFireAndForget({ home, hostSessionId: session, record: { kind: "tool_completed", fields: {} }, python });
    const checkpoint = runLedgerCheckpoint({ home, hostSessionId: session, python });
    await Promise.resolve();

    // The checkpoint must NOT have been spawned while the batch is in flight.
    expect(spawns.filter((spawn) => spawn.args.includes("checkpoint")).length).toBe(0);
    const batchSpawn = spawns.find((spawn) => spawn.args.includes("--batch"));
    expect(batchSpawn).toBeDefined();
    expect(payloadLines(batchSpawn!).map((event) => event.event_type)).toEqual([
      "compaction_started",
      "tool_completed",
    ]);

    held.shift()?.();
    const result = await checkpoint;

    expect(result.ok).toBe(true);
    const batchIndex = spawns.findIndex((spawn) => spawn.args.includes("--batch"));
    const checkpointIndex = spawns.findIndex((spawn) => spawn.args.includes("checkpoint"));
    expect(checkpointIndex).toBeGreaterThan(batchIndex);
    expect(spawns.filter((spawn) => spawn.args.includes("--batch")).length).toBe(1);
  });

  it("the segment rollover flushes queued events first (compaction_completed stays in its segment)", async () => {
    const { home, python } = await fakeHome();
    const session = "rollover-barrier";
    respond = (args) =>
      args.includes("segment") ? { stdout: '{"opened":"seg-2","reason":"compact"}' } : { stdout: OK_BATCH };
    holdNextSpawn = true;

    void mirrorFireAndForget({
      home,
      hostSessionId: session,
      record: { kind: "compaction_completed", fields: { from_extension: false } },
      python,
    });
    runLedgerSegmentRollover({ home, hostSessionId: session, python });
    await Promise.resolve();
    expect(spawns.filter((spawn) => spawn.args.includes("segment")).length).toBe(0);

    held.shift()?.();
    // Awaiting the queue also awaits the rollover's own continuation (attached
    // to the same chain): no real timer is involved.
    await flushMirrorQueue(session);

    const batchIndex = spawns.findIndex((spawn) => spawn.args.includes("--batch"));
    const rolloverIndex = spawns.findIndex((spawn) => spawn.args.includes("segment"));
    expect(batchIndex).toBeGreaterThanOrEqual(0);
    expect(rolloverIndex).toBeGreaterThan(batchIndex);
    expect(payloadLines(spawns[batchIndex]).map((event) => event.event_type)).toEqual([
      "compaction_completed",
    ]);
  });
});

describe("LedgerBatch failure handling", () => {
  it("retries ONCE with a byte-identical payload, then succeeds silently", async () => {
    const { home, python } = await fakeHome();
    let attempts = 0;
    respond = () => {
      attempts += 1;
      return attempts === 1 ? { error: new Error("ledger init race") } : { stdout: OK_BATCH };
    };
    const onError = vi.fn();
    await mirrorFireAndForget({
      home,
      hostSessionId: "batch-retry",
      record: { kind: "turn_end", fields: {} },
      python,
      onError,
    });
    expect(spawns.length).toBe(2);
    expect(spawns[0].stdin).toBe(spawns[1].stdin);
    expect(onError).not.toHaveBeenCalled();
    expect(pendingMirrorEvents("batch-retry")).toBe(0);
  });

  it("requeues the batch once after the retry fails, and drops it with an error record after that", async () => {
    vi.useFakeTimers();
    const { home, python } = await fakeHome();
    respond = () => ({ error: new Error("ledger locked") });
    const onError = vi.fn();
    const settled = mirrorFireAndForget({
      home,
      hostSessionId: "batch-fail",
      record: { kind: "turn_end", fields: {} },
      python,
      onError,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(spawns.length).toBe(1); // initial attempt
    await vi.advanceTimersByTimeAsync(MIRROR_RETRY_DELAY_MS + 1);
    expect(spawns.length).toBe(2); // immediate retry
    expect(pendingMirrorEvents("batch-fail")).toBe(1); // evidence kept, not dropped

    await vi.advanceTimersByTimeAsync(MIRROR_FLUSH_DEBOUNCE_MS + MIRROR_RETRY_DELAY_MS + 1);
    expect(spawns.length).toBe(4); // deferred pump: initial + retry again
    expect(pendingMirrorEvents("batch-fail")).toBe(0); // bounded: dropped after that
    expect(onError).toHaveBeenCalledTimes(1);
    expect(String(onError.mock.calls[0][0])).toContain("not mirrored");
    await settled;
  });

  it("reports per-event rejections with their event ids", async () => {
    const { home, python } = await fakeHome();
    respond = () => ({
      stdout: JSON.stringify({
        appended: [1],
        errors: [{ line: 2, event_id: "mirror-tool_requested-1", error: "invalid parent_event_id: 'x'" }],
        skipped: 0,
      }),
    });
    const onError = vi.fn();
    await mirrorFireAndForget({
      home,
      hostSessionId: "batch-reject",
      record: { kind: "turn_end", fields: {}, eventId: "mirror-tool_requested-1" },
      python,
      onError,
    });
    expect(onError).toHaveBeenCalledTimes(1);
    expect(String(onError.mock.calls[0][0])).toContain("1 of 1 events rejected");
    expect(String(onError.mock.calls[0][0])).toContain("invalid parent_event_id");
  });

  it("a duplicate of the SAME event after a persisted-but-failed attempt is delivery success", async () => {
    const { home, python } = await fakeHome();
    let attempts = 0;
    respond = () => {
      attempts += 1;
      if (attempts === 1) return { error: new Error("Command failed (transient)") };
      return {
        stdout: JSON.stringify({
          appended: [],
          errors: [{ line: 1, event_id: "e-dup", error: "duplicate event_id: 'e-dup'" }],
          skipped: 0,
        }),
      };
    };
    const onError = vi.fn();
    await mirrorFireAndForget({
      home,
      hostSessionId: "batch-dup",
      record: { kind: "turn_end", fields: {}, eventId: "e-dup" },
      python,
      onError,
    });
    expect(spawns.length).toBe(2);
    expect(onError).not.toHaveBeenCalled();
  });

  it("a new parent re-runs --init, later omissions do not", async () => {
    const { home, python } = await fakeHome();
    const session = "batch-parent";
    await mirrorFireAndForget({ home, hostSessionId: session, record: { kind: "turn_end", fields: {} }, python });
    await mirrorFireAndForget({
      home,
      hostSessionId: session,
      parentSessionId: "root-a",
      record: { kind: "turn_end", fields: {} },
      python,
    });
    await mirrorFireAndForget({ home, hostSessionId: session, record: { kind: "turn_end", fields: {} }, python });
    expect(spawns[0].args).not.toContain("--parent-session");
    expect(spawns[1].args).toContain("--parent-session");
    expect(spawns[1].args).toContain("root-a");
    expect(spawns[2].args).not.toContain("--init");
  });

  it("forwards the batch's cwd to --init (project attribution) and never fabricates one", async () => {
    const { home, python } = await fakeHome();
    await mirrorFireAndForget({
      home,
      hostSessionId: "batch-cwd",
      cwd: "C:/proj/x",
      record: { kind: "turn_end", fields: {} },
      python,
    });
    expect(spawns[0].args.slice(-2)).toEqual(["--cwd", "C:/proj/x"]);

    resetMirrorInitCache();
    spawns = [];
    await mirrorFireAndForget({
      home,
      hostSessionId: "batch-nocwd",
      record: { kind: "turn_end", fields: {} },
      python,
    });
    expect(spawns[0].args).not.toContain("--cwd");
  });

  it("the spawn environment stays clean (no PYTHONHOME/PYTHONPATH, home pinned)", async () => {
    const { home, python } = await fakeHome();
    process.env.PYTHONHOME = "H:/poison";
    process.env.PYTHONPATH = "H:/poison-path";
    try {
      await mirrorFireAndForget({
        home,
        hostSessionId: "batch-env",
        record: { kind: "turn_end", fields: {} },
        python,
      });
      const opts = execFileMock.mock.calls[0]?.[2] as {
        env: Record<string, string | undefined>;
        cwd: string;
        timeout: number;
      };
      expect(opts.env.PYTHONHOME).toBeUndefined();
      expect(opts.env.PYTHONPATH).toBeUndefined();
      expect(opts.env.SECOND_BRAIN_HOME).toBe(home);
      expect(opts.cwd).toBe(home);
      expect(opts.timeout).toBe(5000);
    } finally {
      delete process.env.PYTHONHOME;
      delete process.env.PYTHONPATH;
    }
  });
});
