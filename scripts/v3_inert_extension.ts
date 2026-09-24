/**
 * Inert-adapter control for V3 matched measurements (VAL-01, PERF-02).
 *
 * Subscribes to the same OMP host events as the Second Brain extension and does
 * nothing: no process spawn, no file I/O, no patch. The difference between this
 * arm and native (`--no-extensions`) is the host's own cost of loading an
 * extension and dispatching its hooks; the difference between this arm and a
 * Brain arm is what Brain itself adds.
 */

const EVENTS = [
  "session_start",
  "before_agent_start",
  "turn_start",
  "context",
  "before_provider_request",
  "after_provider_response",
  "message_end",
  "tool_call",
  "tool_result",
  "turn_end",
  "agent_end",
  "session_before_compact",
  "session_compact",
  "session_shutdown",
] as const;

interface HookHost {
  on(event: string, handler: () => undefined): void;
}

export default function inertExtension(pi: HookHost): void {
  for (const event of EVENTS) {
    pi.on(event, () => undefined);
  }
}
