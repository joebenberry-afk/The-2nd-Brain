/**
 * Restart replay: what a journaled completion may and may not cause.
 *
 * The extension journals an admission and a result, and after a restart it reconstructs tracking
 * state from those entries. The credential admission minted is deliberately never journaled, so a
 * replayed completion is emitted with none. The safety requirement is not "nothing is emitted" —
 * it is that an unauthenticated replay produces no authoritative effect on either side:
 *
 *  - the recovered attempt is the journaled attempt, and the emitted options carry no credential;
 *  - the Brain's own row — not the journal's `accessIntent` label — decides whether authority is
 *    required, so a journal claiming `read_only` cannot downgrade a mutating attempt;
 *  - a refusal is recorded as a receipt failure, never as a worker failure, a successful delivery
 *    or a successful recovery;
 *  - replayed duplicates add no further effects.
 *
 * The route under test is the extension factory's registered `before_agent_start` hook (recovery
 * runs there, index.ts:3031) with the real result bridge (`runOmpWorkerResult`) and the real Python
 * consumer (`-m second_brain autoinject omp-routing`), against the disposable Brain state built by
 * `tests/fixtures/omp_replay_state.py`. Only the runner capture is a seam; it delegates to the real
 * bridge. `tests/worker-result-authority.test.ts` covers payload construction with a mocked child.
 *
 * The last case records a known open finding rather than a protection: journal fields alone decide
 * acceptance for a genuinely read-only attempt. It is reported under the source-authenticity
 * boundary (#4), and it is asserted here so the boundary's real scope is evidence, not inference.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import {
  ompWorkerResultPayload,
  runOmpWorkerResult,
  type OmpWorkerResultOptions,
  type OmpWorkerResultOutcome,
} from "../src/worker-result-bridge";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

const CANDIDATE_ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const PYTHON = process.env.SECOND_BRAIN_PYTHON ?? candidatePython();
const FIXTURE = fileURLToPath(
  new URL("../../../tests/fixtures/omp_replay_state.py", import.meta.url),
);
const SESSION = "omp-session";
const TIMESTAMP = "2026-01-01T00:00:00.000Z";
let BASE = "";

/** The candidate's own interpreter, derived from the test location rather than the environment. */
function candidatePython(): string {
  return join(CANDIDATE_ROOT, ".venv", "Scripts", "python.exe");
}

function assertInsideCandidate(resolved: string, what: string): void {
  const root = resolve(CANDIDATE_ROOT);
  const path = resolve(resolved);
  expect(path, `${what} must resolve inside the candidate worktree: ${path}`)
    .toContain(root);
}

const savedHome = process.env.SECOND_BRAIN_HOME;
const savedPython = process.env.SECOND_BRAIN_PYTHON;

interface FixtureState {
  home: string;
  repo: string;
  host_session_id: string;
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
  python: string;
  second_brain_file: string;
}

interface ProbeState {
  state: string;
  writer_ownership: string;
  attempt_id: string | null;
  attempt_results: number;
  result_sha256: string | null;
  callback_digest_present: boolean;
  callback_digest_sha256: string | null;
  logical_outcome: string | null;
  executor_settled: number;
  cleanup_complete: number;
  lease_expires_at: string | null;
  host_generation: number | null;
  native_attempt_id: string | null;
  native_job_id: string | null;
  agent_id: string | null;
  lifecycle_sequence: number | null;
}

type Handler = (event: unknown, context: ExtensionContext) => unknown;

function childEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue;
    // `PYTHONHOME` on this machine points at a corrupted interpreter tree, and no Brain
    // environment from the running session may reach a disposable home.
    if (key === "PYTHONHOME" || key === "PYTHONPATH" || key.startsWith("SECOND_BRAIN_")) continue;
    env[key] = value;
  }
  return env;
}

/** Run the fixture and return its single JSON envelope, failing loudly on a non-ok envelope. */
function runFixture<T extends { ok: boolean }>(args: string[]): T {
  const out = execFileSync(PYTHON, [FIXTURE, ...args], { env: childEnv(), encoding: "utf8", stdio: "pipe" });
  const parsed = JSON.parse(out) as T;
  if (!parsed.ok) throw new Error(`fixture ${args[0]} failed: ${out.trim()}`);
  return parsed;
}

