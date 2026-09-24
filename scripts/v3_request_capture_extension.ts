/**
 * V3 provider-request capture extension (S2 request-neutrality evidence).
 *
 * Loaded with `-e` in EVERY arm of `scripts/v3_matched_arms.py`, always AFTER
 * the arm's own extension, and never returns a value, so it observes exactly
 * the payload the host is about to send:
 *
 *   - OMP loads explicit `-e` paths in the order given and de-duplicates by
 *     absolute path, first position wins (`docs` in the host repo:
 *     `extension-loading.md` "Load order and precedence");
 *   - `ExtensionRunner.emitBeforeProviderRequest` walks `this.extensions` in
 *     that same load order and threads `currentPayload` through every
 *     handler, replacing it only when a handler returns a value.
 *
 * Therefore a capture handler registered last sees the payload as every earlier
 * extension - including Second Brain - left it. `V3_CAPTURE_ORDER_MARKER`
 * exists to prove that empirically: when set, this handler rewrites the marker
 * key and returns the payload, and the harness' order probe asserts that a
 * later capture handler observed the replacement (see the S2 harness note).
 *
 * Output (one file per provider request, plus a JSONL index):
 *   $V3_CAPTURE_DIR/provider-request-<seq>.json   raw payload, JSON
 *   $V3_CAPTURE_DIR/index.jsonl                   one line of metadata per request
 *
 * The extension is measurement-only: no spawn, no network, no session writes.
 * It fail-opens (no file I/O) when `V3_CAPTURE_DIR` is unset, and captures a
 * bounded truncated body plus a full-length digest when a payload exceeds
 * `V3_CAPTURE_MAX_BYTES`.
 */

import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";

interface CaptureHost {
  on(
    event: "before_provider_request",
    handler: (event: { type: "before_provider_request"; payload: unknown }) => unknown,
  ): void;
}

const DEFAULT_MAX_BYTES = 16 * 1024 * 1024;

function envInt(name: string, fallback: number): number {
  const raw = process.env[name];
  const value = raw === undefined || raw === "" ? Number.NaN : Number(raw);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}

export default function requestCapture(pi: CaptureHost): void {
  const dir = process.env["V3_CAPTURE_DIR"] ?? "";
  if (dir === "") return;
  mkdirSync(dir, { recursive: true });

  const label = process.env["V3_CAPTURE_LABEL"] ?? "";
  const maxBytes = envInt("V3_CAPTURE_MAX_BYTES", DEFAULT_MAX_BYTES);
  const orderMarker = process.env["V3_CAPTURE_ORDER_MARKER"] ?? "";
  const index = join(dir, "index.jsonl");
  let seq = 0;

  pi.on("before_provider_request", (event) => {
    seq += 1;
    let payload = event.payload;
    let marked = false;
    if (orderMarker !== "") {
      const obj =
        payload !== null && typeof payload === "object"
          ? (payload as Record<string, unknown>)
          : {};
      obj["v3_capture_order_marker"] = orderMarker;
      payload = obj;
      marked = true;
    }
    let text = "";
    let stringifyError: string | null = null;
    try {
      text = JSON.stringify(payload) ?? "";
    } catch (error) {
      stringifyError = error instanceof Error ? error.message : String(error);
    }
    const bytes = Buffer.byteLength(text, "utf8");
    const digest = createHash("sha256").update(text, "utf8").digest("hex");
    let body = text;
    let truncated = false;
    if (bytes > maxBytes) {
      truncated = true;
      body =
        text.slice(0, maxBytes) +
        `\n/* V3 capture: truncated at ${maxBytes} of ${bytes} bytes */`;
    }
    const file = `provider-request-${String(seq).padStart(3, "0")}.json`;
    writeFileSync(join(dir, file), body, "utf8");
    appendFileSync(
      index,
      JSON.stringify({
        seq,
        file,
        label,
        pid: process.pid,
        timestamp: new Date().toISOString(),
        payload_sha256: digest,
        payload_bytes: bytes,
        truncated,
        stringify_error: stringifyError,
        order_marker: orderMarker === "" ? null : orderMarker,
        payload_keys: payload !== null && typeof payload === "object"
          ? Object.keys(payload as Record<string, unknown>).sort()
          : [],
        message_count: Array.isArray((payload as { messages?: unknown })?.messages)
          ? ((payload as { messages: unknown[] }).messages.length)
          : null,
        model: (payload as { model?: unknown })?.model ?? null,
        stream: (payload as { stream?: unknown })?.stream ?? null,
      }) + "\n",
      "utf8",
    );
    if (!marked) return undefined;
    return payload;
  });
}
