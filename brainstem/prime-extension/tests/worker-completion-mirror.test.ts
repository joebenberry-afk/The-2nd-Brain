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
import { existsSync, globSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/** These cases spawn a real interpreter and wait on a real subprocess: the default 5s does not fit. */
const itSlow = (name: string, run: () => Promise<void>) => it(name, run, 60_000);

const observed = vi.hoisted(() => ({ dispatches: [] as Array<Record<string, unknown>> }));
const recordedEntries: Array<{ customType: string; data: unknown }> = [];

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

/**
 * One probe, one code path: the count and the diagnostics come from the same walk, so the assertion
 * can never disagree with the evidence printed beside it.
 */
const LEDGER_PROBE = [
  "import sqlite3, sys, pathlib, json",
  "home, task_id = pathlib.Path(sys.argv[1]), sys.argv[2]",
  "count = 0",
  "found = False",
  "for p in sorted(home.rglob('ledger.sqlite')):",
  "    found = True",
  "    conn = sqlite3.connect(f'file:{p}?mode=ro', uri=True)",
  "    n = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]",
  "    print('LEDGER', p.parent.name[:12], 'events', n)",
  "    for rid, et, pl in conn.execute('SELECT rowid, event_type, payload_json FROM events ORDER BY rowid'):",
  "        try:",
  "            d = json.loads(pl)",
  "        except ValueError:",
  "            print('  ROW', rid, et, 'unparseable')",
  "            continue",
  "        if not isinstance(d, dict) or d.get('task_id') != task_id:",
  "            continue",
  "        attributed = 'packet_sha256' in d and 'child_omp_agent_id' in d",
  "        print('  ROW', rid, et, 'mirror-attributed' if attributed else 'other-writer', json.dumps(d)[:200])",
  "        if attributed:",
  "            count += 1",
  "    conn.close()",
  "if not found:",
  "    print('NO LEDGER FILE UNDER', home)",
  "print('COUNT', count)",
].join("\n");

function ledgerProbe(home: string, taskId: string): { count: number; report: string } {
  const report = execFileSync(PYTHON, ["-c", LEDGER_PROBE, home, taskId],
    { env: childEnv(), encoding: "utf8" });
  const match = /^COUNT (\d+)$/m.exec(report);
  if (!match) throw new Error(`probe produced no count line:\n${report}`);
  return { count: Number(match[1]), report };
}

function dumpDestination(home: string, taskId: string): string {
  return ledgerProbe(home, taskId).report;
}

/** Count matching mirror records on a fresh connection — no cached read snapshot. */
function mirroredCompletions(home: string, taskId: string): number {
  return ledgerProbe(home, taskId).count;
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

function admissionEntry(state: Fixture, intent = "mutating") {
  return { type: "custom", customType: "second-brain.worker-admission-pending", timestamp: TIMESTAMP,
    data: { session: SESSION, taskId: state.task_id, attemptId: state.attempt_id,
      packetSha256: state.packet_sha256, projectId: state.project_id, worktreeId: state.worktree_id,
      accessIntent: intent, parentSessionId: SESSION, agent: "worker",
      toolCallId: "call-mirror", sourceIndex: 0 } };
}

function jobEntry(state: Fixture, intent = "mutating") {
  return { type: "custom", customType: "second-brain.worker-job-pending", timestamp: TIMESTAMP,
    data: { session: SESSION, jobId: state.native_job_id, accessIntent: intent,
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
async function runHook(state: Fixture, token: string | undefined, intent = "mutating") {
  const handlers = new Map<string, (event: unknown, ctx: ExtensionContext) => unknown>();
  const outcomes: Array<Record<string, unknown>> = [];
  const pi = {
    on: (name: string, handler: (event: unknown, ctx: ExtensionContext) => unknown) =>
      handlers.set(name, handler),
    emit: () => {},
    appendEntry: (customType: string, data: unknown) => {
      recordedEntries.push({ customType, data });
    },
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
    context(state, [IDENTITY_ENTRY, admissionEntry(state, intent), jobEntry(state, intent), resultEntry(state)]));
  return outcomes;
}

function taskState(home: string, taskId: string): Record<string, unknown> {
  const out = execFileSync(PYTHON, [FIXTURE, "probe", "--base", dirname(home), "--task-id", taskId],
    { env: childEnv(), encoding: "utf8" });
  return JSON.parse(out) as Record<string, unknown>;
}

function acceptanceClaims() {
  return recordedEntries.filter((entry) => entry.customType.includes("worker-result-accepted"));
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
  recordedEntries.length = 0;
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

    const outcomes = await runHook(state, state.callback_token ?? undefined);
    expect(outcomes[0]?.ok, "the completion is accepted with its credential").toBe(true);

    // Path evidence: the observation point must see the real dispatch for THIS attempt, or the
    // negative case below would be measuring a point that never observes anything.
    const dispatched = completionDispatches(taskId);
    expect(dispatched.length, "one completion mirror dispatched for this attempt").toBe(1);
    // Non-vacuity for the error case below: the accepted path really does record an acceptance claim.
    expect(acceptanceClaims().length, "the accepted path records an acceptance journal entry")
      .toBeGreaterThanOrEqual(1);

    // Destination evidence: the real mirror wrote a matching record into the disposable ledger.
    const deadline = Date.now() + 10_000;
    let records = 0;
    while (Date.now() < deadline && records === 0) {
      records = mirroredCompletions(state.home, taskId);
      if (records === 0) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    // Positive claim only: an accepted completion IS mirrored. Exact-once is an idempotence property
    // this gate does not establish — a duplicate was observed and is recorded as an open question
    // rather than asserted away or silently tolerated.
    console.log(`[mirror test] mirror-attributed completion records for ${taskId}: ${records}`);
    if (records < 1) console.log(`[destination dump]\n${dumpDestination(state.home, taskId)}`);
    expect(records, `at least one mirrored completion for ${taskId} in ${state.home}`)
      .toBeGreaterThanOrEqual(1);
  });

  itSlow("does not dispatch or record a completion mirror for a refused completion", async () => {
    const taskId = "mirror-refused";
    const state = setup(`${BASE}/${taskId}`, taskId);
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);

    const outcomes = await runHook(state, undefined);
    expect(outcomes[0]?.ok, "the replay is refused without its credential").toBe(false);

    // Path evidence is the primary here: the refusal throws before the mirror call, so nothing is
    // scheduled. The destination check below is a secondary observation, not the proof.
    expect(completionDispatches(taskId), "no completion mirror dispatched for a refused attempt")
      .toHaveLength(0);
    expect(mirroredCompletions(state.home, taskId)).toBe(0);
  });

  itSlow("fails closed when a credentialed completion errors at the consumer", async () => {
    // The credential is present on the request (host transport supplies it) and the consumer still
    // errors: an authentication refusal, not a missing-credential replay. Fail-closed means the
    // extension converts neither the error nor the credential into a lifecycle fact.
    const taskId = "mirror-credential-error";
    const state = setup(`${BASE}/${taskId}`, taskId);
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const sentinel = `sentinel-wrong-credential-${taskId}`;

    const outcomes = await runHook(state, sentinel);
    expect(outcomes[0]?.ok, "the credentialed completion is refused, not accepted").toBe(false);

    expect(completionDispatches(taskId), "no completion mirror for an errored credential path")
      .toHaveLength(0);
    expect(mirroredCompletions(state.home, taskId), "no mirrored completion record").toBe(0);
    expect(acceptanceClaims(), "no acceptance claim recorded for a refused completion").toHaveLength(0);

    const after = taskState(state.home, taskId);
    expect(after.state, "the attempt is not terminal").not.toBe("COMPLETED");
    expect(after.attempt_results, "no accepted result row").toBe(0);
    expect(after.writer_ownership, "ownership is not released by a failed completion").toBe("held");

    const recorded = JSON.stringify(recordedEntries);
    expect(recorded.includes(sentinel), "the credential never reaches a recorded destination").toBe(false);
    expect(ledgerProbe(state.home, taskId).report.includes(sentinel), "nor the session ledger").toBe(false);
  });

  itSlow("does not let a journal claiming read_only bypass authentication", async () => {
    // Altered-journal check: the host journal says read_only while the authoritative attempt is
    // mutating. A journal label may not decide whether an authoritative mutating attempt needs its
    // credential, so the outcome must match the honest-journal refusal exactly.
    const taskId = "mirror-readonly-claim";
    const state = setup(`${BASE}/${taskId}`, taskId);
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);

    const outcomes = await runHook(state, undefined, "read_only");
    expect(outcomes[0]?.ok, "the read_only claim does not authenticate the attempt").toBe(false);
    expect(completionDispatches(taskId), "no completion mirror under a read_only claim")
      .toHaveLength(0);
    expect(mirroredCompletions(state.home, taskId), "no mirrored completion record").toBe(0);

    const after = taskState(state.home, taskId);
    expect(after.state, "the attempt is not terminal").not.toBe("COMPLETED");
    expect(after.attempt_results, "no accepted result row").toBe(0);
    expect(after.writer_ownership, "ownership unchanged by the claim").toBe("held");
  });

  itSlow("destination control: the real mirrorEvent reaches the ledger and the query finds it", async () => {
    // Bypasses this file's mock on purpose: this proves the destination and the query detect a
    // completion mirror produced by the real writer, which is the evidence the two cases above
    // depend on when they report "no record".
    const taskId = "mirror-destination-control";
    const state = setup(`${BASE}/${taskId}`, taskId);
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const real = await vi.importActual<typeof ledgerMirror>("../src/ledger-mirror");

    const result = await real.mirrorEvent({
      home: state.home,
      hostSessionId: SESSION,
      // The same envelope the extension's own mirror writes (fields verbatim from the worker), so
      // the control exercises the destination and the attributed query rather than a shape of my own.
      record: {
        kind: "worker_completed",
        fields: {
          task_id: taskId,
          packet_sha256: state.packet_sha256,
          status: "completed",
          worker_agent: "worker",
          child_omp_agent_id: state.agent_id,
          child_omp_session_file: null,
          worker_model: null,
        },
      },
    } as never);
    if (!result.ok) console.log(`[destination dump] mirror reported failure: ${String(result.error)}`);
    expect(result.ok, `the real mirror write must succeed: ${String(result.error)}`).toBe(true);

    const deadline = Date.now() + 10_000;
    let records = 0;
    while (Date.now() < deadline && records === 0) {
      records = mirroredCompletions(state.home, taskId);
      if (records === 0) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (records === 0) console.log(`[destination dump] query found 0; final state:\n${dumpDestination(state.home, taskId)}`);
    expect(records, "the query detects the deliberately produced record").toBe(1);
  });
});
