import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import factory, { type ExtensionOptions } from "../src/index";
import {
  parseConfiguredOmpCandidates,
  parseOmpRoutingOutput,
  type OmpRoutingDecision,
} from "../src/routing-bridge";
import type { ExtensionAPI, ExtensionContext } from "../types/prime";

let home: string;
const savedHome = process.env.SECOND_BRAIN_HOME;

beforeEach(async () => {
  home = await mkdtemp(join(tmpdir(), "sb-omp-routing-"));
  process.env.SECOND_BRAIN_HOME = home;
});

afterEach(async () => {
  if (savedHome === undefined) delete process.env.SECOND_BRAIN_HOME;

  else process.env.SECOND_BRAIN_HOME = savedHome;
  await rm(home, { recursive: true, force: true });
});
async function telemetry(): Promise<Array<Record<string, unknown>>> {
  await new Promise((resolve) => setTimeout(resolve, 30));
  const text = await readFile(join(home, "telemetry", "agent-performance", "omp-session.jsonl"), "utf8");
  return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line) as Record<string, unknown>);
}

function ctx(): ExtensionContext {
  const timestamp = "2026-01-01T00:00:00.000Z";
  return {
    cwd: "C:/omp-project",
    model: { provider: "original-provider", id: "original-model" },
    sessionManager: {
      getSessionFile: () => join(home, "omp-session.jsonl"),
      getSessionId: () => "native-omp-session",
      getHeader: () => ({ type: "session", version: 1, id: "native-omp-session", timestamp }),
      getEntries: () => [{
        type: "custom",
        customType: "brain.active-state",
        details: { session_id: "omp-session" },
        timestamp,
      }],
    },
    getContextUsage: () => undefined,
    getSystemPrompt: () => "base",
    signal: undefined,
    hasUI: false,
    ui: undefined,
  };
}

function decision(): OmpRoutingDecision {
  return {
    decision_id: "model-decision-test",
    task_hash: "0123456789abcdef",
    host_session_id: "omp-session",
    project_id: "omp-project",
    bot_role: "worker",
    selected_provider: "selected-provider",
    selected_model: "selected-model",
    selected_tier: "balanced",
    selected_cost_class: "medium",
    candidate_set_hash: "candidate-hash",
    fallback_used: false,
    fallback_provider: null,
    fallback_model: null,
    reason_code: "LOWEST_COST_ELIGIBLE",
    status: "selected",
    failure_code: null,
    routing_error: false,
  };
}

