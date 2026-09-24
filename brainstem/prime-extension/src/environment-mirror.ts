import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const ENVIRONMENT_DEFAULT_TIMEOUT_MS = 5000;

/**
 * Repo-root manifests whose change invalidates an environment assessment. Only
 * size+mtime are read (`statSync`), never file content, so the fingerprint is
 * cheap enough to compute on every prompt.
 */
export const ENVIRONMENT_FINGERPRINT_FILES = [
  "package.json",
  "package-lock.json",
  "bun.lockb",
  "bun.lock",
  "pyproject.toml",
  "uv.lock",
  "requirements.txt",
  "Cargo.lock",
  "go.sum",
] as const;

/** `requirements*.txt` (version-stamped names) are enumerated by listdir. */
const ENVIRONMENT_FINGERPRINT_REQUIREMENTS_RE = /^requirements.*\.txt$/u;
/** A ref name that stays inside the git directory (no traversal, no drive letter). */
const GIT_REF_NAME_RE = /^[A-Za-z0-9._/-]+$/u;

/** Git directories one checkout reads: a linked worktree splits them in two. */
interface GitDirectories {
  /** Holds this worktree's `HEAD` (`<repo>/.git`, or the worktree gitdir). */
  gitDir: string;
  /** Holds the refs (`<gitDir>` itself, or the main repository's git dir). */
  commonDir: string;
}

/**
 * `commondir` points a linked worktree's git directory at the shared one, where
 * branch refs actually live.
 */
function commonGitDir(gitDir: string): string {
  try {
    const value = readFileSync(join(gitDir, "commondir"), "utf8").trim();
    return value.length === 0 ? gitDir : resolve(gitDir, value);
  } catch {
    return gitDir;
  }
}

/**
 * Resolve the git directories for `repo`. A LINKED WORKTREE — this repository's
 * own reviewed checkout shape — has a `.git` FILE holding `gitdir: <path>`, so
 * reading `<repo>/.git/HEAD` finds nothing and every branch of every worktree
 * would fingerprint identically.
 */
function gitDirectories(repo: string): GitDirectories | undefined {
  const dotGit = join(repo, ".git");
  let pointer: string;
  try {
    const stat = statSync(dotGit);
    if (stat.isDirectory()) return { gitDir: dotGit, commonDir: commonGitDir(dotGit) };
    if (!stat.isFile()) return undefined;
    pointer = readFileSync(dotGit, "utf8").trim();
  } catch {
    return undefined; // not a git checkout: no git state to fingerprint
  }
  const match = /^gitdir:\s*(.+)$/u.exec(pointer);
  if (match === null) return undefined;
  const gitDir = resolve(repo, match[1]!.trim());
  return { gitDir, commonDir: commonGitDir(gitDir) };
}

/** The commit `name` currently points at: loose file first, then `packed-refs`. */
function resolveGitRef(directories: GitDirectories, name: string): string | undefined {
  if (!GIT_REF_NAME_RE.test(name) || name.includes("..")) return undefined;
  const parts = name.split("/");
  for (const dir of [directories.gitDir, directories.commonDir]) {
    try {
      const value = readFileSync(join(dir, ...parts), "utf8").trim();
      if (value.length > 0) return value;
    } catch {
      // not stored loosely there: try the other directory, then packed-refs
    }
  }
  try {
    for (const line of readFileSync(join(directories.commonDir, "packed-refs"), "utf8").split(/\r?\n/u)) {
      const match = /^([0-9a-f]{7,64})\s+(\S+)$/u.exec(line.trim());
      if (match !== null && match[2] === name) return match[1];
    }
  } catch {
    // no packed-refs file: the ref is simply not resolvable here
  }
  return undefined;
}

/**
 * The repository state `HEAD` names, as one fingerprint part: HEAD's content
 * (branch switch, detached commit) PLUS the value the ref currently points at —
 * on a branch the content alone is stable while its commits advance, so a
 * manifest-identical `git pull` would otherwise leave the fingerprint unchanged.
 */
function gitHeadStamp(repo: string): string {
  const directories = gitDirectories(repo);
  if (directories === undefined) return "-";
  let head: string;
  try {
    head = readFileSync(join(directories.gitDir, "HEAD"), "utf8").trim();
  } catch {
    return "-";
  }
  if (head.length === 0) return "-";
  const ref = /^ref:\s*(.+)$/u.exec(head);
  if (ref === null) return head; // detached HEAD: the commit id itself
  return `${head}=${resolveGitRef(directories, ref[1]!.trim()) ?? "-"}`;
}

