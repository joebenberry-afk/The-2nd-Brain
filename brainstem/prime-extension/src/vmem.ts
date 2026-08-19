/**
 * Prime <-> Context Virtual Memory (VMem) bridge (plan §6, Phase R3).
 *
 * VMem (`src/second_brain/vmem.py`) is a real, tested, session-object-level
 * paging store, but until this pass it was reachable only via
 * `second_brain vmem ...` CLI subcommands (§ 01-rc3-evidence-disposition /
 * 02-prime-live-callgraph) — nothing in Prime called it. This module wires
 * the two compaction-boundary operations VMem's own docstrings describe as
 * its natural integration point (§6.7 "Compaction barrier interaction"):
 * `compact-prep` (mark unpinned resident objects EVICTED ahead of
 * compaction) and `hot-context` (render the resulting hot/cold working set).
 *
 * This is bookkeeping only: it advances residency state in VMem's own
 * SQLite store and reports counts as telemetry. It does NOT replace the
 * Prime `context` event's `messages` array — that would require knowing the
 * real Prime message shape, which is `unknown[]` everywhere in this
 * codebase because no live session has ever captured it (see
 * outputs/reports/rc4/02-prime-live-callgraph.md, "context" section).
 *
 * Fail-open, same subprocess pattern as `ledger-mirror.ts`'s
 * runLedgerCheckpoint/runLedgerSegmentRollover and `rtd.ts`'s
 * cliRtdPreserver: any spawn/parse failure resolves `ok: false` with an
 * `error` string, never throws.
 */
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const VMEM_DEFAULT_TIMEOUT_MS = 5000;

function pythonExe(home: string, python?: string): string {
  return python ?? join(home, ".venv", "Scripts", "python.exe");
}

function runEnv(home: string): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = home;
  return env;
}

export interface VmemCompactPrepResult {
  ok: boolean;
  evictedAtCompaction?: number;
  pinnedPreserved?: number;
  error?: string;
}

/** `second_brain vmem compact-prep <session> --json`: mark unpinned resident
 * objects EVICTED ahead of a real compaction event. */
export function runVmemCompactPrep(options: {
  home: string;
  hostSessionId: string;
  python?: string;
  timeoutMs?: number;
}): Promise<VmemCompactPrepResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return Promise.resolve({ ok: false, error: "no brain venv (vmem compact-prep unavailable)" });
  }
  return new Promise((resolve) => {
    execFile(
      python,
      ["-m", "second_brain", "vmem", "compact-prep", options.hostSessionId, "--json"],
      {
        cwd: options.home,
        env: runEnv(options.home),
        timeout: options.timeoutMs ?? VMEM_DEFAULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, error: error.message });
          return;
        }
        try {
          const parsed = JSON.parse(stdout) as {
            evicted_at_compaction?: number;
            pinned_preserved?: number;
          };
          resolve({
            ok: true,
            evictedAtCompaction: parsed.evicted_at_compaction,
            pinnedPreserved: parsed.pinned_preserved,
          });
        } catch {
          resolve({ ok: false, error: "compact-prep returned unparsable output" });
        }
      },
    );
  });
}

export interface VmemHotContextResult {
  ok: boolean;
  residentCount?: number;
  evictedCount?: number;
  residentTokens?: number;
  error?: string;
}

/** `second_brain vmem hot-context <session> --budget <n> --json`: render the
 * resident/evicted working set after a compaction boundary. Renders (not
 * mutates) — the model-visible context is untouched by this call. */
export function runVmemHotContext(options: {
  home: string;
  hostSessionId: string;
  budgetTokens: number;
  python?: string;
  timeoutMs?: number;
}): Promise<VmemHotContextResult> {
  const python = pythonExe(options.home, options.python);
  if (!existsSync(python)) {
    return Promise.resolve({ ok: false, error: "no brain venv (vmem hot-context unavailable)" });
  }
  return new Promise((resolve) => {
    execFile(
      python,
      [
        "-m",
        "second_brain",
        "vmem",
        "hot-context",
        options.hostSessionId,
        "--budget",
        String(options.budgetTokens),
        "--json",
      ],
      {
        cwd: options.home,
        env: runEnv(options.home),
        timeout: options.timeoutMs ?? VMEM_DEFAULT_TIMEOUT_MS,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, error: error.message });
          return;
        }
        try {
          const parsed = JSON.parse(stdout) as {
            resident_count?: number;
            evicted_count?: number;
            resident_tokens?: number;
          };
          resolve({
            ok: true,
            residentCount: parsed.resident_count,
            evictedCount: parsed.evicted_count,
            residentTokens: parsed.resident_tokens,
          });
        } catch {
          resolve({ ok: false, error: "hot-context returned unparsable output" });
        }
      },
    );
  });
}
