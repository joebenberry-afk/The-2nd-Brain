/** Thin OMP -> Second Brain model-decision bridge. */
 
import { execFile } from "node:child_process";
import { join } from "node:path";

export const OMP_ROUTING_MAX_TASK_CHARS = 2048;
export const OMP_ROUTING_MAX_IDENTITY_CHARS = 128;
export const OMP_ROUTING_MAX_CANDIDATES = 32;
export const OMP_ROUTING_TIMEOUT_MS = 3000;
export const OMP_ROUTING_MAX_STDOUT_CHARS = 256 * 1024;
export const OMP_MODEL_CANDIDATES_ENV = "SECOND_BRAIN_OMP_MODEL_CANDIDATES";

export interface OmpModelCandidate {
  provider: string;
  model: string;
  [key: string]: unknown;
}

export interface OmpRoutingOptions {
  home: string;
  task: string;
  sessionId: string;
  projectId: string;
  role: string;
  provider: string;
  model: string;
  cwd?: string;
  candidates?: OmpModelCandidate[];
  python?: string;
  timeoutMs?: number;
  minimumTier?: string;
}

export interface OmpRoutingDecision {
  decision_id: string;
  task_hash: string;
  host_session_id: string;
  project_id: string;
  bot_role: string;
  selected_provider: string | null;
  selected_model: string | null;
  selected_tier: string | null;
  selected_cost_class: string | null;
  candidate_set_hash: string;
  fallback_used: boolean;
  fallback_provider: string | null;
  fallback_model: string | null;
  reason_code: string;
  status: "selected" | "failed";
  failure_code: string | null;
  routing_error: boolean;
  [key: string]: unknown;
}

export interface OmpRoutingResult {
  decision: OmpRoutingDecision | null;
  error?: string;
}

