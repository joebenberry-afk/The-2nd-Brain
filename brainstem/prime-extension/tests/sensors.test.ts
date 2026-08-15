import { describe, expect, it } from "vitest";
import * as sensors from "../src/sensors";

const SESSION = "test-session-123";

/** All records must carry the common schema fields. */
function expectBase(record: object, kind: string): void {
  const r = record as Record<string, unknown>;
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
});
