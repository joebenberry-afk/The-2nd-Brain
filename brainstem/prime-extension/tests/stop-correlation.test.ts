import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, expect, it, vi } from "vitest";
import type { ExtensionAPI, ExtensionContext, ToolCallEventResult, ToolResultEventResult } from "../types/prime";
import type * as LedgerMirror from "../src/ledger-mirror";
import type { MirrorOptions } from "../src/ledger-mirror";
import { TelemetryStore } from "../src/storage";

type Handler = (event: unknown, ctx: ExtensionContext) => (ToolCallEventResult & ToolResultEventResult) | undefined | Promise<(ToolCallEventResult & ToolResultEventResult) | undefined>;
type FixtureCall = { toolName: string; toolCallId: string; input: Record<string, unknown> };
const stores = new Set<TelemetryStore>();
const append = TelemetryStore.prototype.append;
vi.spyOn(TelemetryStore.prototype, "append").mockImplementation(function(this: TelemetryStore, record: unknown) {
  stores.add(this);
  append.call(this, record);
});
const mirrors = vi.hoisted(() => [] as MirrorOptions[]);
vi.mock("../src/ledger-mirror", async (original) => {
  const actual = await original<typeof LedgerMirror>();
  return { ...actual, mirrorFireAndForget: vi.fn(), mirrorEventSync: (options: MirrorOptions) => {
    mirrors.push(options);
    const result = actual.mirrorEventSync({ ...options, python: resolve("../../.venv/Scripts/python.exe") });
    writeFileSync(join(options.home, "mirror-result.json"), JSON.stringify({ options, result }));
    return result;
  } };
});
// Runtime-selected copied handler gives the same consumer a genuine red baseline.
const factory = (await import(process.env.STOP_CORRELATION_BASELINE === "1" ? "../src/.stop-correlation-baseline" : "../src/index")).default;
afterEach(async () => {
  await Promise.all([...stores].map(store => store.flush()));
  stores.clear(); vi.unstubAllEnvs(); mirrors.length = 0;
});
function rig(id: string) {
  const base = process.env.STOP_CORRELATION_EVIDENCE || tmpdir();
  mkdirSync(base, { recursive: true });
  const home = mkdtempSync(join(base, `${id}-`));
  for (const [key, value] of Object.entries({ SECOND_BRAIN_HOME: home, SECOND_BRAIN_OBSERVABILITY: "on", SECOND_BRAIN_RTD: "off", SECOND_BRAIN_REREAD_AVOIDANCE: "OFF", SECOND_BRAIN_PYTHON: join(home, "absent.exe"), ORCHESTRATOR_MODELS: "", SECOND_BRAIN_RECALL: "off" })) vi.stubEnv(key, value);
  const handlers = new Map<string, Handler>();
  factory({ on: (name: string, handler: Handler) => handlers.set(name, handler) } as ExtensionAPI);
  const ctx = (session: string): ExtensionContext => ({ cwd: home, model: { provider: "fixture", id: "fixture" }, sessionManager: { getSessionFile: () => join(home, `${session}.jsonl`) }, getContextUsage: () => undefined, getSystemPrompt: () => "", hasUI: false } as ExtensionContext);
  const call = async (session: string, id = "call", target = session, extra = "") => {
    const input = { command: `brainctl stop decide --session ${target} --task-id task-1 ${extra} --json` };
    const event = { toolName: "bash", toolCallId: id, input };
    const patch = await handlers.get("tool_call")!(event, ctx(session));
    return { ...event, input: patch?.input ?? input } as FixtureCall;
  };
  const result = (session: string, event: FixtureCall, evidence: unknown, isError = false) => handlers.get("tool_result")!({ ...event, content: [{ type: "text", text: typeof evidence === "string" ? evidence : JSON.stringify(evidence) }], isError }, ctx(session));
  const action = async (session: string) => (await handlers.get("tool_call")!({ toolName: "write", toolCallId: "next", input: { path: "fixture", content: "fixture" } }, ctx(session)))?.block === true;
  const records = async (session: string) => {
    const file = join(home, "telemetry", "agent-performance", `${session}.jsonl`);
    await Promise.all([...stores].map(store => store.flush()));
    return readFileSync(file, "utf8").trim().split("\n").map(line => JSON.parse(line));
  };
  return { home, handlers, ctx, call, result, action, records };
}
function receipt(session = "receiver", extra: Record<string, unknown> = {}) {
  return { decision: "stop", stop_id: "stop-1", task_id: "task-1", session_id: session, parent_session_id: "", worker_session_id: "", reason_code: "completion_proven", triggering_condition: "completion_condition_satisfied", verification_state: "passed", completion_condition_state: "satisfied", final_substantive_event: "task_result", continuation_forbidden: true, ...extra };
}
it("SC01 rejects foreign schema-valid evidence before state and finalization", async () => {
  const r = rig("SC01"); const e = await r.call("receiver");
  await r.result("receiver", e, receipt("foreign"));
  expect(await r.action("receiver")).toBe(false);
  expect(mirrors).toHaveLength(0);
  const rows = await r.records("receiver");
  expect(rows.some(x => x.kind === "stop_evidence_rejected")).toBe(true);
  expect(rows.filter(x => x.kind === "stop_boundary")).toHaveLength(0);
});
it("SC02 matching positive blocks substantive actions and durably finalizes the target", async () => {
  const r = rig("SC02"); await r.result("receiver", await r.call("receiver"), receipt());
  expect(await r.action("receiver")).toBe(true);
  expect(mirrors.map(x => x.hostSessionId)).toEqual(["receiver"]);
  expect(JSON.parse(readFileSync(join(r.home, "mirror-result.json"), "utf8")).result.ok).toBe(true);
  expect((await r.records("receiver")).filter(x => x.kind === "stop_boundary")).toHaveLength(1);
});
it("SC03 continue neither arms nor clears the boundary", async () => {
  const r = rig("SC03"); const next = receipt("receiver", { decision: "continue", continuation_forbidden: false });
  await r.result("receiver", await r.call("receiver", "a"), next); expect(await r.action("receiver")).toBe(false);
  await r.result("receiver", await r.call("receiver", "b"), receipt());
  await r.result("receiver", await r.call("receiver", "c"), next); expect(await r.action("receiver")).toBe(true);
  expect(mirrors).toHaveLength(1);
});
it("SC04 rejects absent blank malformed unknown and conflicting identities", async () => {
  const r = rig("SC04");
  const variants = [{ session_id: undefined }, { session_id: "" }, { session_id: " " }, { session_id: "current" }, { session_id: "unknown" }, { session_id: "receiver/child" }, { parent_session_id: "foreign" }, { worker_session_id: "foreign" }, { task_id: "other-task" }, { decision: "stop", continuation_forbidden: false }, { parent_session_id: undefined }, { worker_session_id: undefined }];
  for (const [i, extra] of variants.entries()) { await r.result("receiver", await r.call("receiver", String(i)), receipt("receiver", extra)); expect(await r.action("receiver")).toBe(false); }
  await r.result("receiver", await r.call("receiver", "bad-json"), "{bad");
  expect(mirrors).toHaveLength(0);
  const rejects = (await r.records("receiver")).filter(x => x.kind === "stop_evidence_rejected"); expect(rejects.length).toBe(variants.length + 1);
  expect(rejects.every(x => !JSON.stringify(x).includes("foreign"))).toBe(true);
});
it("SC05 parent acknowledgement stops only a verified native child", async () => {
  const r = rig("SC05"); mkdirSync(join(r.home, "parent")); writeFileSync(join(r.home, "parent.jsonl"), ""); writeFileSync(join(r.home, "parent", "child.jsonl"), "");
  execFileSync(resolve("../../.venv/Scripts/python.exe"), ["-m", "second_brain", "ledger", "init", "--session", "parent", "--host", "prime"], { cwd: r.home, env: { ...process.env, SECOND_BRAIN_HOME: r.home }, stdio: "pipe" });
  const childCtx = { ...r.ctx("child"), sessionManager: { getSessionFile: () => join(r.home, "parent", "child.jsonl") } };
  await r.handlers.get("tool_call")!({ toolName: "telemetry", toolCallId: "register", input: {} }, childCtx);
  await r.result("parent", await r.call("parent", "child-stop", "child", "--parent-session-id parent --worker-session-id child"), receipt("child", { parent_session_id: "parent", worker_session_id: "child" }));
  expect(await r.action("parent")).toBe(false); expect(await r.action("child")).toBe(true);
  expect(mirrors.map(x => [x.hostSessionId, x.parentSessionId])).toEqual([["child", "parent"]]);
  expect(JSON.parse(readFileSync(join(r.home, "mirror-result.json"), "utf8")).result.ok).toBe(true);
});
it("SC06 concurrent sessions and colliding IDs cannot steal another invocation", async () => {
  const r = rig("SC06"); const a = await r.call("a", "same"); const b = await r.call("b", "same");
  await r.result("b", a, receipt("a")); expect(await r.action("a")).toBe(false); expect(await r.action("b")).toBe(false);
  await r.result("a", a, receipt("a")); await r.result("b", b, receipt("b"));
  expect(await r.action("a")).toBe(true); expect(await r.action("b")).toBe(true);
});
it("SC07 delayed results session switching and duplicate replay remain target-correct", async () => {
  const r = rig("SC07"); const a = await r.call("a"); await r.action("b");
  await r.result("b", a, receipt("a")); expect(await r.action("b")).toBe(false);
  await r.result("a", a, receipt("a"));
  for (let i = 0; i < 150; i++) await r.result("a", a, receipt("a"));
  await r.result("a", await r.call("a", "new-id"), receipt("a"));
  expect(await r.action("a")).toBe(true); expect(mirrors).toHaveLength(1);
  expect((await r.records("a")).filter(x => x.kind === "stop_evidence_rejected").length).toBeLessThanOrEqual(128);
});
it("SC08 ordinary STOP-shaped output and wrong tool have no authority", async () => {
  const r = rig("SC08"); const e = { toolName: "read", toolCallId: "ordinary", input: { path: "receipt" } };
  await r.handlers.get("tool_call")!(e, r.ctx("receiver")); await r.result("receiver", e, receipt());
  const pending = await r.call("receiver"); await r.result("receiver", { ...pending, toolName: "read" }, receipt());
  expect(await r.action("receiver")).toBe(false); expect(mirrors).toHaveLength(0);
  await r.result("receiver", pending, receipt()); expect(await r.action("receiver")).toBe(true);
});
it("SC09 foreign evidence preserves an already stopped session", async () => {
  const r = rig("SC09"); await r.result("receiver", await r.call("receiver", "a"), receipt());
  await r.result("receiver", await r.call("receiver", "b"), receipt("foreign"));
  expect(await r.action("receiver")).toBe(true); expect(mirrors).toHaveLength(1);
  expect((await r.records("receiver")).filter(x => x.kind === "stop_evidence_rejected")).toHaveLength(1);
});
it("SC10 errors remain errors and cannot finalize despite matching evidence", async () => {
  const r = rig("SC10"); const event = await r.call("receiver");
  const patch = await r.result("receiver", event, receipt(), true);
  expect(patch?.isError).not.toBe(false); expect(patch?.content).toBeUndefined();
  expect(await r.action("receiver")).toBe(false); expect(mirrors).toHaveLength(0);
  expect((await r.records("receiver")).some(x => x.kind === "tool_result" && x.is_error === true)).toBe(true);
});
it("SC11 exact full stem current rewriting and malformed invocation containment", async () => {
  const r = rig("SC11"); const session = "2026-09-06T10-41-16-361Z_01a0764e-e249-768d-87d7-543918f56b19";
  const e = await r.call(session, "current", "current"); expect(e.input.command).toContain(`--session ${session}`);
  await r.result(session, e, receipt(session)); expect(await r.action(session)).toBe(true);
  for (const [i, target] of ["unknown", "", "receiver --session receiver"].entries()) {
    await r.result("receiver", await r.call("receiver", `bad-${i}`, target), receipt()); expect(await r.action("receiver")).toBe(false);
  }
  const absent = { ...r.ctx("receiver"), sessionManager: { getSessionFile: () => undefined } };
  const unknownCall = { toolName: "bash", toolCallId: "absent-context", input: { command: "brainctl stop decide --session current --task-id task-1 --json" } };
  const patch = await r.handlers.get("tool_call")!(unknownCall, absent);
  const effective = { ...unknownCall, input: patch?.input ?? unknownCall.input };
  await r.handlers.get("tool_result")!({ ...effective, content: [{ type: "text", text: JSON.stringify(receipt()) }], isError: false }, absent);
  expect((await r.handlers.get("tool_call")!({ toolName: "write", toolCallId: "absent-action", input: {} }, absent))?.block).not.toBe(true);
});