function bounded(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

function validIdentity(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= OMP_ROUTING_MAX_IDENTITY_CHARS;
}

function normaliseCandidates(values: OmpModelCandidate[] | undefined): OmpModelCandidate[] {
  if (!Array.isArray(values)) return [];
  return values
    .slice(0, OMP_ROUTING_MAX_CANDIDATES)
    .filter((candidate): candidate is OmpModelCandidate => {
      return candidate != null && typeof candidate === "object" && validIdentity(candidate.provider) && validIdentity(candidate.model);
    })
    .map((candidate) => ({ ...candidate, provider: bounded(candidate.provider, OMP_ROUTING_MAX_IDENTITY_CHARS), model: bounded(candidate.model, OMP_ROUTING_MAX_IDENTITY_CHARS) }));
}

/** Parse optional bounded candidate metadata; null means malformed config. */
export function parseConfiguredOmpCandidates(
  raw: string | undefined,
): OmpModelCandidate[] | null | undefined {
  if (raw === undefined || raw.trim().length === 0) return undefined;
  try {
    const parsed: unknown = JSON.parse(raw);
    const values =
      Array.isArray(parsed)
        ? parsed
        : parsed != null && typeof parsed === "object" && "candidates" in parsed &&
            Array.isArray(parsed.candidates)
          ? parsed.candidates
          : null;
    if (values === null || values.length > OMP_ROUTING_MAX_CANDIDATES) return null;
    const allowedTiers = new Set(["efficient", "balanced", "premium"]);
    const allowedCosts = new Set(["low", "medium", "high"]);
    const candidates: OmpModelCandidate[] = [];
    for (const value of values) {
      if (value == null || typeof value !== "object") return null;
      const item = value as Record<string, unknown>;
      if (!validIdentity(item.provider) || !validIdentity(item.model)) return null;
      const candidate: OmpModelCandidate = {
        provider: bounded(item.provider, OMP_ROUTING_MAX_IDENTITY_CHARS),
        model: bounded(item.model, OMP_ROUTING_MAX_IDENTITY_CHARS),
      };
      for (const key of ["tier", "cost_class", "roles", "capabilities", "max_risk", "quality_score"]) {
        if (item[key] !== undefined) candidate[key] = item[key];
      }
      if (candidate.tier !== undefined && (!allowedTiers.has(String(candidate.tier)))) return null;
      if (candidate.cost_class !== undefined && (!allowedCosts.has(String(candidate.cost_class)))) return null;
      const availability = item.availability;
      if (typeof availability === "boolean") candidate.available = availability;
      else if (availability != null && typeof availability === "object") {
        for (const key of ["available", "provider_available", "model_available"]) {
          if (typeof (availability as Record<string, unknown>)[key] === "boolean") {
            candidate[key] = (availability as Record<string, unknown>)[key];
          }
        }
      }
      candidates.push(candidate);
    }
    return candidates;
  } catch {
    return null;
  }
}

export function parseOmpRoutingOutput(stdout: string): OmpRoutingResult {
  if (stdout.length > OMP_ROUTING_MAX_STDOUT_CHARS) return { decision: null, error: "BRAIN_ROUTING_OUTPUT_TOO_LARGE" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return { decision: null, error: "BRAIN_ROUTING_INVALID_JSON" };
  }
  if (parsed == null || typeof parsed !== "object") return { decision: null, error: "BRAIN_ROUTING_INVALID_RESPONSE" };
  const value = parsed as Record<string, unknown>;
  const raw = value.decision;
  if (raw == null || typeof raw !== "object") {
    return { decision: null, error: bounded(value.error, 128) || "BRAIN_ROUTING_UNAVAILABLE" };
  }
  const decision = raw as Record<string, unknown>;
  if (!validIdentity(decision.decision_id) || !validIdentity(decision.task_hash)) {
    return { decision: null, error: "BRAIN_ROUTING_INVALID_DECISION" };
  }
  if (decision.status !== "selected" && decision.status !== "failed") {
    return { decision: null, error: "BRAIN_ROUTING_INVALID_DECISION" };
  }
  return { decision: decision as OmpRoutingDecision };
}

/** Run one bounded Brain-owned model decision; every failure fails open. */
export function runOmpRouting(options: OmpRoutingOptions): Promise<OmpRoutingResult> {
  const python = options.python ?? join(options.home, ".venv", "Scripts", "python.exe");
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = options.home;
  const provider = bounded(options.provider, OMP_ROUTING_MAX_IDENTITY_CHARS);
  const model = bounded(options.model, OMP_ROUTING_MAX_IDENTITY_CHARS);
  const role = bounded(options.role, OMP_ROUTING_MAX_IDENTITY_CHARS) || "worker";
  const configured = parseConfiguredOmpCandidates(process.env[OMP_MODEL_CANDIDATES_ENV]);
  const candidates = normaliseCandidates(
    configured === undefined ? options.candidates : configured ?? [],
  );
  if (candidates.length === 0 && provider.length > 0 && model.length > 0) {
    const elevated = ["driver", "integrator", "orchestrator"].includes(role.toLowerCase());
    candidates.push({
      provider,
      model,
      tier: elevated ? "balanced" : "efficient",
      cost_class: elevated ? "medium" : "low",
    });
  }
  const payload = {
    harness: "omp",
    task: bounded(options.task, OMP_ROUTING_MAX_TASK_CHARS),
    session_id: bounded(options.sessionId, OMP_ROUTING_MAX_IDENTITY_CHARS),
    host_session_id: bounded(options.sessionId, OMP_ROUTING_MAX_IDENTITY_CHARS),
    project_id: bounded(options.projectId, OMP_ROUTING_MAX_IDENTITY_CHARS),
    role,
    bot_role: role,
    bot_name: "omp",
    provider,
    model,
    cwd: bounded(options.cwd, OMP_ROUTING_MAX_IDENTITY_CHARS),
    candidates,
    ...(options.minimumTier ? { minimum_tier: bounded(options.minimumTier, OMP_ROUTING_MAX_IDENTITY_CHARS) } : {}),
  };
  return new Promise((resolve) => {
    const child = execFile(
      python,
      ["-m", "second_brain", "autoinject", "omp-routing"],
      {
        cwd: options.home,
        env,
        timeout: options.timeoutMs ?? OMP_ROUTING_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: OMP_ROUTING_MAX_STDOUT_CHARS,
      },
      (error, stdout) => {
        if (error) {
          resolve({ decision: null, error: "BRAIN_ROUTING_UNAVAILABLE" });
          return;
        }
        resolve(parseOmpRoutingOutput(stdout));
      },
    );
    child.stdin?.end(JSON.stringify(payload));
  });
}

export function ompRoutingRecord(
  kind: string,
  session: string,
  fields: Record<string, unknown>,
): Record<string, unknown> {
  return {
    v: 3,
    ts: new Date().toISOString(),
    kind,
    session,
    ...fields,
  };
}
