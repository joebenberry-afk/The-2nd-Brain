/**
 * Candidate-local vitest configuration.
 *
 * The candidate reaches its toolchain through a directory junction to the runtime worktree's
 * node_modules (space, not isolation). Vite's default cacheDir is node_modules/.vite, so running
 * the suite with defaults writes *through* that junction into a tree this campaign must not touch.
 * This config keeps every generated artifact candidate-owned. It is not a behaviour change to the
 * tests; the same specs run.
 */
import { defineConfig } from "vitest/config";

export default defineConfig({
  cacheDir: "./.m00-candidate-cache/vite",
  test: {
    cache: false,
  },
});
