import { defineConfig } from "vitest/config";

// Tests make throwaway git repositories and commit in them: give every run an identity, so they
// pass on machines (CI runners) without a global git user.
const identity = { GIT_AUTHOR_NAME: "brain-test", GIT_AUTHOR_EMAIL: "brain-test@example.invalid", GIT_COMMITTER_NAME: "brain-test", GIT_COMMITTER_EMAIL: "brain-test@example.invalid" };

export default defineConfig({ test: { include: ["test/**/*.test.ts"], testTimeout: 20000, env: identity } });