/** Create the disposable home + registered worktree + admitted attempt under `base`. */
function setup(base: string, taskId: string, intent: "mutating" | "read_only"): FixtureState {
  const parsed = runFixture<FixtureState & { ok: boolean }>([
    "setup", "--base", base, "--task-id", taskId, "--intent", intent, "--host-session", SESSION,
  ]);
  // Identity of the state this case runs against: both the interpreter and the resolved source
  // tree must live inside the candidate worktree, whatever the environment prefers. Asserting
  // only equality with an environment-selected path would be a tautology.
  assertInsideCandidate(parsed.python, "interpreter");
  assertInsideCandidate(parsed.second_brain_file, "second_brain source");
  expect(parsed.python).toBe(candidatePython());
  expect(parsed.second_brain_file).toBe(join(CANDIDATE_ROOT, "src", "second_brain", "__init__.py"));
  console.log(`[replay] interpreter=${parsed.python} second_brain=${parsed.second_brain_file}`);
  return parsed;
}

/** Run the fixture's authenticated completion, so the attempt already has an accepted outcome. */
function accept(base: string, taskId: string): Record<string, unknown> {
  return runFixture<{ ok: boolean } & Record<string, unknown>>([
    "accept", "--base", base, "--task-id", taskId,
  ]);
}

function probe(base: string, taskId: string): ProbeState {
  return runFixture<ProbeState & { ok: boolean }>(["probe", "--base", base, "--task-id", taskId]);
}

/** Session-binding entry the identity resolver reads; not a journal event. */
const IDENTITY_ENTRY = {
  type: "custom",
  customType: "brain.active-state",
  details: { session_id: SESSION },
  timestamp: TIMESTAMP,
};

function admissionEntry(state: FixtureState, accessIntent: "mutating" | "read_only") {
  return {
    type: "custom",
    customType: "second-brain.worker-admission-pending",
    timestamp: TIMESTAMP,
    data: {
      session: SESSION,
      taskId: state.task_id,
      attemptId: state.attempt_id,
      packetSha256: state.packet_sha256,
      projectId: state.project_id,
      worktreeId: state.worktree_id,
      accessIntent,
      parentSessionId: SESSION,
      agent: "worker",
      toolCallId: "call-replay",
      sourceIndex: 0,
    },
  };
}

function jobEntry(state: FixtureState, accessIntent: "mutating" | "read_only") {
  return {
    type: "custom",
    customType: "second-brain.worker-job-pending",
    timestamp: TIMESTAMP,
    data: {
      session: SESSION,
      jobId: state.native_job_id,
      accessIntent,
      toolCallId: "call-replay",
      sourceIndex: 0,
      taskId: state.task_id,
      attemptId: state.attempt_id,
      packetSha256: state.packet_sha256,
      parentSessionId: SESSION,
      agent: "worker",
      agentId: state.agent_id,
      hostGeneration: state.host_generation,
      nativeAttemptId: state.native_attempt_id,
      projectId: state.project_id,
      worktreeId: state.worktree_id,
    },
  };
}

function resultEntry(state: FixtureState) {
  return {
    type: "custom",
    customType: "second-brain.worker-result-pending",
    timestamp: TIMESTAMP,
    data: {
      session: SESSION,
      attemptId: state.attempt_id,
      summary: "restart replay",
      fields: {
        task_id: state.task_id,
        packet_sha256: state.packet_sha256,
        status: "completed",
        worker_agent: "worker",
        child_omp_agent_id: state.agent_id,
        child_omp_session_file: null,
        worker_model: null,
      },
    },
  };
}

