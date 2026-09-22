/**
 * Ledger-mirror acceptance for worker completions.
 *
 * The prohibition is narrow: **a refused completion must not be recorded as an accepted completion**.
 * A refusal diagnostic is legitimate, and an empty ledger proves nothing — so this file asserts on
 * two independent pieces of evidence rather than on the absence of everything:
 *
 *  1. **path evidence** — whether the completion handler dispatched a `worker_completed` mirror at
 *     all. `mirrorFireAndForget` is fire-and-forget with an internal retry and returns no handle, so
 *     a destination poll cannot tell "not scheduled yet" from "never scheduled". The observation
 *     point is the real exported function, wrapped: the wrapper records the dispatch **and delegates
 *     to the real implementation**, so the same call also produces the destination record.
 *  2. **destination evidence** — the disposable session ledger, read on a fresh connection each time
 *     (a long-lived read transaction keeps its snapshot and can miss later commits).
 *
 * A third case is the **destination/query positive control**: it invokes the real `mirrorEvent`
 * through `vi.importActual` (bypassing this file's mock), because a same-module direct call is not
 * observable through a module mock. It proves the ledger path and the query work — it is not the
 * regression test, which must exercise the refused-completion path itself.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/** These cases spawn a real interpreter and wait on a real subprocess: the default 5s does not fit. */
const itSlow = (name: string, run: () => Promise<void>) => it(name, run, 60_000);

const observed = vi.hoisted(() => ({ dispatches: [] as Array<Record<string, unknown>> }));

vi.mock("../src/ledger-mirror", async (importOriginal) => {
  const actual = await importOriginal<typeof ledgerMirror>();
  return {
    ...actual,
    mirrorFireAndForget: (options: Record<string, unknown>) => {
      observed.dispatches.push(options);
      return actual.mirrorFireAndForget(options as never);
    },
  };
});

import type * as ledgerMirror from "../src/ledger-mirror";
import factory, { type ExtensionOptions } from "../src/index";
import { runOmpWorkerResult, type OmpWorkerResultOptions } from "../src/worker-result-bridge";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

const CANDIDATE_ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const PYTHON = process.env.SECOND_BRAIN_PYTHON ?? join(CANDIDATE_ROOT, ".venv", "Scripts", "python.exe");
const FIXTURE = fileURLToPath(new URL("../../../tests/fixtures/omp_replay_state.py", import.meta.url));
const SESSION = "omp-session";
const TIMESTAMP = "2026-01-01T00:00:00.000Z";
const LEDGER_QUERY = [
  "import sys",
  "import json, sqlite3, sys",
  "path, needle = sys.argv[1], sys.argv[2]",
  "conn = sqlite3.connect(path)",
  "rows = conn.execute(",
  "    \"SELECT payload_json FROM events WHERE payload_json LIKE '%worker_completed%'\"",
  "    \" AND payload_json LIKE ?\", ('%' + needle + '%',),",
  ").fetchall()",
  "conn.close()",
  "print(len(rows))",
].join("\n");

let BASE = "";
const savedHome = process.env.SECOND_BRAIN_HOME;
const savedPython = process.env.SECOND_BRAIN_PYTHON;

interface Fixture {
  home: string;
  repo: string;
  task_id: string;
  attempt_id: string;
  packet_sha256: string;
  project_id: string;
  worktree_id: string | null;
  agent_id: string;
  host_generation: number;
  native_attempt_id: string;
  native_job_id: string;
  callback_token: string | null;
}

function childEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue;
    if (key === "PYTHONHOME" || key === "PYTHONPATH" || key.startsWith("SECOND_BRAIN_")) continue;
    env[key] = value;
  }
  return env;
}

function setup(base: string, taskId: string): Fixture {
  const out = execFileSync(PYTHON, [FIXTURE, "setup", "--base", base, "--task-id", taskId,
    "--intent", "mutating", "--host-session", SESSION], { env: childEnv(), encoding: "utf8" });
  const parsed = JSON.parse(out) as Fixture & { ok: boolean };
  expect(parsed.ok).toBe(true);
  return parsed;
}

/** The session ledger the mirror writes into, by the host session's internal id. */
function ledgerPath(home: string): string {
  const internal = execFileSync(PYTHON, ["-c",
    "import sys; from second_brain import ledger; print(ledger.internal_session_id(sys.argv[1]))",
    SESSION], { env: childEnv(), encoding: "utf8" }).trim();
  return join(home, "state", "sessions", internal, "ledger.sqlite");
}

