import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "vitest/config";

// Tests make throwaway git repositories and commit in them: give every run an identity, so they
// pass on machines (CI runners) without a global git user.
const identity = { GIT_AUTHOR_NAME: "brain-test", GIT_AUTHOR_EMAIL: "brain-test@example.invalid", GIT_COMMITTER_NAME: "brain-test", GIT_COMMITTER_EMAIL: "brain-test@example.invalid" };

// Throwaway homes, repos and scripts of one run live under one folder that test/global-setup.ts
// removes: before, every full run left about 1,000 `brain-*` folders in the OS temp directory.
const runTemp = (process.env.BRAIN_TEST_TMP ??= mkdtempSync(join(tmpdir(), "brain-test-run-")));

// Whole suites that launch external runtimes or git stay outside the fast loop.
const integration = ["capture", "card", "claims", "cli", "install", "journey", "review", "startup", "swarm", "sync"].map((name) => `test/${name}.test.ts`);

export default defineConfig({
  test: {
    testTimeout: 20000,
    setupFiles: ["./test/setup.ts"],
    globalSetup: ["./test/global-setup.ts"],
    env: { ...identity, TMPDIR: runTemp, TEMP: runTemp, TMP: runTemp },
    projects: [
      { extends: true, test: { name: "unit", include: ["test/**/*.test.ts"], exclude: integration } },
      { extends: true, test: { name: "integration", include: integration } },
    ],
  },
});
