/**
 * BrainHostProtocol v1 — OMP-side bridge.
 *
 * Thesis: Brain needs *facts about the host*, and the host needs to stop being patched.
 * This file is the whole OMP-side surface of the contract: it reads documented
 * extension surfaces, maps their field names here (nowhere else), and emits protocol
 * payloads. It imports nothing from OMP internals, owns no Brain semantics, and never
 * decides a release.
 *
 * Capability honesty: a capability is advertised true only when this bridge can
 * actually produce that payload from surfaces it can read. Stock 18.2.8 offers a job
 * snapshot and lifecycle frames; it offers no host-attested settlement and no cleanup
 * completion signal at all, so both stay false and no settlement payoff is emitted.
 * The former 13-file host patch existed to manufacture exactly those two facts; this
 * bridge refuses to fake them instead.
 */

export const PROTOCOL_VERSION = 1;
export const BRIDGE_NAME = "brain-host-bridge";
export const BRIDGE_VERSION = "1.0.0";

export type Capability =
  | "effective_tool_grant"
  | "execution_binding"
  | "settlement_observation"
  | "cleanup_observation"
  | "cancellation_observation"
  | "execution_census";

export const CAPABILITIES: readonly Capability[] = [
  "effective_tool_grant",
  "execution_binding",
  "settlement_observation",
  "cleanup_observation",
  "cancellation_observation",
  "execution_census",
];

export interface Advertisement {
  protocol_version: 1;
  bridge: { name: string; version: string };
  host: { vendor: string; name: string; version: string };
  capabilities: Record<Capability, boolean>;
  evidence: Record<Capability, string>;
}

export interface ObservationBase {
  protocol_version: 1;
  attempt_id: string;
  host_generation: number;
  method: string;
  observation: string;
}

export type HostWorkerBinding = ObservationBase & {
  kind: "HostWorkerBinding";
  native_execution_id: string;
  agent_id: string;
};

export type HostCancellation = ObservationBase & {
  kind: "HostCancellation";
  native_execution_id: string;
  cancelled: boolean;
};

export type HostExecutionCensus = ObservationBase & {
  kind: "HostExecutionCensus";
  resources: Array<{ kind: string; id: string; quiescent: boolean }>;
  resources_complete: boolean;
};

export type HostObservation = HostWorkerBinding | HostCancellation | HostExecutionCensus;

/** The surfaces this bridge reads. Everything else about the host stays unknown to it. */
export interface HostSurfaces {
  /** Documented: returns running/recent job rows. Row shape is narrowed below. */
  getAsyncJobSnapshot?: (options?: { recentLimit?: number }) => unknown;
  /** Documented: the lifecycle event bus (`events.on`). Presence is all we assert. */
  events?: { on?: unknown };
}

/** Host field names appear only in this narrowing block. */
interface JobRow {
  /** OMP manager execution id (`jobs[].id`). */
  id: string;
  /** OMP agent identity (`jobs[].agentId`). */
  agentId: string;
  /** OMP terminal status. */
  status: string;
}

const TERMINAL_STATUSES: Record<string, true> = {
  completed: true,
  failed: true,
  cancelled: true,
  canceled: true,
};

function narrowSurfaces(context: unknown): HostSurfaces {
  if (context === null || typeof context !== "object") return {};
  const surfaces: HostSurfaces = {};
  if ("getAsyncJobSnapshot" in context) {
    const candidate: unknown = context.getAsyncJobSnapshot;
    if (typeof candidate === "function") {
      // Documented signature; the value it returns is re-validated in rowsFrom, so this
      // contained cast only carries the call, not the shape.
      surfaces.getAsyncJobSnapshot = candidate as HostSurfaces["getAsyncJobSnapshot"];
    }
  }
  if ("events" in context) {
    const events: unknown = context.events;
    if (events !== null && typeof events === "object" && "on" in events) {
      const on: unknown = events.on;
      if (typeof on === "function") surfaces.events = { on };
    }
  }
  return surfaces;
}

function rowsFrom(value: unknown): JobRow[] {
  if (value === null || typeof value !== "object") return [];
  const rows: JobRow[] = [];
  for (const key of ["running", "recent"] as const) {
    if (!(key in value)) continue;
    const group: unknown = value[key];
    if (!Array.isArray(group)) continue;
    for (const row of group) {
      if (row === null || typeof row !== "object") continue;
      if (!("id" in row)) continue;
      const id: unknown = row.id;
      if (typeof id !== "string" || id === "") continue;
      // agentId is the documented agent identity; agentUrlId is what the hub
      // serializer substitutes for a structured result. Both name the agent.
      let agentId = "";
      if ("agentId" in row && typeof row.agentId === "string") agentId = row.agentId;
      else if ("agentUrlId" in row && typeof row.agentUrlId === "string") agentId = row.agentUrlId;
      let status = "";
      if ("status" in row && typeof row.status === "string") status = row.status.toLowerCase();
      rows.push({ id, agentId, status });
    }
  }
  return rows;
}

function snapshotRows(surfaces: HostSurfaces): JobRow[] {
  if (surfaces.getAsyncJobSnapshot === undefined) return [];
  try {
    return rowsFrom(surfaces.getAsyncJobSnapshot({ recentLimit: 64 }));
  } catch {
    return [];
  }
}