/** Count matching mirror records on a fresh connection — no cached read snapshot. */
function mirroredCompletions(ledger: string, taskId: string): number {
  // A missing ledger is a fixture failure, not evidence of absence: say so instead of reporting 0.
  if (!existsSync(ledger)) throw new Error(`ledger not found at ${ledger}`);
  const out = execFileSync(PYTHON, ["-c", LEDGER_QUERY, ledger, taskId],
    { env: childEnv(), encoding: "utf8" });
  return Number(out.trim());
}

function context(state: Fixture, entries: unknown[]): ExtensionContext {
  return {
    cwd: state.repo,
    model: { provider: "original-provider", id: "original-model" },
    sessionManager: {
      getSessionFile: () => `${state.home}/${SESSION}.jsonl`,
      getSessionId: () => "native-omp-session",
      getHeader: () => ({ type: "session", version: 1, id: "native-omp-session", timestamp: TIMESTAMP }),
      getEntries: () => entries,
    },
    getContextUsage: () => undefined,
    getSystemPrompt: () => "base",
    signal: undefined,
    hasUI: false,
    ui: undefined,
  } as unknown as ExtensionContext;
}

function admissionEntry(state: Fixture) {
  return { type: "custom", customType: "second-brain.worker-admission-pending", timestamp: TIMESTAMP,
    data: { session: SESSION, taskId: state.task_id, attemptId: state.attempt_id,
      packetSha256: state.packet_sha256, projectId: state.project_id, worktreeId: state.worktree_id,
      accessIntent: "mutating", parentSessionId: SESSION, agent: "worker",
      toolCallId: "call-mirror", sourceIndex: 0 } };
}

function jobEntry(state: Fixture) {
  return { type: "custom", customType: "second-brain.worker-job-pending", timestamp: TIMESTAMP,
    data: { session: SESSION, jobId: state.native_job_id, accessIntent: "mutating",
      toolCallId: "call-mirror", sourceIndex: 0, taskId: state.task_id, attemptId: state.attempt_id,
      packetSha256: state.packet_sha256, parentSessionId: SESSION, agent: "worker",
      agentId: state.agent_id, hostGeneration: state.host_generation,
      nativeAttemptId: state.native_attempt_id, projectId: state.project_id,
      worktreeId: state.worktree_id } };
}

function resultEntry(state: Fixture) {
  return { type: "custom", customType: "second-brain.worker-result-pending", timestamp: TIMESTAMP,
    data: { session: SESSION, attemptId: state.attempt_id, summary: "mirror case",
      fields: { task_id: state.task_id, packet_sha256: state.packet_sha256, status: "completed",
        worker_agent: "worker", child_omp_agent_id: state.agent_id,
        child_omp_session_file: null, worker_model: null } } };
}

const IDENTITY_ENTRY = { type: "custom", customType: "brain.active-state",
  details: { session_id: SESSION }, timestamp: TIMESTAMP };

/** Drive the real registered hook; `token` represents host transport (absent on replay). */
async function runHook(state: Fixture, token: string | undefined) {
  const handlers = new Map<string, (event: unknown, ctx: ExtensionContext) => unknown>();
  const outcomes: Array<Record<string, unknown>> = [];
  const pi = {
    on: (name: string, handler: (event: unknown, ctx: ExtensionContext) => unknown) =>
      handlers.set(name, handler),
    emit: () => {},
    appendEntry: () => {},
  } as unknown as ExtensionAPI;
  const options: ExtensionOptions = {
    ompWorkerResultRunner: (workerOptions: OmpWorkerResultOptions) =>
      runOmpWorkerResult({ ...workerOptions, callbackToken: token }).then((outcome) => {
        outcomes.push(outcome as unknown as Record<string, unknown>);
        return outcome;
      }),
    ompWorkerDispatchFailedRunner: () => Promise.resolve({ ok: true, status: "accepted" }),
  };
  factory(pi, options);
  const handler = handlers.get("before_agent_start");
  expect(handler, "before_agent_start was registered").toBeDefined();
  await handler!({ type: "before_agent_start", prompt: "mirror" },
    context(state, [IDENTITY_ENTRY, admissionEntry(state), jobEntry(state), resultEntry(state)]));
  return outcomes;
}

