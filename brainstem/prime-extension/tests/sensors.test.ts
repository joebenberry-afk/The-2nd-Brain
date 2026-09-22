import { describe, expect, it } from "vitest";
import * as sensors from "../src/sensors";

const SESSION = "test-session-123";

/** All records must carry the common schema fields. */
function expectBase(record: object, kind: string): void {
  const r = record as unknown as Record<string, unknown>;
  expect(r.v).toBe(2);
  expect(typeof r.ts).toBe("string");
  expect(new Date(r.ts as string).toISOString()).toBe(r.ts); // ISO-8601 UTC, ms precision
  expect(r.kind).toBe(kind);
  expect(r.session).toBe(SESSION);
}

describe("sensors: event -> record mapping", () => {
  it("session_start -> kind session_start with reason, cwd, model", () => {
    const record = sensors.sessionStart(SESSION, "startup", "/work", {
      id: "deepseek-v4-flash",
      provider: "deepseek",
    });
    expectBase(record, "session_start");
    expect(record.reason).toBe("startup");
    expect(record.cwd).toBe("/work");
    expect(record.model).toBe("deepseek/deepseek-v4-flash");
  });

  it("session_start -> model null when model is undefined", () => {
    const record = sensors.sessionStart(SESSION, "new", "/work", undefined);
    expect(record.model).toBeNull();
  });

  it("before_agent_start -> prompt_chars only (never the prompt text)", () => {
    const prompt = "Please summarize this long conversation";
    const record = sensors.beforeAgentStart(SESSION, prompt);
    expectBase(record, "before_agent_start");
    expect(record.prompt_chars).toBe(prompt.length);
    expect(JSON.stringify(record)).not.toContain(prompt);
  });

  it("before_agent_start -> additive role + driver_contract_injected fields (driver)", () => {
    const record = sensors.beforeAgentStart(SESSION, "x", "driver", true);
    expectBase(record, "before_agent_start");
    expect(record.role).toBe("driver");
    expect(record.driver_contract_injected).toBe(true);
  });

  it("before_agent_start -> role present without injected flag for non-driver roles", () => {
    const record = sensors.beforeAgentStart(SESSION, "x", "worker");
    expectBase(record, "before_agent_start");
    expect(record.role).toBe("worker");
    expect(record.driver_contract_injected).toBeUndefined();
  });

  it("turn_start -> turn", () => {
    const record = sensors.turnStart(SESSION, 3);
    expectBase(record, "turn_start");
    expect(record.turn).toBe(3);
  });

  it("context -> messages count only", () => {
    const messages = [{ content: "secret a" }, { content: "secret b" }];
    const record = sensors.context(SESSION, messages);
    expectBase(record, "context");
    expect(record.messages).toBe(2);
    expect(JSON.stringify(record)).not.toContain("secret");
  });

  it("tool_call (bash) -> tool, id, command truncated to 500 chars, input_bytes", () => {
    const longCommand = `echo ${"x".repeat(600)}`;
    const record = sensors.toolCall(SESSION, "bash", "call-1", {
      command: longCommand,
      timeout: 120,
    });
    expectBase(record, "tool_call");
    expect(record.tool).toBe("bash");
    expect(record.id).toBe("call-1");
    expect(record.command).toBeDefined();
    expect((record.command as string).length).toBe(500);
    expect(record.command).toBe(longCommand.slice(0, 500));
    expect(typeof record.input_bytes).toBe("number");
    expect(record.input_bytes).toBeGreaterThan(0);
  });

  it("tool_call (non-bash) -> only input_bytes, no command field (privacy)", () => {
    const code = "print('this is private python code')";
    const record = sensors.toolCall(SESSION, "ipython", "call-2", { code });
    expectBase(record, "tool_call");
    expect(record.tool).toBe("ipython");
    expect(record.id).toBe("call-2");
    expect(record).not.toHaveProperty("command");
    expect(JSON.stringify(record)).not.toContain(code);
    // byte length of the JSON payload, UTF-8
    expect(record.input_bytes).toBe(
      new TextEncoder().encode(JSON.stringify({ code })).length,
    );
  });

  it("tool_call read -> target hash without raw path", () => {
    const record = sensors.toolCall(SESSION, "read", "call-read", {
      path: "src/second_brain/radar.py",
    });
    expect(record).toHaveProperty("target_sha256");
    expect(JSON.stringify(record)).not.toContain("radar.py");
  });

  it("tool_call (bash, missing command) -> no command field", () => {
    const record = sensors.toolCall(SESSION, "bash", "call-3", { timeout: 30 });
    expect(record).not.toHaveProperty("command");
    expect(record.input_bytes).toBeGreaterThan(0);
  });

  it("tool_result -> tool, id, is_error, output_bytes (precomputed, no content)", () => {
    const content = [{ type: "text", text: "private tool output" }];
    const record = sensors.toolResult(
      SESSION,
      "bash",
      "call-1",
      true,
      sensors.measureContent(content).outputBytes,
    );
    expectBase(record, "tool_result");
    expect(record.tool).toBe("bash");
    expect(record.id).toBe("call-1");
    expect(record.is_error).toBe(true);
    expect(record.output_bytes).toBe(
      new TextEncoder().encode(JSON.stringify(content)).length,
    );
    expect(JSON.stringify(record)).not.toContain("private tool output");
  });

  it("tool_result -> is_error false when not truthy", () => {
    const record = sensors.toolResult(SESSION, "edit", "call-9", undefined, 0);
    expect(record.is_error).toBe(false);
  });

  it("turn_end -> turn, context_usage {used,total,percent}, tool_results count", () => {
    const usage = { tokens: 1234, contextWindow: 100000, percent: 1.2 };
    const record = sensors.turnEnd(SESSION, 1, usage, [{}, {}]);
    expectBase(record, "turn_end");
    expect(record.turn).toBe(1);
    expect(record.context_usage).toEqual({ used: 1234, total: 100000, percent: 1.2 });
    expect(record.tool_results).toBe(2);
  });

  it("turn_end -> context_usage null when runtime reports undefined", () => {
    const record = sensors.turnEnd(SESSION, 0, undefined, []);
    expect(record.context_usage).toBeNull();
  });

  it("turn_end -> tool_results count only, never content", () => {
    const record = sensors.turnEnd(SESSION, 0, null, [{ content: "hush" }]);
    expect(record.tool_results).toBe(1);
    expect(JSON.stringify(record)).not.toContain("hush");
  });

  it("agent_end -> messages count only", () => {
    const record = sensors.agentEnd(SESSION, [{ role: "assistant" }, { role: "user" }]);
    expectBase(record, "agent_end");
    expect(record.messages).toBe(2);
  });

  it("session_before_compact -> branch_entries count", () => {
    const record = sensors.sessionBeforeCompact(SESSION, [1, 2, 3, 4]);
    expectBase(record, "session_before_compact");
    expect(record.branch_entries).toBe(4);
  });

  it("session_compact -> from_extension", () => {
    expect(sensors.sessionCompact(SESSION, true).from_extension).toBe(true);
    expect(sensors.sessionCompact(SESSION, false).from_extension).toBe(false);
    expectBase(sensors.sessionCompact(SESSION, false), "session_compact");
  });

  it("session_shutdown -> reason", () => {
    const record = sensors.sessionShutdown(SESSION, "quit");
    expectBase(record, "session_shutdown");
    expect(record.reason).toBe("quit");
  });

  it("extension_error -> error string truncated to 500 chars", () => {
    const boom = new Error(`boom ${"y".repeat(600)}`);
    const record = sensors.extensionError(SESSION, boom);
    expectBase(record, "extension_error");
    expect((record.error as string).length).toBe(500);
    expect(record.error).toBe(`boom ${"y".repeat(600)}`.slice(0, 500));
  });

  it("extension_error -> stringified non-Error values", () => {
    expect(sensors.extensionError(SESSION, 42).error).toBe("42");
  });
});

