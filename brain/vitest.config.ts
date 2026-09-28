import { defineConfig } from "vitest/config";

// Tests make throwaway git repositories and commit in them: give every run an identity, so they
// pass on machines (CI runners) without a global git user.
const identity = { GIT_AUTHOR_NAME: "brain-test", GIT_AUTHOR_EMAIL: "brain-test@example.invalid", GIT_COMMITTER_NAME: "brain-test", GIT_COMMITTER_EMAIL: "brain-test@example.invalid" };

// Whole suites that launch external runtimes or git stay outside the fast loop.
const integration = ["capture", "card", "cli", "install", "journey", "review", "swarm", "sync"].map((name) => `test/${name}.test.ts`);

export default defineConfig({
  test: {
    testTimeout: 20000,
    env: identity,
    projects: [
      { extends: true, test: { name: "unit", include: ["test/**/*.test.ts"], exclude: integration } },
      { extends: true, test: { name: "integration", include: integration } },
    ],
  },
});