function completionDispatches(taskId: string) {
  return observed.dispatches.filter((entry) => {
    const record = entry.record as Record<string, unknown> | undefined;
    if (!record || record.kind !== "worker_completed") return false;
    return JSON.stringify(record.fields ?? {}).includes(taskId);
  });
}

beforeAll(() => { BASE = mkdtempSync(join(tmpdir(), "sb-mirror-")); });

beforeEach(() => {
  vi.stubEnv("SECOND_BRAIN_HOME", BASE);
  vi.stubEnv("SECOND_BRAIN_OBSERVABILITY", "on");
  vi.stubEnv("SECOND_BRAIN_RTD", "off");
  vi.stubEnv("SECOND_BRAIN_REREAD_AVOIDANCE", "OFF");
  vi.stubEnv("SECOND_BRAIN_RECALL", "off");
  vi.stubEnv("SECOND_BRAIN_PYTHON", PYTHON);
  vi.stubEnv("ORCHESTRATOR_MODELS", "");
  observed.dispatches.length = 0;
});

afterEach(() => {
  vi.unstubAllEnvs();
  if (savedHome === undefined) delete process.env.SECOND_BRAIN_HOME;
  else process.env.SECOND_BRAIN_HOME = savedHome;
  if (savedPython === undefined) delete process.env.SECOND_BRAIN_PYTHON;
  else process.env.SECOND_BRAIN_PYTHON = savedPython;
});

afterAll(() => {
  try { rmSync(BASE, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); }
  catch (error) { console.warn(`[mirror test] temp tree left behind: ${BASE}: ${String(error)}`); }
});

describe("worker completion mirror", () => {
  itSlow("mirrors an accepted completion and records it in the session ledger", async () => {
    const taskId = "mirror-accepted";
    const state = setup(`${BASE}/${taskId}`, taskId);
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const ledger = ledgerPath(state.home);

    const outcomes = await runHook(state, state.callback_token ?? undefined);
    expect(outcomes[0]?.ok, "the completion is accepted with its credential").toBe(true);

    // Path evidence: the observation point must see the real dispatch for THIS attempt, or the
    // negative case below would be measuring a point that never observes anything.
    const dispatched = completionDispatches(taskId);
    expect(dispatched.length, "one completion mirror dispatched for this attempt").toBe(1);

    // Destination evidence: the real mirror wrote a matching record into the disposable ledger.
    const deadline = Date.now() + 10_000;
    let records = 0;
    while (Date.now() < deadline && records === 0) {
      records = mirroredCompletions(ledger, taskId);
      if (records === 0) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    expect(records, `expected one mirrored completion in ${ledger}`).toBe(1);
  });

  itSlow("does not dispatch or record a completion mirror for a refused completion", async () => {
    const taskId = "mirror-refused";
    const state = setup(`${BASE}/${taskId}`, taskId);
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const ledger = ledgerPath(state.home);

    const outcomes = await runHook(state, undefined);
    expect(outcomes[0]?.ok, "the replay is refused without its credential").toBe(false);

    // Path evidence is the primary here: the refusal throws before the mirror call, so nothing is
    // scheduled. The destination check below is a secondary observation, not the proof.
    expect(completionDispatches(taskId), "no completion mirror dispatched for a refused attempt")
      .toHaveLength(0);
    expect(mirroredCompletions(ledger, taskId)).toBe(0);
  });

  itSlow("destination control: the real mirrorEvent reaches the ledger and the query finds it", async () => {
    // Bypasses this file's mock on purpose: this proves the destination and the query detect a
    // completion mirror produced by the real writer, which is the evidence the two cases above
    // depend on when they report "no record".
    const taskId = "mirror-destination-control";
    const state = setup(`${BASE}/${taskId}`, taskId);
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const ledger = ledgerPath(state.home);
    const real = await vi.importActual<typeof ledgerMirror>("../src/ledger-mirror");

    const result = await real.mirrorEvent({
      home: state.home,
      hostSessionId: SESSION,
      record: { kind: "worker_completed", fields: { task_id: taskId, status: "completed" } },
    } as never);
    expect(result.ok, `the real mirror write must succeed: ${String(result.error)}`).toBe(true);

    const deadline = Date.now() + 10_000;
    let records = 0;
    while (Date.now() < deadline && records === 0) {
      records = mirroredCompletions(ledger, taskId);
      if (records === 0) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    expect(records, "the query detects the deliberately produced record").toBe(1);
  });
});