describe("sensors: P3-B economics records (schema v3)", () => {
  it("assistant_usage maps exact host usage counters to snake_case (zeros preserved)", () => {
    const record = sensors.assistantUsage(SESSION, "deepseek", "deepseek-v4-flash", {
      input: 100,
      output: 50,
      cacheRead: 200,
      cacheWrite: 0,
      totalTokens: 350,
      cost: { input: 1, output: 2, cacheRead: 3, cacheWrite: 4, total: 10.5 },
    });
    expect(record).not.toBeNull();
    const r = record as unknown as Record<string, unknown>;
    expect(r.v).toBe(3);
    expect(r.kind).toBe("assistant_usage");
    expect(r.provider).toBe("deepseek");
    expect(r.model).toBe("deepseek-v4-flash");
    expect(r.input_tokens).toBe(100);
    expect(r.output_tokens).toBe(50);
    expect(r.cache_read_tokens).toBe(200);
    expect(r.cache_write_tokens).toBe(0); // zero is preserved, not dropped
    expect(r.total_tokens).toBe(350);
    expect(r.cost_total).toBe(10.5);
  });

  it("assistant_usage omits missing counters — never invents values", () => {
    const record = sensors.assistantUsage(SESSION, "p", "m", {
      input: 5,
      output: 3,
      // no cacheRead/cacheWrite/totalTokens/cost from this host
    });
    const r = record as unknown as Record<string, unknown>;
    expect(r.input_tokens).toBe(5);
    expect(r.output_tokens).toBe(3);
    expect(r).not.toHaveProperty("cache_read_tokens");
    expect(r).not.toHaveProperty("cache_write_tokens");
    expect(r).not.toHaveProperty("total_tokens");
    expect(r).not.toHaveProperty("cost_total");
  });

  it("assistant_usage returns null when the host exposes no usage object", () => {
    expect(sensors.assistantUsage(SESSION, "p", "m", undefined)).toBeNull();
    expect(sensors.assistantUsage(SESSION, "p", "m", null)).toBeNull();
  });

  it("assistant_usage carries the host's response identity, and never invents one", () => {
    // The identity is what makes a repeated observation of one billable response recognisable
    // downstream; the host reports it as `responseId` on the assistant message.
    const identified = sensors.assistantUsage(
      SESSION, "p", "m", { input: 1 }, "resp-abc",
    ) as unknown as Record<string, unknown>;
    expect(identified.response_id).toBe("resp-abc");

    const absent = sensors.assistantUsage(SESSION, "p", "m", { input: 1 }) as unknown as
      Record<string, unknown>;
    expect(absent).not.toHaveProperty("response_id");

    // Long identities are digested rather than truncated: two responses whose first 256 units
    // agree must not collapse into one recorded identity, or accounting would drop one of them.
    const longA = "x".repeat(300) + "A";
    const longB = "x".repeat(300) + "B";
    const digestA = sensors.assistantUsage(SESSION, "p", "m", { input: 1 }, longA) as unknown as
      Record<string, unknown>;
    const digestB = sensors.assistantUsage(SESSION, "p", "m", { input: 1 }, longB) as unknown as
      Record<string, unknown>;
    expect(String(digestA.response_id)).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(digestA.response_id).not.toBe(digestB.response_id);
    const short = sensors.assistantUsage(SESSION, "p", "m", { input: 1 }, "resp-short") as unknown as
      Record<string, unknown>;
    expect(short.response_id).toBe("resp-short");

    for (const value of ["", null, undefined, 7, { id: "x" }]) {
      const r = sensors.assistantUsage(SESSION, "p", "m", { input: 1 }, value) as unknown as
        Record<string, unknown>;
      expect(r).not.toHaveProperty("response_id");
    }
  });

  it("provider_request_meta contains keys/counts/sizes/hashes only, never content", () => {
    const payload = {
      model: "deepseek/deepseek-v4-flash",
      messages: [
        { role: "system", content: "SECRET SYSTEM PROMPT" },
        { role: "user", content: "top-secret task text" },
      ],
      tools: [{ type: "function", name: "bash" }],
      stream: true,
    };
    const record = sensors.providerRequestMeta(SESSION, "deepseek", "deepseek-v4-flash", 7, payload);
    expect(record.kind).toBe("provider_request_meta");
    expect(record.v).toBe(3);
    expect(record.request_seq).toBe(7);
    expect(record.request_bytes).toBe(new TextEncoder().encode(JSON.stringify(payload)).length);
    expect(record.message_count).toBe(2);
    expect(record.payload_keys).toEqual(["messages", "model", "stream", "tools"]);
    expect(typeof record.system_prefix_sha).toBe("string");
    expect(record.system_prefix_sha).toMatch(/^[0-9a-f]{64}$/);
    expect(typeof record.tool_surface_sha).toBe("string");
    const text = JSON.stringify(record);
    // privacy: no prompt text, no tool output, no raw tool name
    expect(text).not.toContain("SECRET");
    expect(text).not.toContain("top-secret");
    expect(text).not.toContain("bash");
  });
  it("provider_request_meta proves bounded Lean marker and exact-kernel presence without storing prompt text", () => {
    const marker = "[second-brain-lean-code-kernel]";
    const kernel = "# Runtime Kernel\nLEAN CODE: deliver the smallest correct patch.";
    const candidate = sensors.providerRequestMeta(
      SESSION,
      "openai-codex",
      "gpt-5.6-luna",
      8,
      { input: [{ role: "system", content: `BASE\n\n${marker}\n${kernel}` }] },
      { marker, kernel },
    );
    expect(candidate.lean_kernel_marker_count).toBe(1);
    expect(candidate.lean_kernel_content_count).toBe(1);
    expect(candidate.lean_kernel_sha256).toBe(sensors.sha256Hex(kernel));
    expect(candidate.lean_kernel_chars).toBe(kernel.length);
    expect(candidate.lean_kernel_placement).toBe("$.input[0].content");
    const candidateText = JSON.stringify(candidate);
    expect(candidateText).not.toContain(marker);
    expect(candidateText).not.toContain(kernel);

    const baseline = sensors.providerRequestMeta(
      SESSION,
      "openai-codex",
      "gpt-5.6-luna",
      9,
      { input: [{ role: "system", content: "BASE" }] },
      { marker, kernel },
    );
    expect(baseline.lean_kernel_marker_count).toBe(0);
    expect(baseline.lean_kernel_content_count).toBe(0);
    expect(baseline.lean_kernel_placement).toBe("absent");
  });

  it("provider_request_meta fingerprint is stable across changing user content", () => {
    const base = { messages: [{ role: "system", content: "STABLE" }], tools: [] };
    const r1 = sensors.providerRequestMeta(SESSION, "p", "m", 1, {
      ...base,
      messages: [...base.messages, { role: "user", content: "task A" }],
    });
    const r2 = sensors.providerRequestMeta(SESSION, "p", "m", 2, {
      ...base,
      messages: [...base.messages, { role: "user", content: "task B" }],
    });
    // stable prefix (system message) is the same → same fingerprint
    expect(r1.system_prefix_sha).toBe(r2.system_prefix_sha);
    // but a changed system prompt changes the fingerprint
    const r3 = sensors.providerRequestMeta(SESSION, "p", "m", 3, {
      ...base,
      messages: [{ role: "system", content: "CHANGED" }, { role: "user", content: "task A" }],
    });
    expect(r3.system_prefix_sha).not.toBe(r1.system_prefix_sha);
  });

  it("provider_request_meta omits tool_surface_sha when the payload has no tools", () => {
    const record = sensors.providerRequestMeta(SESSION, "p", "m", 1, { messages: [] });
    expect(record.tool_surface_sha).toBeUndefined();
    expect(typeof record.system_prefix_sha).toBe("string"); // empty prefix still hashable
  });

  it("provider_request_meta handles non-object payloads defensively", () => {
    const record = sensors.providerRequestMeta(SESSION, "p", "m", 1, undefined);
    expect(record.message_count).toBe(0);
    expect(record.payload_keys).toEqual([]);
    expect(record.request_bytes).toBeGreaterThan(0);
  });

  describe("provider_request_meta: RC4 CVM closure repair pointer-marker counts (content-private, counts only)", () => {
    it("zero pointers: no [SECOND_BRAIN_VMEM]/[SECOND_BRAIN_RTD] marker anywhere -> both counts 0 (existing behavior unchanged)", () => {
      const payload = {
        messages: [
          { role: "system", content: "ordinary system prompt" },
          { role: "user", content: "ordinary task text" },
        ],
      };
      const record = sensors.providerRequestMeta(SESSION, "p", "m", 1, payload);
      expect(record.vmem_pointer_count).toBe(0);
      expect(record.rtd_pointer_count).toBe(0);
      // existing fields remain intact and correct alongside the new counters.
      expect(record.request_bytes).toBe(new TextEncoder().encode(JSON.stringify(payload)).length);
      expect(record.message_count).toBe(2);
      expect(record.payload_keys).toEqual(["messages"]);
    });

    it("exactly one VMem pointer -> vmem_pointer_count 1", () => {
      const payload = {
        messages: [
          {
            role: "toolResult",
            toolCallId: "call-1",
            content: [{ type: "text", text: "[SECOND_BRAIN_VMEM]\nkind=TOOL_OBSERVATION\nobj_id=obj-1" }],
          },
          { role: "user", content: "task" },
        ],
      };
      const record = sensors.providerRequestMeta(SESSION, "p", "m", 1, payload);
      expect(record.vmem_pointer_count).toBe(1);
      expect(record.rtd_pointer_count).toBe(0);
    });

    it("multiple VMem pointers (and a distinct RTD marker) -> both counted independently", () => {
      const payload = {
        messages: [
          { role: "custom", customType: "brain.autoinject.packet", content: "[SECOND_BRAIN_VMEM]\nkind=RESEARCH_RESULT" },
          {
            role: "toolResult",
            toolCallId: "call-1",
            content: [{ type: "text", text: "[SECOND_BRAIN_VMEM]\nkind=TOOL_OBSERVATION" }],
          },
          {
            role: "toolResult",
            toolCallId: "call-2",
            content: [{ type: "text", text: "[SECOND_BRAIN_RTD]\ncommand=pytest" }],
          },
        ],
      };
      const record = sensors.providerRequestMeta(SESSION, "p", "m", 1, payload);
      expect(record.vmem_pointer_count).toBe(2);
      expect(record.rtd_pointer_count).toBe(1);
    });

    it("malformed/unusual payload shape (messages not an array; a non-string content field) -> counter never throws, existing fields stay intact and correct", () => {
      const payload = {
        messages: "not-an-array-at-all",
        tools: [{ type: "function", name: "bash" }],
        extra: { nested: { deeply: [1, 2, { content: 42 }] } },
      };
      let threw = false;
      let record: ReturnType<typeof sensors.providerRequestMeta> | undefined;
      try {
        record = sensors.providerRequestMeta(SESSION, "p", "m", 5, payload);
      } catch {
        threw = true;
      }
      expect(threw).toBe(false);
      expect(record).toBeDefined();
      expect(record!.vmem_pointer_count).toBe(0);
      expect(record!.rtd_pointer_count).toBe(0);
      expect(record!.message_count).toBe(0); // messages is not an array -> defensive 0, unchanged existing behavior
      expect(record!.request_bytes).toBe(new TextEncoder().encode(JSON.stringify(payload)).length);
      expect(record!.payload_keys).toEqual(["extra", "messages", "tools"]);
    });

    it("a real [SECOND_BRAIN_VMEM] marker embedded deep in a non-string field never breaks counting or leaks into any other field", () => {
      const payload = {
        messages: [],
        weird: { a: { b: { c: "[SECOND_BRAIN_VMEM]\nkind=X" } } },
      };
      const record = sensors.providerRequestMeta(SESSION, "p", "m", 1, payload);
      expect(record.vmem_pointer_count).toBe(1);
      const text = JSON.stringify(record);
      expect(text).not.toContain("SECOND_BRAIN_VMEM"); // the record itself never stores the marker text
    });
  });

  it("provider_response_meta keeps status and allowlisted cache/rate-limit headers only", () => {
    const record = sensors.providerResponseMeta(SESSION, "deepseek", "m", 200, {
      "x-ratelimit-remaining": "42",
      "x-cache": "HIT",
      "content-type": "application/json",
      "x-request-id": "req-123",
      authorization: "Bearer sk-secret-value",
    });
    expect(record.kind).toBe("provider_response_meta");
    expect(record.v).toBe(3);
    expect(record.status).toBe(200);
    expect(record.headers).toHaveLength(2);
    expect(record.headers?.[0]?.key).toBe("x-ratelimit-remaining");
    expect(record.headers?.[0]?.value_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(record.headers?.[1]?.key).toBe("x-cache");
    const text = JSON.stringify(record);
    // header VALUES are hashed, never raw; unrelated headers never stored
    expect(text).not.toContain("HIT");
    expect(text).not.toContain('"42"'); // raw value would appear quoted
    expect(text).not.toContain("application/json");
    expect(text).not.toContain("req-123");
    expect(text).not.toContain("sk-secret");
  });

  it("provider_response_meta omits status/headers when absent or disallowed", () => {
    const r1 = sensors.providerResponseMeta(SESSION, "p", "m", undefined, {
      "x-arbitrary": "v",
    });
    expect(r1.status).toBeUndefined();
    expect(r1.headers).toBeUndefined();
    const r2 = sensors.providerResponseMeta(SESSION, "p", "m", "ok", {});
    expect(r2.status).toBeUndefined();
  });

  it("splitProviderModel splits provider/id and is null-safe", () => {
    expect(sensors.splitProviderModel("deepseek/deepseek-v4-flash")).toEqual({
      provider: "deepseek",
      model: "deepseek-v4-flash",
    });
    expect(sensors.splitProviderModel("bare-model")).toEqual({ provider: null, model: "bare-model" });
    expect(sensors.splitProviderModel(null)).toEqual({ provider: null, model: null });
  });
});

describe("sensors: helpers", () => {
  it("modelToString handles string, object, and garbage", () => {
    expect(sensors.modelToString("deepseek/deepseek-v4-flash")).toBe("deepseek/deepseek-v4-flash");
    expect(sensors.modelToString({ id: "m", provider: "p" })).toBe("p/m");
    expect(sensors.modelToString({ id: "m" })).toBe("m");
    expect(sensors.modelToString(null)).toBeNull();
    expect(sensors.modelToString(undefined)).toBeNull();
    expect(sensors.modelToString(42)).toBeNull();
  });

  it("contextUsageToRecord maps runtime shape to schema shape", () => {
    expect(
      sensors.contextUsageToRecord({ tokens: 5, contextWindow: 100, percent: 5 }),
    ).toEqual({ used: 5, total: 100, percent: 5 });
    expect(sensors.contextUsageToRecord(null)).toBeNull();
    expect(sensors.contextUsageToRecord(undefined)).toBeNull();
  });

  it("byteLength measures UTF-8 bytes", () => {
    expect(sensors.byteLength("abc")).toBe(3);
    expect(sensors.byteLength("héllo")).toBe(6); // é is 2 bytes
    expect(sensors.byteLength({ a: 1 })).toBe(new TextEncoder().encode('{"a":1}').length);
  });

  it("truncate keeps short strings and clips long ones", () => {
    expect(sensors.truncate("short", 500)).toBe("short");
    expect(sensors.truncate("1234567890", 4)).toBe("1234");
  });
});


describe("redactSensitiveCommand (SEC-08)", () => {
  const SECRET = "sk-super-secret-value-1234567890";

  it("redacts Authorization Bearer headers (case-insensitive)", () => {
    expect(sensors.redactSensitiveCommand(`curl -H "Authorization: Bearer ${SECRET}" url`)).toBe(
      `curl -H "[REDACTED]" url`,
    );
    expect(
      sensors.redactSensitiveCommand(`curl -H 'authorization: bearer ${SECRET}' url`),
    ).toBe(`curl -H "[REDACTED]" url`);
  });

  it("redacts unquoted Authorization headers", () => {
    expect(sensors.redactSensitiveCommand(`curl -H Authorization: Bearer ${SECRET} url`)).not.toContain(
      SECRET,
    );
    expect(sensors.redactSensitiveCommand(`curl -H Authorization: Bearer ${SECRET} url`)).toContain(
      "[REDACTED]",
    );
  });

  it("redacts bare Bearer tokens", () => {
    const redacted = sensors.redactSensitiveCommand(`echo Bearer ${SECRET}`);
    expect(redacted).toBe(`echo Bearer [REDACTED]`);
  });

  it("redacts token/password assignments", () => {
    expect(sensors.redactSensitiveCommand(`curl --data token=${SECRET}`)).not.toContain(SECRET);
    expect(sensors.redactSensitiveCommand(`curl --data token=${SECRET}`)).toContain("[REDACTED]");
    expect(sensors.redactSensitiveCommand(`api_key=${SECRET} run.py`)).not.toContain(SECRET);
    expect(sensors.redactSensitiveCommand(`api_key=${SECRET} run.py`)).toContain("[REDACTED]");
    expect(sensors.redactSensitiveCommand(`password=${SECRET}`)).not.toContain(SECRET);
    expect(sensors.redactSensitiveCommand(`secret = ${SECRET}`)).not.toContain(SECRET);
  });

  it("redacts CLI flags with separate and inline values", () => {
    expect(sensors.redactSensitiveCommand(`python run.py --token ${SECRET}`)).toBe(
      `python run.py --token [REDACTED]`,
    );
    expect(sensors.redactSensitiveCommand(`python run.py --token=${SECRET}`)).toBe(
      `python run.py --token=[REDACTED]`,
    );
    expect(sensors.redactSensitiveCommand(`python run.py --password ${SECRET}`)).not.toContain(SECRET);
    expect(sensors.redactSensitiveCommand(`python run.py --api-key ${SECRET}`)).not.toContain(SECRET);
  });

  it("redacts vendor environment variables", () => {
    const cmd = `OPENAI_API_KEY=${SECRET} ANTHROPIC_API_KEY=${SECRET} GITHUB_TOKEN=${SECRET} GH_TOKEN=${SECRET} DEEPSEEK_API_KEY=${SECRET} XAI_API_KEY=${SECRET} run.py`;
    const redacted = sensors.redactSensitiveCommand(cmd);
    expect(redacted).not.toContain(SECRET);
    expect(redacted.match(/\[REDACTED\]/g)).toHaveLength(6);
  });

  it("redacts AWS secret access keys", () => {
    const redacted = sensors.redactSensitiveCommand(
      `AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE aws s3 ls`,
    );
    expect(redacted).not.toContain("AKIAIOSFODNN7EXAMPLE");
    expect(redacted).toContain("[REDACTED]");
  });

  it("redacts credential-shaped tokens and private keys", () => {
    const cmd = `echo ${"sk-".concat("a".repeat(20))} ${"ghp_".concat("b".repeat(25))}`;
    const redacted = sensors.redactSensitiveCommand(cmd);
    expect(redacted).not.toContain("sk-aaaa");
    expect(redacted).not.toContain("ghp_bbbb");
    const key = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----";
    expect(sensors.redactSensitiveCommand(`cat <<EOF\n${key}\nEOF`)).not.toContain("BEGIN RSA");
  });

  it("preserves non-secret commands materially unchanged", () => {
    const cmd = "python run.py --project telemetry-test --mode fast";
    expect(sensors.redactSensitiveCommand(cmd)).toBe(cmd);
    const header = `curl -H "Content-Type: application/json" -d '{"a":1}' url`;
    expect(sensors.redactSensitiveCommand(header)).toBe(header);
  });

  it("redacts before truncation, including near the boundary", () => {
    const nearBoundary = `${"x".repeat(485)} --token=${SECRET}`;
    const record = sensors.toolCall("s", "bash", "c1", { command: nearBoundary });
    expect((record.command as string).length).toBeLessThanOrEqual(500);
    expect(JSON.stringify(record)).not.toContain(SECRET);
    const secretAtStart = `--password=${SECRET} ${"y".repeat(600)}`;
    const record2 = sensors.toolCall("s", "bash", "c2", { command: secretAtStart });
    expect(JSON.stringify(record2)).not.toContain(SECRET);
    expect(JSON.stringify(record2)).toContain("[REDACTED]");
  });
});

describe("sensors: orchestrator_policy_violation (bounded fields, report-only)", () => {
  it("maps enumerated violation code, model, detector, blocked flag", () => {
    const record = sensors.orchestratorPolicyViolation(
      SESSION,
      "direct_execution",
      { id: "gpt-5.6-sol", provider: "openai" },
      "manual",
      false,
    );
    expectBase(record, "orchestrator_policy_violation");
    expect(record.violation).toBe("direct_execution");
    expect(record.model).toBe("openai/gpt-5.6-sol");
    expect(record.detected_by).toBe("manual");
    expect(record.blocked).toBe(false);
  });

  it("blocks flag true when blocked===true, model null when model missing", () => {
    const record = sensors.orchestratorPolicyViolation(SESSION, "wrong_tier", undefined, "telemetry_audit", true);
    expect(record.model).toBeNull();
    expect(record.blocked).toBe(true);
  });

  it("rejects free text and unknown codes: coerces to bounded 'unknown', never stores payload", () => {
    const record = sensors.orchestratorPolicyViolation(
      SESSION,
      "ran: rm -rf --payload SECRET_VALUE_123",
      { id: "gpt-5.6-sol" },
      "human wrote a long note",
      false,
    );
    expect(record.violation).toBe("unknown");
    expect(record.detected_by).toBe("unknown");
    expect(JSON.stringify(record)).not.toContain("SECRET_VALUE_123");
    expect(JSON.stringify(record)).not.toContain("rm -rf");
  });
});

describe("measureContent: one serialization, both metrics (Phase 3)", () => {
  it("string content: serializedChars = JSON char length, outputBytes = RAW string UTF-8 bytes", () => {
    const m = sensors.measureContent("hello");
    expect(m.serializedChars).toBe(7); // '"hello"' = 7 chars
    expect(m.outputBytes).toBe(5); // raw string bytes, no quotes
  });

  it("Unicode/escaping divergence: chars vs bytes differ, both legacy-correct", () => {
    const m = sensors.measureContent("héllo");
    expect(m.serializedChars).toBe(7); // '"héllo"' (é is 1 char)
    expect(m.outputBytes).toBe(6); // é is 2 UTF-8 bytes
    const escaped = sensors.measureContent('a"b');
    expect(escaped.serializedChars).toBe(6); // '"a\\"b"' — quote escaped
    expect(escaped.outputBytes).toBe(3); // raw bytes a " b
  });

  it("object content: one serialization feeds both metrics (UTF-8 bytes of the JSON)", () => {
    const content = { a: 1, t: "héllo" };
    const serialized = JSON.stringify(content);
    const m = sensors.measureContent(content);
    expect(m.serializedChars).toBe(serialized.length);
    expect(m.outputBytes).toBe(new TextEncoder().encode(serialized).length);
  });

  it("undefined: JSON.stringify returns undefined (no throw) -> serializedChars 0, outputBytes matches legacy byteLength (Node-verified: encode(undefined) defaults to empty string, 0 bytes)", () => {
    const m = sensors.measureContent(undefined);
    expect(m.serializedChars).toBe(0);
    expect(m.outputBytes).toBe(0);
    expect(m.outputBytes).toBe(sensors.byteLength(undefined));
    expect(m.outputBytes).toBe(new TextEncoder().encode(undefined).length); // Node: 0
  });

  it("function/symbol content: JSON.stringify returns undefined -> serializedChars 0, outputBytes matches legacy byteLength (Node-verified: 0 bytes)", () => {
    const fn = () => 42;
    const sym = Symbol("s");
    expect(sensors.measureContent(fn).serializedChars).toBe(0);
    expect(sensors.measureContent(fn).outputBytes).toBe(0);
    expect(sensors.measureContent(fn).outputBytes).toBe(sensors.byteLength(fn));
    expect(sensors.measureContent(sym).serializedChars).toBe(0);
    expect(sensors.measureContent(sym).outputBytes).toBe(0);
    expect(sensors.measureContent(sym).outputBytes).toBe(sensors.byteLength(sym));
  });

  it("circular/bigint content: throws -> serializedChars 0, outputBytes = legacy '<unserializable>' fallback (Node-verified: 16 bytes)", () => {
    const circular: Record<string, unknown> = { a: 1 };
    circular.self = circular;
    const m = sensors.measureContent(circular);
    expect(m.serializedChars).toBe(0);
    expect(m.outputBytes).toBe(16); // '<unserializable>'
    expect(m.outputBytes).toBe(sensors.byteLength(circular));
    const big = sensors.measureContent(1n);
    expect(big.serializedChars).toBe(0);
    expect(big.outputBytes).toBe(16);
    expect(big.outputBytes).toBe(sensors.byteLength(1n));
  });
});

describe("measureContent modes (Phase 3 correction)", () => {
  it("includeSerializedChars=false on a primitive string: ZERO JSON.stringify, raw bytes only, serializedChars 0", () => {
    const m = sensors.measureContent("héllo", false);
    expect(m.serializedChars).toBe(0); // RTD char metric not measured
    expect(m.outputBytes).toBe(6); // raw UTF-8 bytes, legacy byteLength parity
  });

  it("includeSerializedChars=false on an object: single telemetry serialization, serializedChars 0", () => {
    const content = { a: 1, t: "héllo" };
    const m = sensors.measureContent(content, false);
    expect(m.serializedChars).toBe(0);
    expect(m.outputBytes).toBe(new TextEncoder().encode(JSON.stringify(content)).length); // base telemetry parity
  });

  it("includeSerializedChars=false on unserializable/undefined: serializedChars 0, legacy byteLength fallback", () => {
    const circular: Record<string, unknown> = { a: 1 };
    circular.self = circular;
    expect(sensors.measureContent(circular, false)).toEqual({ serializedChars: 0, outputBytes: 16 });
    expect(sensors.measureContent(undefined, false)).toEqual({ serializedChars: 0, outputBytes: 0 });
  });

  it("includeSerializedChars=true (default) still measures both metrics from one serialization", () => {
    const m = sensors.measureContent("hello");
    expect(m).toEqual({ serializedChars: 7, outputBytes: 5 });
  });

  it("no chain-of-thought / reasoning field ever reaches a telemetry record", () => {
    // Structural guard: model reasoning must never be persisted. Every record
    // builder that touches model-facing data is exercised with content that
    // deliberately contains reasoning-shaped text, and no emitted key (at any
    // nesting depth) may name a reasoning/thinking field.
    // NB: `reason` alone is a legitimate lifecycle field (session_start.reason,
    // session_shutdown.reason); the forbidden shapes are reasoning-content fields.
    const forbiddenKey = /think|reasoning|chain[_-]?of[_-]?thought|\bcot\b|internal[_-]?monologue|scratchpad/i;

    const records: unknown[] = [
      sensors.sessionStart(SESSION, "startup", "/cwd", { id: "m", provider: "p" }),
      sensors.beforeAgentStart(SESSION, "let me think step by step about this", "driver", true),
      sensors.turnStart(SESSION, 1),
      sensors.context(SESSION, [{ role: "assistant", content: "my reasoning was ..." }]),
      sensors.toolCall(SESSION, "bash", "call-1", { command: "echo hi" }),
      sensors.toolResult(SESSION, "bash", "call-1", false, 42),
      sensors.turnEnd(SESSION, 1, { tokens: 10, contextWindow: 100, percent: 10 }, [1, 2]),
      sensors.agentEnd(SESSION, [1, 2, 3]),
      sensors.assistantUsage(SESSION, "p", "m", {
        input: 1,
        output: 2,
        cacheRead: 3,
        cacheWrite: 4,
        totalTokens: 10,
      }),
    ];

    const walk = (value: unknown, path: string): void => {
      if (value === null || typeof value !== "object") return;
      for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
        expect(key, `forbidden reasoning-shaped key at ${path}.${key}`).not.toMatch(forbiddenKey);
        walk(child, `${path}.${key}`);
      }
    };

    for (const record of records) {
      expect(record).not.toBeNull();
      walk(record, "record");
    }

    // The assistant's own text must never be carried verbatim: the context
    // record keeps a count, not the message bodies.
    const ctx = JSON.stringify(sensors.context(SESSION, [{ content: "my reasoning was ..." }]));
    expect(ctx).not.toContain("my reasoning was");
  });
});

