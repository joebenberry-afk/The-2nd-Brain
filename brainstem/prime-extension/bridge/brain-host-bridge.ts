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
  | "execution_census"
  | "authenticated_observation_source";

export const CAPABILITIES: readonly Capability[] = [
  "effective_tool_grant",
  "execution_binding",
  "settlement_observation",
  "cleanup_observation",
  "cancellation_observation",
  "execution_census",
  "authenticated_observation_source",
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

export type HostExecutionInventory = ObservationBase & {
  kind: "HostExecutionInventory";
  resources: Array<{ kind: string; id: string; observed_terminal: boolean }>;
  census_available: boolean;
  census_scope_complete: boolean;
};

export type HostObservation = HostWorkerBinding | HostCancellation | HostExecutionInventory;

/** The surfaces this bridge reads. Everything else about the host stays unknown to it. */
export interface HostSurfaces {
  /** Documented: returns running/recent job rows. Row shape is narrowed below. */
  getAsyncJobSnapshot?: (options?: { recentLimit?: number }) => unknown;
  /** Documented: the lifecycle event bus (`events.on`). Presence is all we assert. */
  events?: { on?: unknown };
}

/** Host field names are READ only in this narrowing block; the diagnostic strings that
 * describe an observation may name the surface they came from, but no other function
 * reads a host object and no host object crosses the boundary. */
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

/**
 * Whether the snapshot's *shape* is the one this bridge knows how to read.
 *
 * Renaming the host's arrays (or returning something else entirely) must make the
 * capability false rather than leave the bridge silently unable to bind: a claim it
 * cannot deliver is worse than an advertised gap. An empty snapshot is still a usable
 * shape — absence of jobs is not absence of the surface.
 */
function snapshotShapeUsable(surfaces: HostSurfaces): boolean {
  if (surfaces.getAsyncJobSnapshot === undefined) return false;
  let value: unknown;
  try {
    value = surfaces.getAsyncJobSnapshot({ recentLimit: 64 });
  } catch {
    return false;
  }
  if (value === null || typeof value !== "object") return false;
  return (
    ("running" in value && Array.isArray(value.running)) ||
    ("recent" in value && Array.isArray(value.recent))
  );
}

/**
 * Bind an agent identity to the host's execution id, from the snapshot alone.
 *
 * Returns null when the identity is not uniquely resolvable: an agent name can be
 * reused, and a first-match lookup would silently bind the wrong execution.
 */
export function executionIdForAgent(context: unknown, agentId: string): string | null {
  if (agentId === "") return null;
  const matches = new Set<string>();
  for (const row of snapshotRows(narrowSurfaces(context))) {
    if (row.agentId === agentId) matches.add(row.id);
  }
  return matches.size === 1 ? [...matches][0] : null;
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
  const snapshotAvailable = snapshotShapeUsable(surfaces);
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
    // The snapshot is a bounded window over an evicting list, and recovery needs a
    // *complete* census; enumerating rows is not completeness, so the capability is
    // advertised false rather than approximated from a partial read.
    execution_census: false,
    // Nothing signs a payload: any code in the agent's execution context could emit
    // identical JSON. Until an impersonation boundary exists, settlement and cleanup
    // can never be trusted from this bridge — which is what keeps mutating work off.
    authenticated_observation_source: false,
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
      ? "unavailable: the host snapshot is a bounded window over an evicting list, so a complete census cannot be established"
      : "unavailable: no getAsyncJobSnapshot on this host",
    authenticated_observation_source:
      "unavailable: advertisements and observations are unsigned; code sharing the agent's execution context could emit identical bytes and there is no OS-level impersonation boundary on this host",
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
  // Only a cancelled execution is a cancellation. A failed one is a failure, which the
  // Brain learns from its own result path; reporting it here would relabel an ordinary
  // failure as an operator/host cancellation.
  const status = terminalStatusFor(context, input.executionId);
  if (status !== "cancelled") return null;
  return {
    protocol_version: PROTOCOL_VERSION,
    kind: "HostCancellation",
    attempt_id: input.attemptId,
    host_generation: input.hostGeneration,
    native_execution_id: input.executionId,
    cancelled: true,
    method: "host snapshot: cancelled status observed for this exact execution id",
    observation: `execution ${input.executionId} was cancelled`,
  };
}

export function observeInventory(
  context: unknown,
  input: { attemptId: string; hostGeneration: number },
): HostExecutionInventory | null {
  const surfaces = narrowSurfaces(context);
  if (surfaces.getAsyncJobSnapshot === undefined) return null;
  const rows = snapshotRows(surfaces);
  return {
    protocol_version: PROTOCOL_VERSION,
    kind: "HostExecutionInventory",
    attempt_id: input.attemptId,
    host_generation: input.hostGeneration,
    resources: rows.map((row) => ({
      kind: "host_execution",
      id: row.id,
      // What the snapshot showed, not a claim that anything is idle.
      observed_terminal: TERMINAL_STATUSES[row.status] === true,
    })),
    census_available: true,
    // The snapshot is a bounded window over an evicting list, so its scope is never
    // provably complete. Recovery must not read "no listed workers" as "nothing can
    // mutate this worktree".
    census_scope_complete: false,
    method: "host snapshot enumeration (bounded window); scope completeness not establishable",
    observation: `${rows.length} host executions observed; absence of a row proves nothing`,
  };
}