function context(state: FixtureState, entries: unknown[]): ExtensionContext {
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

interface Started {
  handlers: Map<string, Handler>;
  journal: Array<{ customType: string; data: unknown }>;
  emissions: OmpWorkerResultOptions[];
  outcomes: OmpWorkerResultOutcome[];
  dispatchFailures: unknown[];
}

/** Start the extension with the runner seam delegating to the real bridge. */
function startExtension(options: { register?: boolean } = {}): Started {
  const register = options.register ?? true;
  const handlers = new Map<string, Handler>();
  const journal: Array<{ customType: string; data: unknown }> = [];
  const emissions: OmpWorkerResultOptions[] = [];
  const outcomes: OmpWorkerResultOutcome[] = [];
  const dispatchFailures: unknown[] = [];
  const pi = {
    on: (name: string, handler: Handler) => {
      if (register) handlers.set(name, handler);
    },
    emit: () => {},
    appendEntry: (customType: string, data: unknown) => {
      journal.push({ customType, data });
    },
  } as unknown as ExtensionAPI;
  const extensionOptions: ExtensionOptions = {
    ompWorkerResultRunner: (workerOptions) => {
      emissions.push(workerOptions);
      return runOmpWorkerResult(workerOptions).then((outcome) => {
        outcomes.push(outcome);
        return outcome;
      });
    },
    ompWorkerDispatchFailedRunner: (dispatchOptions) => {
      dispatchFailures.push(dispatchOptions);
      return Promise.resolve({ ok: true, status: "accepted" });
    },
  };
  factory(pi, extensionOptions);
  return { handlers, journal, emissions, outcomes, dispatchFailures };
}

async function runBeforeAgentStart(started: Started, state: FixtureState, entries: unknown[]): Promise<void> {
  const handler = started.handlers.get("before_agent_start");
  expect(handler, "before_agent_start was not registered").toBeDefined();
  await handler!({ type: "before_agent_start", prompt: "replay" }, context(state, entries));
}

function telemetryRecords(home: string): Array<Record<string, unknown>> {
  const file = `${home}/telemetry/agent-performance/${SESSION}.jsonl`;
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

/** Journal entries the extension itself wrote for worker lifecycle, not identity bookkeeping. */
function journalKinds(started: Started): string[] {
  return started.journal
    .map((entry) => entry.customType)
    .filter((customType) => customType.startsWith("second-brain.worker-"));
}

/**
 * Send the *same bytes the bridge sent* to the consumer directly and return its raw verdict.
 * The bridge collapses a refusal into a receipt error, so this is what names the reason.
 */
function consumerVerdict(home: string, options: OmpWorkerResultOptions): Record<string, unknown> {
  const payload = ompWorkerResultPayload(options);
  const env = { ...childEnv(), SECOND_BRAIN_HOME: home };
  const out = execFileSync(PYTHON, ["-m", "second_brain", "autoinject", "omp-routing"], {
    input: JSON.stringify(payload),
    env,
    cwd: home,
    encoding: "utf8",
    stdio: "pipe",
  });
  return JSON.parse(out) as Record<string, unknown>;
}

/** The seam must delegate to the real bridge, so a receipt failure is a real refusal. */
function expectReceiptFailure(outcome: OmpWorkerResultOutcome | undefined): void {
  expect(outcome, "the real bridge produced no outcome").toBeDefined();
  expect(outcome!.ok).toBe(false);
  expect(outcome!.status).toBeUndefined();
  expect(outcome!.resultSha256).toBeUndefined();
  expect(String(outcome!.error)).toMatch(/^BRAIN_WORKER_RESULT/);
  // Transport failures would make the refusal vacuous: the consumer must have answered.
  expect(outcome!.error).not.toBe("BRAIN_WORKER_RESULT_UNAVAILABLE");
}

beforeAll(() => {
  BASE = mkdtempSync(join(tmpdir(), "sb-worker-replay-"));
});

beforeEach(() => {
  vi.stubEnv("SECOND_BRAIN_HOME", BASE);
  vi.stubEnv("SECOND_BRAIN_OBSERVABILITY", "on");
  vi.stubEnv("SECOND_BRAIN_RTD", "off");
  vi.stubEnv("SECOND_BRAIN_REREAD_AVOIDANCE", "OFF");
  vi.stubEnv("SECOND_BRAIN_RECALL", "off");
  vi.stubEnv("SECOND_BRAIN_PYTHON", PYTHON);
  vi.stubEnv("ORCHESTRATOR_MODELS", "");
  expect(existsSync(PYTHON), `candidate interpreter missing: ${PYTHON}`).toBe(true);
  expect(existsSync(FIXTURE), `fixture missing: ${FIXTURE}`).toBe(true);
});

afterEach(() => {
  vi.unstubAllEnvs();
  if (savedHome === undefined) delete process.env.SECOND_BRAIN_HOME;
  else process.env.SECOND_BRAIN_HOME = savedHome;
  if (savedPython === undefined) delete process.env.SECOND_BRAIN_PYTHON;
  else process.env.SECOND_BRAIN_PYTHON = savedPython;
});

afterAll(() => {
  try {
    rmSync(BASE, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  } catch (error) {
    // A spawned bridge can still hold this disposable tree as its cwd, and Windows locks a live
    // process's cwd. The tree lives in the OS temp directory and is not part of the tested
    // behaviour, so report the leftover instead of failing the suite on cleanup.
    console.warn(`[worker-result-replay] temp tree left behind: ${BASE}: ${String(error)}`);
  }
});

/** These cases spawn a real interpreter and a real Brain consumer; the default 5s budget does not
 * survive a loaded full-suite run. */
const itSlow = (name: string, run: () => Promise<void>) => it(name, run, 60_000);

describe("restart replay of a journaled worker completion", () => {
  itSlow("recovers the journaled attempt, emits it without a credential, and changes no durable fact", async () => {
    const taskId = "replay-mutating";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "mutating");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const before = probe(base, taskId);
    expect(before).toMatchObject({
      state: "WORKING",
      writer_ownership: "held",
      attempt_results: 0,
      callback_digest_present: true,
    });

    const started = startExtension();
    await runBeforeAgentStart(started, state, [
      IDENTITY_ENTRY,
      admissionEntry(state, "mutating"),
      jobEntry(state, "mutating"),
      resultEntry(state),
    ]);

    // Reachability: the emission came from the journaled attempt, not from another route.
    expect(started.emissions).toHaveLength(1);
    const emitted = started.emissions[0];
    expect(emitted.taskId).toBe(state.task_id);
    expect(emitted.attemptId).toBe(state.attempt_id);
    expect(emitted.packetSha256).toBe(state.packet_sha256);
    expect(emitted.status).toBe("completed");
    // The credential admission minted is never journaled, and recovery invents none.
    expect(emitted.callbackToken).toBeUndefined();

    expectReceiptFailure(started.outcomes[0]);
    // The same bytes, sent straight to the consumer, name the refusal: the Brain refused this
    // attempt's completion for lack of the authority admission minted, not for a malformed or
    // misbound request (the credential-present control below shows acceptance otherwise).
    const verdict = consumerVerdict(state.home, started.emissions[0]);
    expect(verdict.failure_code).toBe("UNAUTHORIZED_CALLBACK");
    expect(verdict.status).toBe("failed");

    expect(journalKinds(started)).toContain("second-brain.worker-result-pending");
    expect(journalKinds(started)).not.toContain("second-brain.worker-result-accepted");
    const records = telemetryRecords(state.home);
    const errors = records.filter((record) => record.kind === "extension_error");
    expect(errors.some((record) => String(record.error).includes(String(started.outcomes[0]?.error))))
      .toBe(true);
    // NOTE: `emitWorkerCompletion` mirrors an *accepted* completion through `mirror(...)`
    // (src/index.ts:883), which is fire-and-forget into the ledger-mirror engine and writes no
    // telemetry record. Asserting "no worker_completed here" would therefore never fail, so it is
    // deliberately absent: the honest statement is that the mirror sink is not asserted by this
    // file, and an independent verifier flagged exactly that. What is asserted instead is the
    // journal the extension itself writes: no `worker-result-accepted` (above) and a correlated
    // `extension_error` (below).
    expect(started.dispatchFailures).toHaveLength(0);

    const after = probe(base, taskId);
    expect(after).toEqual(before);
  });

  itSlow("replays an already accepted mutating completion without rewriting its outcome", async () => {
    // The decisive duplicate case: the attempt already holds an accepted outcome and the
    // credential that authorised it, and the replay has neither. Nothing about the accepted
    // result, the authority digest or the ownership row may change.
    const taskId = "replay-accepted";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "mutating");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    accept(base, taskId);
    const before = probe(base, taskId);
    expect(before).toMatchObject({
      state: "COMPLETED",
      writer_ownership: "held",
      attempt_results: 1,
      callback_digest_present: true,
    });
    expect(before.result_sha256, "the accepted outcome is on disk").toMatch(/^[0-9a-f]{64}$/);
    expect(before.callback_digest_sha256).toMatch(/^[0-9a-f]{64}$/);

    const started = startExtension();
    await runBeforeAgentStart(started, state, [
      IDENTITY_ENTRY,
      admissionEntry(state, "mutating"),
      jobEntry(state, "mutating"),
      resultEntry(state),
    ]);

    expect(started.emissions).toHaveLength(1);
    expect(started.emissions[0].callbackToken).toBeUndefined();
    expectReceiptFailure(started.outcomes[0]);
    expect(consumerVerdict(state.home, started.emissions[0]).failure_code).toBe("UNAUTHORIZED_CALLBACK");
    expect(journalKinds(started)).not.toContain("second-brain.worker-result-accepted");
    expect(started.dispatchFailures).toHaveLength(0);

    const after = probe(base, taskId);
    expect(after).toEqual(before);
  });

  itSlow("does not let a journal label downgrade an authoritatively mutating attempt", async () => {
    const taskId = "replay-downgrade";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "mutating");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const before = probe(base, taskId);
    expect(before.writer_ownership).toBe("held");
    expect(before.callback_digest_present).toBe(true);

    // The journal claims the attempt was read-only; the Brain's own row says mutating and holds
    // the authority admission minted. The claim must not remove the requirement. The journal is
    // otherwise complete (job binding included), so the label is the only difference from the
    // authenticated-looking replay above — and a binding-only refusal would not satisfy this case.
    const started = startExtension();
    await runBeforeAgentStart(started, state, [
      IDENTITY_ENTRY,
      admissionEntry(state, "read_only"),
      jobEntry(state, "read_only"),
      resultEntry(state),
    ]);

    expect(started.emissions).toHaveLength(1);
    expect(started.emissions[0].callbackToken).toBeUndefined();
    expect(started.emissions[0].attemptId).toBe(state.attempt_id);
    expectReceiptFailure(started.outcomes[0]);
    expect(journalKinds(started)).not.toContain("second-brain.worker-result-accepted");
    expect(started.dispatchFailures).toHaveLength(0);

    const after = probe(base, taskId);
    expect(after).toEqual(before);
  });

  itSlow("repeats the refusal without accumulated effects when the same journal is replayed twice", async () => {
    const taskId = "replay-twice";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "mutating");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const before = probe(base, taskId);
    const entries = [
      IDENTITY_ENTRY,
      admissionEntry(state, "mutating"),
      jobEntry(state, "mutating"),
      resultEntry(state),
    ];

    for (const _ of [0, 1]) {
      const started = startExtension();
      await runBeforeAgentStart(started, state, entries);
      expect(started.emissions).toHaveLength(1);
      expectReceiptFailure(started.outcomes[0]);
      expect(journalKinds(started)).not.toContain("second-brain.worker-result-accepted");
    }

    const after = probe(base, taskId);
    expect(after).toEqual(before);
    expect(after.attempt_results).toBe(0);
  });

  itSlow("emits nothing when the journal holds a result but no persisted admission", async () => {
    const taskId = "replay-no-admission";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "mutating");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);

    const started = startExtension();
    await runBeforeAgentStart(started, state, [IDENTITY_ENTRY, resultEntry(state)]);

    expect(started.emissions).toHaveLength(0);
    expect(journalKinds(started)).toHaveLength(0);
    expect(probe(base, taskId).state).toBe("WORKING");
  });

  itSlow("shows the reachability assertions are sensitive to the recovery hook running", async () => {
    // Control for every case above: with the same fixture and the recovery hook disconnected, the
    // observations that prove recovery ran disappear. Without this, "no authoritative effect"
    // could pass because recovery never executed.
    const taskId = "replay-disconnected";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "mutating");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);

    const disconnected = startExtension({ register: false });
    expect(disconnected.handlers.get("before_agent_start")).toBeUndefined();
    expect(disconnected.handlers.size).toBe(0);
    expect(disconnected.emissions).toHaveLength(0);
    expect(journalKinds(disconnected)).toHaveLength(0);

    // The same journal through the registered hook does produce the reachability evidence.
    const connected = startExtension();
    await runBeforeAgentStart(connected, state, [
      IDENTITY_ENTRY,
      admissionEntry(state, "mutating"),
      jobEntry(state, "mutating"),
      resultEntry(state),
    ]);
    expect(connected.emissions).toHaveLength(1);
    expect(journalKinds(connected)).toContain("second-brain.worker-result-pending");
  });

  itSlow("accepts the same emitted payload when the attempt's credential is present", async () => {
    // Control for the refusals above: same fixture family, same bridge, same payload shape — only
    // the credential differs. Acceptance proves the replayed payload was binding-correct, so the
    // refusals were caused by the missing authority and not by a malformed or misbound request.
    const taskId = "replay-credential";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "mutating");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    expect(typeof state.callback_token).toBe("string");

    const started = startExtension();
    await runBeforeAgentStart(started, state, [
      IDENTITY_ENTRY,
      admissionEntry(state, "mutating"),
      jobEntry(state, "mutating"),
      resultEntry(state),
    ]);
    expect(started.emissions).toHaveLength(1);
    expectReceiptFailure(started.outcomes[0]);

    const authorized = await runOmpWorkerResult({
      ...started.emissions[0],
      callbackToken: state.callback_token ?? undefined,
    });
    expect(authorized).toMatchObject({
      ok: true,
      status: "completed",
      taskId: state.task_id,
      attemptId: state.attempt_id,
      packetSha256: state.packet_sha256,
    });

    const after = probe(base, taskId);
    expect(after.state).toBe("COMPLETED");
    expect(after.attempt_results).toBe(1);
  });

  itSlow("keeps the attempt credential out of every recorded destination", async () => {
    // A raw credential in the private host-runner options is not a disclosure by itself; the
    // question is whether any *recorded* surface serializes it. This scans the destinations this
    // route actually writes: the extension's own journal, the telemetry it appends, and every
    // error string returned to the caller. The runner-seam options are excluded deliberately —
    // they are the host-internal transport, not a record.
    const taskId = "replay-credential-scan";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "mutating");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    const sentinel = state.callback_token;
    expect(typeof sentinel).toBe("string");

    const started = startExtension();
    await runBeforeAgentStart(started, state, [
      IDENTITY_ENTRY,
      admissionEntry(state, "mutating"),
      jobEntry(state, "mutating"),
      resultEntry(state),
    ]);
    const authorized = await runOmpWorkerResult({
      ...started.emissions[0],
      callbackToken: sentinel ?? undefined,
    });
    expect(authorized.ok).toBe(true);

    // Sensitivity of the scan itself, and the honest scope of this case: on the *replay* path the
    // credential is absent by construction — recovery never reconstructs it — so scanning these
    // destinations cannot by itself show that the search works. The control therefore proves the
    // search against a string that does contain the sentinel, and the assertion above is a guard
    // against a future change that starts threading the credential into a record. The path where
    // the credential legitimately travels (host-internal runner options, supplied to the direct
    // bridge call below) is a transport, not a record, and is excluded on purpose.
    const probe = JSON.stringify({ transport: sentinel });
    expect(probe.includes(String(sentinel))).toBe(true);
    expect(JSON.stringify({ transport: undefined }).includes(String(sentinel))).toBe(false);

    const destinations: Record<string, string> = {
      journal: JSON.stringify(started.journal),
      telemetry: JSON.stringify(telemetryRecords(state.home)),
      outcomes: JSON.stringify(started.outcomes),
      dispatchFailures: JSON.stringify(started.dispatchFailures),
    };
    for (const [where, text] of Object.entries(destinations)) {
      expect(text.includes(String(sentinel)), `credential appeared in ${where}`).toBe(false);
    }
    // The same requirement for the refusal path, which is where an error string is actually
    // produced by the bridge.
    const refused = await runOmpWorkerResult({ ...started.emissions[0], callbackToken: undefined });
    expect(refused.ok).toBe(false);
    expect(String(refused.error).includes(String(sentinel))).toBe(false);
  });

  itSlow("records the open finding: a read-only attempt accepts a journal-only completion", async () => {
    // Known open finding under the source-authenticity boundary (#4), asserted here to fix its
    // real scope. The Brain's guard requires completion authority only for attempts that hold
    // writer ownership; a read-only attempt holds none, so journal fields alone decide acceptance.
    const taskId = "replay-readonly";
    const base = `${BASE}/${taskId}`;
    const state = setup(base, taskId, "read_only");
    vi.stubEnv("SECOND_BRAIN_HOME", state.home);
    expect(state.callback_token).toBeNull();
    const before = probe(base, taskId);
    expect(before).toMatchObject({
      state: "WORKING",
      writer_ownership: "released",
      attempt_results: 0,
      callback_digest_present: false,
    });

    const started = startExtension();
    await runBeforeAgentStart(started, state, [
      IDENTITY_ENTRY,
      admissionEntry(state, "read_only"),
      resultEntry(state),
    ]);

    expect(started.emissions).toHaveLength(1);
    expect(started.emissions[0].callbackToken).toBeUndefined();
    expect(started.outcomes[0]?.ok).toBe(true);
    expect(journalKinds(started)).toContain("second-brain.worker-result-accepted");

    const after = probe(base, taskId);
    expect(after.state).toBe("COMPLETED");
    expect(after.attempt_results).toBe(1);
    // No writer lease existed to release, so the digest of this effect stays evidence integrity.
    expect(after.writer_ownership).toBe(before.writer_ownership);

    // A duplicate replay of the same accepted completion adds no second effect.
    const replay = startExtension();
    await runBeforeAgentStart(replay, state, [
      IDENTITY_ENTRY,
      admissionEntry(state, "read_only"),
      resultEntry(state),
    ]);
    expect(replay.emissions).toHaveLength(1);
    const repeated = probe(base, taskId);
    expect(repeated.state).toBe("COMPLETED");
    expect(repeated.attempt_results).toBe(1);
  });
});