describe("Part D: vmemFaultIn (privacy-safe fault-in telemetry)", () => {
  it("records kind, resolution, and ok as a bool only — never obj_id/content", () => {
    const record = sensors.vmemFaultIn(SESSION, "TOOL_OBSERVATION", "artifact", true);
    expectBase(record, "vmem_fault_in");
    expect(record.obj_kind).toBe("TOOL_OBSERVATION");
    expect(record.resolution).toBe("artifact");
    expect(record.ok).toBe(true);
  });

  it("coerces non-token obj_kind/resolution to null, non-true ok to false", () => {
    const record = sensors.vmemFaultIn(SESSION, "this is not a short enum-like token at all", 42, "yes");
    expect(record.obj_kind).toBeNull();
    expect(record.resolution).toBeNull();
    expect(record.ok).toBe(false);
  });

  it("only emits the four documented fields (v/ts/kind/session inherited via base + obj_kind/resolution/ok) — no extra surface for accidental content leakage", () => {
    const record = sensors.vmemFaultIn(SESSION, "RESEARCH_RESULT", "memory", true);
    expect(Object.keys(record).sort()).toEqual(["kind", "obj_kind", "ok", "resolution", "session", "ts", "v"]);
  });
});

describe("Part B/E: contextPaging (privacy-safe paging-count telemetry)", () => {
  it("records paged_count only — a count, never which elements or content", () => {
    const record = sensors.contextPaging(SESSION, 2);
    expectBase(record, "context_paging");
    expect(record.paged_count).toBe(2);
  });

  it("coerces a non-number pagedCount to 0", () => {
    expect(sensors.contextPaging(SESSION, "two" as unknown as number).paged_count).toBe(0);
    expect(sensors.contextPaging(SESSION, undefined as unknown as number).paged_count).toBe(0);
  });

  it("omitting details (existing call shape) leaves every Defect B additive field null", () => {
    const record = sensors.contextPaging(SESSION, 1);
    expect(record.candidate_count).toBeNull();
    expect(record.eligible_count).toBeNull();
    expect(record.pressure_estimated_tokens).toBeNull();
    expect(record.resident_budget).toBeNull();
    expect(record.requested_page_count).toBeNull();
    expect(record.claimed_page_count).toBeNull();
    expect(record.newly_claimed_count).toBeNull();
    expect(record.reprojected_page_count).toBeNull();
    expect(record.estimated_tokens_before).toBeNull();
    expect(record.estimated_tokens_after).toBeNull();
    expect(record.estimated_tokens_removed).toBeNull();
    expect(record.object_kinds).toBeNull();
    expect(record.state_before).toBeNull();
    expect(record.state_after).toBeNull();
  });

  it("Defect B: populates every additive field from details, computes estimated_tokens_removed as before-after", () => {
    const record = sensors.contextPaging(SESSION, 2, {
      candidateCount: 3,
      eligibleCount: 2,
      pressureEstimatedTokens: 150,
      residentBudget: 100,
      requestedPageCount: 2,
      claimedPageCount: 2,
      estimatedTokensBefore: 120,
      estimatedTokensAfter: 40,
      objectKinds: ["RESEARCH_RESULT", "TOOL_OBSERVATION"],
      stateBefore: ["RESIDENT", "FAULTED_IN"],
      stateAfter: ["EVICTED"],
    });
    expect(record.candidate_count).toBe(3);
    expect(record.eligible_count).toBe(2);
    expect(record.pressure_estimated_tokens).toBe(150);
    expect(record.resident_budget).toBe(100);
    expect(record.requested_page_count).toBe(2);
    expect(record.claimed_page_count).toBe(2);
    expect(record.estimated_tokens_before).toBe(120);
    expect(record.estimated_tokens_after).toBe(40);
    expect(record.estimated_tokens_removed).toBe(80);
    expect(record.object_kinds).toEqual(["RESEARCH_RESULT", "TOOL_OBSERVATION"]);
    expect(record.state_before).toEqual(["RESIDENT", "FAULTED_IN"]);
    expect(record.state_after).toEqual(["EVICTED"]);
  });

  it("RC4 CVM closure repair (Repair B): populates newly_claimed_count/reprojected_page_count additively; paged_count keeps meaning 'total replacements' covering both paths", () => {
    const record = sensors.contextPaging(SESSION, 2, {
      candidateCount: 2,
      eligibleCount: 2,
      requestedPageCount: 1, // Path A ONLY — the reprojected candidate was never "requested" to claim
      claimedPageCount: 1,
      newlyClaimedCount: 1,
      reprojectedPageCount: 1,
      objectKinds: ["RESEARCH_RESULT"],
      stateBefore: ["RESIDENT", "EVICTED"],
      stateAfter: ["EVICTED", "EVICTED_REPROJECTED"],
    });
    expect(record.paged_count).toBe(2);
    expect(record.newly_claimed_count).toBe(1);
    expect(record.reprojected_page_count).toBe(1);
    expect(record.requested_page_count).toBe(1);
    // EVICTED_REPROJECTED is a well-formed recognized token (letters/underscore
    // only, <=24 chars) -- it survives the SAME allowlist filter as every
    // other kind/state label, never dropped as free text.
    expect(record.state_after).toEqual(["EVICTED", "EVICTED_REPROJECTED"]);
  });

  it("estimated_tokens_removed never goes negative (clamped at 0)", () => {
    const record = sensors.contextPaging(SESSION, 1, {
      estimatedTokensBefore: 10,
      estimatedTokensAfter: 50, // pathological but must not produce a negative "removed"
    });
    expect(record.estimated_tokens_removed).toBe(0);
  });

  it("object_kinds/state_before/state_after are recognized tokens only — an unrecognized token is dropped, never free text", () => {
    const record = sensors.contextPaging(SESSION, 1, {
      objectKinds: ["RESEARCH_RESULT", "not a token; has spaces"],
      stateBefore: ["RESIDENT"],
      stateAfter: ["EVICTED"],
    });
    expect(record.object_kinds).toEqual(["RESEARCH_RESULT"]);
  });

  it("no obj_id/delivery_id/tool_call_id/content ever appears on the record surface", () => {
    const record = sensors.contextPaging(SESSION, 1, {
      candidateCount: 1,
      objectKinds: ["RESEARCH_RESULT"],
    }) as unknown as Record<string, unknown>;
    const serialized = JSON.stringify(record);
    expect(serialized).not.toContain("obj-");
    expect(serialized).not.toContain("del-");
  });
});

