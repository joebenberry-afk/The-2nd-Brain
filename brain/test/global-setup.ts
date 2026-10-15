import { rmSync } from "node:fs";

/** Removes the run's temp folder (created in vitest.config.ts) once every test file has finished. */
export default function setup(): () => void {
  return () => {
    const dir = process.env.BRAIN_TEST_TMP;
    if (dir) rmSync(dir, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
  };
}