/** Bind an agent identity to the host's execution id, from the snapshot alone. */
export function executionIdForAgent(context: unknown, agentId: string): string | null {
  if (agentId === "") return null;
  for (const row of snapshotRows(narrowSurfaces(context))) {
    if (row.agentId === agentId) return row.id;
  }
  return null;
}

/** The terminal status observed for exactly this execution id, or null. */
export function terminalStatusFor(
  context: unknown,
  executionId: string,
): "completed" | "failed" | "cancelled" | null {
  if (executionId === "") return null;
  for (const row of snapshotRows(narrowSurfaces(context))) {
    if (row.id !== executionId) continue;
    if (TERMINAL_STATUSES[row.status] !== true) return null;
    return row.status === "canceled" ? "cancelled" : (row.status as "completed" | "failed" | "cancelled");
  }
  return null;
}

export function advertise(options: { hostVersion: string; context?: unknown }): Advertisement {
  const surfaces = narrowSurfaces(options.context);
  const snapshotAvailable = surfaces.getAsyncJobSnapshot !== undefined;
  const framesAvailable = surfaces.events?.on !== undefined;
  const capabilities: Record<Capability, boolean> = {
    effective_tool_grant: false,
    // The snapshot names both ids for running and recent jobs: that is correlation,
    // which the bridge can establish without being trusted about safety.
    execution_binding: snapshotAvailable,
    // No host-attested settlement exists on stock: frames carry a status but no
    // authenticated binding, so the bridge does not emit settlement at all.
    settlement_observation: false,
    // Nothing on stock reports that a worktree's cleanup finished.
    cleanup_observation: false,
    cancellation_observation: snapshotAvailable,
    execution_census: snapshotAvailable,
  };
  const evidence: Record<Capability, string> = {
    effective_tool_grant:
      "unavailable: a child's effective tool grant is not exposed; a driver's own tool surface is not evidence about a child",
    execution_binding: snapshotAvailable
      ? "ctx.getAsyncJobSnapshot() running/recent rows, matching rows[].agentId and taking rows[].id"
      : "unavailable: no getAsyncJobSnapshot on this host",
    settlement_observation:
      framesAvailable
        ? "unavailable: lifecycle frames carry an unauthenticated status only; the host-attested settlement API the retired patch added is absent"
        : "unavailable: no lifecycle surface at all",
    cleanup_observation:
      "unavailable: the host detaches late cleanup and exposes no completion signal",
    cancellation_observation: snapshotAvailable
      ? "ctx.getAsyncJobSnapshot() terminal status for the bound execution id"
      : "unavailable: no getAsyncJobSnapshot on this host",
    execution_census: snapshotAvailable
      ? "ctx.getAsyncJobSnapshot() running plus recent rows"
      : "unavailable: no getAsyncJobSnapshot on this host",
  };
  return {
    protocol_version: PROTOCOL_VERSION,
    bridge: { name: BRIDGE_NAME, version: BRIDGE_VERSION },
    host: { vendor: "oh-my-pi", name: "pi-coding-agent", version: options.hostVersion },
    capabilities,
    evidence,
  };
}

export function observeBinding(
  context: unknown,
  input: { attemptId: string; hostGeneration: number; agentId: string },
): HostWorkerBinding | null {
  const executionId = executionIdForAgent(context, input.agentId);
  if (executionId === null) return null;
  return {
    protocol_version: PROTOCOL_VERSION,
    kind: "HostWorkerBinding",
    attempt_id: input.attemptId,
    host_generation: input.hostGeneration,
    native_execution_id: executionId,
    agent_id: input.agentId,
    method: "ctx.getAsyncJobSnapshot(): rows[].agentId matched, rows[].id taken as the execution id",
    observation: `agent ${input.agentId} is bound to execution ${executionId} in the host snapshot`,
  };
}

export function observeCancellation(
  context: unknown,
  input: { attemptId: string; hostGeneration: number; executionId: string },
): HostCancellation | null {
  const status = terminalStatusFor(context, input.executionId);
  if (status !== "cancelled" && status !== "failed") return null;
  return {
    protocol_version: PROTOCOL_VERSION,
    kind: "HostCancellation",
    attempt_id: input.attemptId,
    host_generation: input.hostGeneration,
    native_execution_id: input.executionId,
    cancelled: true,
    method: "ctx.getAsyncJobSnapshot(): terminal status observed for this exact execution id",
    observation: `execution ${input.executionId} reached terminal status ${status}`,
  };
}

export function observeCensus(
  context: unknown,
  input: { attemptId: string; hostGeneration: number },
): HostExecutionCensus | null {
  const surfaces = narrowSurfaces(context);
  if (surfaces.getAsyncJobSnapshot === undefined) return null;
  const rows = snapshotRows(surfaces);
  return {
    protocol_version: PROTOCOL_VERSION,
    kind: "HostExecutionCensus",
    attempt_id: input.attemptId,
    host_generation: input.hostGeneration,
    resources: rows.map((row) => ({
      kind: "host_execution",
      id: row.id,
      // Presence in the snapshot is not proof a worktree is idle: the census reports
      // what the host lists, and says so, rather than inferring quiescence.
      quiescent: TERMINAL_STATUSES[row.status] === true,
    })),
    resources_complete: true,
    method: "ctx.getAsyncJobSnapshot(): enumeration of running plus recent executions",
    observation: `${rows.length} host executions listed at census time`,
  };
}
