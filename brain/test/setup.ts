import { beforeEach, vi } from "vitest";

// Never inherit the owner's credentials, including in CLI child processes.
delete process.env.TYPESAFE_API_KEY;
beforeEach(() => {
  delete process.env.TYPESAFE_API_KEY;
  vi.stubGlobal("fetch", () => { throw new Error("Network is disabled in tests; mock fetch explicitly"); });
});