describe("P4 sensors: heartbeatPulse/bottleneckFingerprint/optimizationEvent (Task 7)", () => {
  it("heartbeatPulse mirrors a healthy shadow pulse and forces model_tokens_used to zero", () => {
    const record = sensors.heartbeatPulse(SESSION, {
      mode: "shadow",
      event: "session_start",
      due: true,
      ran: true,
      healthy: true,
      db_ok: true,
      cache_pruned_count: 3,
      git_dirty: false,
      issue_codes: ["cache_stale"],
      latency_ms: 12,
      model_tokens_used: 999, // must never survive: heartbeat is zero-token by design
    });
    expectBase(record, "heartbeat_pulse");
    expect(record.mode).toBe("shadow");
    expect(record.event).toBe("session_start");
    expect(record.due).toBe(true);
    expect(record.cache_pruned_count).toBe(3);
    expect(record.issue_codes).toEqual(["cache_stale"]);
    expect(record.latency_ms).toBe(12);
    expect(record.model_tokens_used).toBe(0);
  });

  it("heartbeatPulse falls back to bounded defaults for missing/malformed input", () => {
    const record = sensors.heartbeatPulse(SESSION, undefined);
    expectBase(record, "heartbeat_pulse");
    expect(record.mode).toBe("shadow");
    expect(record.event).toBe("");
    expect(record.due).toBe(false);
    expect(record.ran).toBe(false);
    expect(record.cache_pruned_count).toBe(0);
    expect(record.issue_codes).toEqual([]);
  });

  it("heartbeatPulse rejects an unrecognized mode and clamps out-of-range counts", () => {
    const record = sensors.heartbeatPulse(SESSION, {
      mode: "turbo",
      cache_pruned_count: 9_999_999,
      latency_ms: -5,
      issue_codes: Array.from({ length: 40 }, (_, i) => `code-${i}`),
    });
    expect(record.mode).toBe("shadow");
    expect(record.cache_pruned_count).toBe(1_000_000);
    expect(record.latency_ms).toBe(0);
    expect(record.issue_codes).toHaveLength(32);
  });

  it("bottleneckFingerprint mirrors bounded fields only — never description/mitigation/metadata/evidence_refs", () => {
    const record = sensors.bottleneckFingerprint(SESSION, {
      fingerprint_id: "fp-1",
      category: "PROMPT_BLOAT",
      scope_id: "project-a",
      occurrence_count: 4,
      impact_score: 7.5,
      evidence_count: 2,
      evidence_hash: "a".repeat(64),
      description: "SECRET: repeated read of large file",
      mitigation: "SECRET: use grep instead",
      metadata: { note: "SECRET" },
      evidence_refs: [{ telemetry_ref: "SECRET:1" }],
    });
    expectBase(record, "bottleneck_fingerprint");
    expect(record.fingerprint_id).toBe("fp-1");
    expect(record.category).toBe("PROMPT_BLOAT");
    expect(record.occurrence_count).toBe(4);
    expect(record.impact_score).toBe(7.5);
    expect(record.evidence_hash).toBe("a".repeat(64));
    const serialized = JSON.stringify(record);
    expect(serialized).not.toContain("SECRET");
  });

  it("bottleneckFingerprint rejects a malformed evidence_hash and unknown category", () => {
    const record = sensors.bottleneckFingerprint(SESSION, {
      fingerprint_id: "fp-2",
      category: "NOT_A_REAL_CATEGORY",
      evidence_hash: "not-hex",
    });
    expect(record.category).toBe("unknown");
    expect(record.evidence_hash).toBeNull();
  });

  it("optimizationEvent mirrors bounded tokens/hashes for a recognized kind", () => {
    const record = sensors.optimizationEvent(SESSION, "optimization_activation", {
      proposal_id: "proposal-abc123",
      status: "activated",
      approval_state: "approved",
      rollback_state: "clear",
      intervention_hash: "b".repeat(64),
      evidence_hash: "c".repeat(64),
    });
    expect(record).not.toBeNull();
    expectBase(record!, "optimization_activation");
    expect(record!.proposal_id).toBe("proposal-abc123");
    expect(record!.status).toBe("activated");
    expect(record!.intervention_hash).toBe("b".repeat(64));
  });

  it("optimizationEvent returns null for an unrecognized kind or missing proposal_id/status", () => {
    expect(
      sensors.optimizationEvent(SESSION, "not_a_kind" as sensors.OptimizationEventKind, {
        proposal_id: "p",
        status: "s",
      }),
    ).toBeNull();
    expect(
      sensors.optimizationEvent(SESSION, "optimization_proposal", {
        proposal_id: "",
        status: "proposed",
      }),
    ).toBeNull();
  });
});