describe("OMP routing bridge", () => {
  it("parses only bounded Brain decisions", () => {
    const parsed = parseOmpRoutingOutput(JSON.stringify({ decision: decision() }));
    expect(parsed.decision?.decision_id).toBe("model-decision-test");
    expect(parseOmpRoutingOutput("x"));
    expect(parseOmpRoutingOutput("x").error).toBe("BRAIN_ROUTING_INVALID_JSON");
  });
  it("parses bounded configured candidates and fails open on malformed JSON", () => {
    const configured = parseConfiguredOmpCandidates(
      JSON.stringify({
        candidates: [{
          provider: "openai-codex",
          model: "gpt-5.6-luna",
          tier: "balanced",
          cost_class: "medium",
          capabilities: ["deep_reasoning"],
          availability: { provider_available: true, model_available: true },
        }],
      }),
    );
    expect(configured?.[0]).toMatchObject({
      provider: "openai-codex",
      model: "gpt-5.6-luna",
      tier: "balanced",
      cost_class: "medium",
      provider_available: true,
    });
    expect(parseConfiguredOmpCandidates("{bad")).toBeNull();
  });

  it("caches a decision, rewrites effective identity, records lifecycle correlation, and emits readiness", async () => {
    type Handler = (event: unknown, context: ExtensionContext) => unknown;
    const handlers = new Map<string, Handler>();
    const emitted: string[] = [];
    let calls = 0;
    const options: ExtensionOptions = {
      ompRoutingRunner: async () => {
        calls += 1;
        return { decision: decision() };
      },
    };
    const pi = {
      on: (name: string, handler: Handler) => handlers.set(name, handler),
      emit: (name: string) => emitted.push(name),
    } as unknown as ExtensionAPI;
    factory(pi, options);
    const context = ctx();
    await handlers.get("before_agent_start")!({ prompt: "bounded task" }, context);
    await handlers.get("before_agent_start")!({ prompt: "bounded task" }, context);
    expect(calls).toBe(1);
    const payload = { provider: "original-provider", model: "original-model", messages: [] };
    const replacement = await handlers.get("before_provider_request")!({ payload }, context);
    expect(replacement).toMatchObject({ provider: "selected-provider", model: "selected-model" });
    await handlers.get("after_provider_response")!({ status: 200, headers: {} }, context);
    await handlers.get("message_end")!({
      message: { role: "assistant", usage: { input: 1, output: 2, total: 3 } },
    }, context);
    const records = await telemetry();
    const invocation = records.find((record) => record.kind === "omp_routing_invocation");
    expect(invocation?.effective_provider).toBe("selected-provider");
    const usage = records.find((record) => record.kind === "assistant_usage");
    expect(usage?.provider).toBe("selected-provider");
    expect(usage?.model).toBe("selected-model");
    expect(invocation?.effective_model).toBe("selected-model");
    expect(records.some((record) => record.kind === "OMP_SECOND_BRAIN_READY")).toBe(true);
    expect(records.some((record) => record.kind === "omp_routing_response")).toBe(true);
  });

  it("preserves payload and records explicit provider handoff failure when provider is unrepresentable", async () => {
    type Handler = (event: unknown, context: ExtensionContext) => unknown;
    const handlers = new Map<string, Handler>();
    const pi = { on: (name: string, handler: Handler) => handlers.set(name, handler) } as unknown as ExtensionAPI;
    factory(pi, { ompRoutingRunner: async () => ({ decision: decision() }) });
    const context = ctx();
    await handlers.get("before_agent_start")!({ prompt: "handoff task" }, context);
    const payload = { model: "original-model", messages: [] };
    const replacement = await handlers.get("before_provider_request")!({ payload }, context);
    expect(replacement).toBeUndefined();
    const records = await telemetry();
    expect(records.find((record) => record.kind === "omp_routing_handoff_failure")?.reason).toBe("OMP_PROVIDER_NOT_REPRESENTABLE");
  });
  it("rewrites a model-only payload when Brain keeps the effective provider", async () => {
    type Handler = (event: unknown, context: ExtensionContext) => unknown;
    const handlers = new Map<string, Handler>();
    const pi = { on: (name: string, handler: Handler) => handlers.set(name, handler) } as unknown as ExtensionAPI;
    const selected = { ...decision(), selected_provider: "original-provider" };
    factory(pi, { ompRoutingRunner: async () => ({ decision: selected }) });
    const context = {
      ...ctx(),
      getSystemPrompt: (() => undefined) as unknown as () => string,
    };
    await handlers.get("before_agent_start")!({ prompt: "same provider" }, context);
    const payload = { model: "original-model", messages: [] };
    const replacement = await handlers.get("before_provider_request")!({ payload }, context);
    expect(replacement).toMatchObject({ model: "selected-model" });
    expect((replacement as Record<string, unknown>).provider).toBeUndefined();
    await telemetry();
  });

  it("does not emit readiness for a failed Brain decision", async () => {
    type Handler = (event: unknown, context: ExtensionContext) => unknown;
    const emitted: string[] = [];
    const handlers = new Map<string, Handler>();
    const failed = {
      ...decision(),
      status: "failed" as const,
      selected_provider: null,
      selected_model: null,
      selected_tier: null,
      selected_cost_class: null,
    };
    const pi = {
      on: (name: string, handler: Handler) => handlers.set(name, handler),
      emit: (name: string) => emitted.push(name),
    } as unknown as ExtensionAPI;
    factory(pi, { ompRoutingRunner: async () => ({ decision: failed }) });
    await handlers.get("before_agent_start")!({ prompt: "failed route" }, ctx());
    expect(emitted).toEqual([]);
    const records = await telemetry();
    expect(records.some((record) => record.kind === "OMP_SECOND_BRAIN_READY")).toBe(false);
  });
});
