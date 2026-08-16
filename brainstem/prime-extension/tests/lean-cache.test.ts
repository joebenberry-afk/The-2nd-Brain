import { beforeEach, describe, expect, it, vi } from "vitest";
import { join } from "node:path";

/**
 * P3-D lean kernel in-process cache tests (plan §8.6) with node:fs mocked,
 * so read counts are observable. The real-fs behavioral tests (mtime/size
 * invalidation, lifecycle dir resolution) live in tests/lean-code.test.ts;
 * this file proves the CACHE CONTRACT deterministically:
 *   - an unchanged file is read AT MOST ONCE per extension lifecycle;
 *   - an mtime change reloads exactly once.
 */
const existsSyncMock = vi.hoisted(() => vi.fn());
const readFileSyncMock = vi.hoisted(() => vi.fn());
const statSyncMock = vi.hoisted(() => vi.fn());

vi.mock("node:fs", () => ({
  existsSync: existsSyncMock,
  readFileSync: readFileSyncMock,
  statSync: statSyncMock,
}));

import {
  leanKernelCacheSize,
  loadLeanKernel,
  resetLeanKernelCache,
} from "../src/lean-code";

const SKILL_TEXT =
  "# Purpose\nLean Code minimizes total cost.\n\n# Runtime Kernel\n\nLEAN CODE: kernel body\n";

const home = "C:/brain";
const candidatePath = join(home, "skills", "candidates", "lean-code", "SKILL.md");

beforeEach(() => {
  resetLeanKernelCache();
  existsSyncMock.mockReset();
  readFileSyncMock.mockReset();
  statSyncMock.mockReset();
  existsSyncMock.mockImplementation((p: string) => p === candidatePath);
  readFileSyncMock.mockReturnValue(SKILL_TEXT);
  statSyncMock.mockReturnValue({ mtimeMs: 1000, size: SKILL_TEXT.length });
});

describe("lean kernel in-process cache (plan §8.6)", () => {
  it("serves the second call from the cache (no reread per turn)", () => {
    const first = loadLeanKernel(home);
    expect(first.kernel).toBe("LEAN CODE: kernel body");
    expect(readFileSyncMock).toHaveBeenCalledTimes(1);

    const second = loadLeanKernel(home);
    expect(second.kernel).toBe("LEAN CODE: kernel body");
    expect(readFileSyncMock).toHaveBeenCalledTimes(1); // cache hit: no reread
    expect(leanKernelCacheSize()).toBe(1);
  });

  it("reloads exactly once when the file mtime changes", () => {
    loadLeanKernel(home);
    expect(readFileSyncMock).toHaveBeenCalledTimes(1);

    statSyncMock.mockReturnValue({ mtimeMs: 2000, size: SKILL_TEXT.length });
    const reloaded = loadLeanKernel(home);
    expect(reloaded.kernel).toBe("LEAN CODE: kernel body");
    expect(readFileSyncMock).toHaveBeenCalledTimes(2); // mtime changed -> reloaded
  });

  it("reloads when the file size changes even with the same mtime", () => {
    loadLeanKernel(home);
    expect(readFileSyncMock).toHaveBeenCalledTimes(1);

    statSyncMock.mockReturnValue({ mtimeMs: 1000, size: SKILL_TEXT.length + 10 });
    loadLeanKernel(home);
    expect(readFileSyncMock).toHaveBeenCalledTimes(2); // size changed -> reloaded
  });

  it("caches fail-open errors so a corrupt file is not re-parsed per turn", () => {
    readFileSyncMock.mockReturnValue("# Purpose\nno kernel");
    const first = loadLeanKernel(home);
    expect(first.kernel).toBeUndefined();
    expect(first.error).toBeDefined();
    expect(readFileSyncMock).toHaveBeenCalledTimes(1);

    const second = loadLeanKernel(home);
    expect(second.kernel).toBeUndefined();
    expect(readFileSyncMock).toHaveBeenCalledTimes(1); // error entry cached too
  });
});
