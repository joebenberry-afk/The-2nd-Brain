/**
 * P3 provider-capability probe — installed Prime Agent v0.7.2.
 *
 * Proves (live) that these hooks fire and what they expose:
 *   resources_discover, context, before_provider_request,
 *   after_provider_response, message_end (usage), tool_result (mutation).
 *
 * PRIVACY RULES: hashes/counts/keys ONLY. Never logs prompt text, secrets,
 * or tool output. tool_result mutation appends a hash-only marker text block.
 *
 * NOT installed in ~/.prime/agent/extensions/ — the live run is
 * parent-coordinated (see README.md). This file is repo-only and removable.
 */
import { createHash } from "node:crypto";
import { appendFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const sha = (v: unknown): string =>
  createHash("sha256").update(JSON.stringify(v) ?? "null").digest("hex").slice(0, 16);

let logPath: string | null = null;
function log(entry: Record<string, unknown>): void {
  try {
    if (!logPath) {
      logPath = fileURLToPath(new URL("./probe.log.jsonl", import.meta.url));
    }
    appendFileSync(logPath, JSON.stringify({ t: Date.now(), ...entry }) + "\n");
  } catch {
    /* fail open: probing must never disturb the session */
  }
}

export default function (pi: any): void {
  let rdCount = 0;
  let ctxCount = 0;
  let bprCount = 0;
  let aprCount = 0;
  let meCount = 0;
  let trCount = 0;

  pi.on("resources_discover", (event: any) => {
    rdCount++;
    log({ event: "resources_discover", count: rdCount, reason: event?.reason });
  });

  pi.on("context", (event: any) => {
    ctxCount++;
    const msgs = Array.isArray(event?.messages) ? event.messages : [];
    const roles: Record<string, number> = {};
    for (const m of msgs) {
      const role = m?.role ?? "?";
      roles[role] = (roles[role] ?? 0) + 1;
    }
    log({ event: "context", count: ctxCount, messageCount: msgs.length, roles });
    return undefined;
  });

  pi.on("before_provider_request", (event: any) => {
    bprCount++;
    const payload = event?.payload ?? {};
    const keys = payload && typeof payload === "object" ? Object.keys(payload) : [];
    log({
      event: "before_provider_request",
      count: bprCount,
      payloadKeys: keys,
      payloadSha: sha(payload),
      messageCount: Array.isArray(payload.messages) ? payload.messages.length : undefined,
    });
    return undefined;
  });

  pi.on("after_provider_response", (event: any) => {
    aprCount++;
    const headers = (event?.headers ?? {}) as Record<string, string>;
    log({
      event: "after_provider_response",
      count: aprCount,
      status: event?.status,
      headerKeys: Object.keys(headers).sort(),
      headerValuesSha: sha(Object.entries(headers).sort()),
    });
  });

  pi.on("message_end", (event: any) => {
    meCount++;
    const m = event?.message;
    const entry: Record<string, unknown> = { event: "message_end", count: meCount, role: m?.role };
    if (m?.role === "assistant") {
      entry.model = m.model;
      entry.usage = m.usage; // numbers only: input/output/cacheRead/cacheWrite/totalTokens/cost
      entry.firstTextSha = sha(m.content?.find?.((c: any) => c?.type === "text")?.text);
    }
    log(entry);
    return undefined;
  });

  pi.on("tool_result", (event: any) => {
    trCount++;
    const contentSha = sha(event?.content);
    log({
      event: "tool_result",
      count: trCount,
      toolName: event?.toolName,
      isError: event?.isError,
      contentSha,
    });
    // Mutation proof: append a hash-only marker to the result content. If the
    // patch flows back into model context, the model can quote the marker in
    // its next message (verify by asking it — the marker is a hash, not content).
    return { content: [...(event?.content ?? []), { type: "text", text: `probe-marker:${contentSha}` }] };
  });
}
