/** ONE owner of "start a Brain Python command that outlives the host".
 *
 * The host worker can be torn down the moment a shutdown handler returns, so
 * anything the host hands off at that point must run in its own detached
 * process: `detached: true` puts the child in its own process group, `unref()`
 * releases the host's last handle, and `stdio: "ignore"` removes the pipes a
 * dying parent would close. Verified on Windows under both Bun (the OMP host
 * runtime) and Node: a detached child finishes its ~3 s of work seconds AFTER
 * the parent exits, while the same spawn without `detached: true` is reaped
 * with the parent.
 *
 * Fail-open by contract: these children have no reader, so a spawn failure
 * (missing interpreter, EACCES, bad cwd) must be reported as "not started" and
 * never as a throw, and the async `error` event a failed spawn raises must not
 * become an uncaught exception inside the host. */
import { spawn } from "node:child_process";

/**
 * Start `python args...` detached, in `home`, with the bridges' environment
 * contract (no inherited PYTHONHOME/PYTHONPATH; SECOND_BRAIN_HOME set).
 * Returns whether the process was started.
 */
export function startDetachedBrainCommand(python: string, args: string[], home: string): boolean {
  const env: Record<string, string | undefined> = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.SECOND_BRAIN_HOME = home;
  try {
    const child = spawn(python, args, {
      cwd: home,
      env: env as NodeJS.ProcessEnv,
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    });
    child.once("error", () => {
      // The host may already be exiting; nothing can read this failure.
    });
    child.unref();
    return true;
  } catch {
    return false;
  }
}
