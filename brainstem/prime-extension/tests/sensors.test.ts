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

  it("tool_result -> tool, id, is_error, output_bytes (no content)", () => {
    const content = [{ type: "text", text: "private tool output" }];
    const record = sensors.toolResult(SESSION, "bash", "call-1", true, content);
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
    const record = sensors.toolResult(SESSION, "edit", "call-9", undefined, []);
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