/**
 * Cheap in-host fingerprint of the environment evidence a new assessment would
 * read: repo-root manifests (size+mtime) plus Git's HEAD state (HEAD content and
 * the ref value it resolves to, through the real git directory, so linked
 * worktrees and branch advances are visible). The assessment runs once per
 * session and then only when this value changes — not once per prompt.
 */
export function environmentFingerprint(
  repo: string,
  env: Record<string, string | undefined> = process.env,
): string {
  const parts: string[] = [];
  const stamp = (name: string): void => {
    try {
      const stat = statSync(join(repo, name));
      parts.push(`${name}=${stat.size}:${Math.trunc(stat.mtimeMs)}`);
    } catch {
      parts.push(`${name}=-`); // absent/unreadable: a stable, honest value
    }
  };
  for (const name of ENVIRONMENT_FINGERPRINT_FILES) {
    if (name === "requirements.txt") continue; // covered by the listdir below
    stamp(name);
  }
  try {
    for (const entry of readdirSync(repo)) {
      if (ENVIRONMENT_FINGERPRINT_REQUIREMENTS_RE.test(entry)) stamp(entry);
    }
  } catch {
    // unreadable repo root: the fixed list above still fingerprints
  }
  try {
    parts.push(`git/head=${gitHeadStamp(repo)}`);
  } catch {
    parts.push("git/head=-"); // any unexpected failure: a stable, honest value
  }
  parts.sort();
  return createHash("sha256")
    .update(`${repo}\n${parts.join("\n")}\n${env.SECOND_BRAIN_PROJECT ?? ""}`, "utf8")
    .digest("hex");
}

type JsonRecord = Record<string, unknown>;

export interface EnvironmentAssessmentOptions {
  home: string;
  hostSessionId: string;
  repo: string;
  taskId?: string;
  phase: "session_start" | "task_boundary" | "doctor" | "shutdown";
  expectedFields?: string[];
  python?: string;
  timeoutMs?: number;
}

export interface EnvironmentAssessmentResult {
  ok: boolean;
  sessionId?: string;
  environmentStewardId?: string;
  environmentHash?: string;
  mutationDetected?: boolean;
  mutationClassification?: string;
  completionEligible?: boolean;
  evidence?: JsonRecord;
  error?: string;
}

function pythonExe(home: string, python?: string): string {
  return python ?? process.env.SECOND_BRAIN_PYTHON ?? join(home, ".venv", "Scripts", "python.exe");
}

function runEnv(home: string): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = home;
  return env;
}

function parseResult(stdout: string, sessionId: string): EnvironmentAssessmentResult {
  try {
    const evidence = JSON.parse(stdout) as JsonRecord;
    if (evidence.session_id !== sessionId) {
      return { ok: false, error: "environment session mismatch" };
    }
    return {
      ok: true,
      sessionId,
      environmentStewardId:
        typeof evidence.environment_steward_id === "string"
          ? evidence.environment_steward_id
          : undefined,
      environmentHash:
        typeof evidence.environment_hash === "string" ? evidence.environment_hash : undefined,
      mutationDetected: evidence.mutation_detected === true,
      mutationClassification:
        typeof evidence.mutation_classification === "string"
          ? evidence.mutation_classification
          : undefined,
      completionEligible: evidence.completion_eligible === true,
      evidence,
    };
  } catch {
    return { ok: false, error: "environment assessment returned unparsable output" };
  }
}

function assessmentArgs(options: EnvironmentAssessmentOptions): string[] {
  const args = [
    "-m", "second_brain", "env", "assess", options.repo,
    "--session", options.hostSessionId,
    ...(options.taskId ? ["--task-id", options.taskId] : []),
    "--phase", options.phase,
  ];
  for (const field of options.expectedFields ?? []) args.push("--expected-field", field);
  args.push("--json");
  return args;
}

/**
 * Non-blocking variant for session start and task boundaries: the assessment
 * (~1.4 s measured on a large repo) writes its own evidence file, so the host
 * turn never waits for it (PERF-02).
 */
export async function runEnvironmentAssessment(
  options: EnvironmentAssessmentOptions,
): Promise<EnvironmentAssessmentResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) return { ok: true, sessionId: options.hostSessionId };
  try {
    const { stdout } = await execFileAsync(python, assessmentArgs(options), {
      cwd: options.home,
      env: runEnv(options.home),
      timeout: options.timeoutMs ?? ENVIRONMENT_DEFAULT_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
    });
    return parseResult(String(stdout), options.hostSessionId);
  } catch (error) {
    return { ok: false, sessionId: options.hostSessionId, error: error instanceof Error ? error.message : String(error) };
  }
}
