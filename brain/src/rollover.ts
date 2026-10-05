import { createHash } from "node:crypto";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { loadProjects } from "./project.ts";
import { estimateTokens } from "./util.ts";

/** A local atomic latch survives hook processes and OMP restarts; never session text. */
export function rolloverHint(home: string, project: string, session: string, tokens: unknown, sub = false): string {
  if (sub || typeof tokens !== "number" || !Number.isFinite(tokens) || tokens < 0) return "";
  const configured = loadProjects(home)[project]?.rollover;
  const threshold = typeof configured === "number" && Number.isFinite(configured) && configured >= 0 ? configured : 250_000;
  const directory = join(home, "state", "rollover");
  const latch = join(directory, createHash("sha256").update(project + "\0" + session).digest("hex"));
  try {
    if (!threshold || tokens <= threshold) {
      rmSync(latch, { force: true, recursive: true });
      return "";
    }
    const text = `Brain: context ${Math.ceil(tokens / 1000)}k. Save brain_state (Goal/Next/See:) and start a fresh session; the card carries it over.`;
    if (estimateTokens(text) > 40) return "";
    mkdirSync(directory, { recursive: true });
    mkdirSync(latch); // EEXIST means this crossing was already shown, including concurrent hooks.
    return text;
  } catch {
    return ""; // A locked/missing home never interrupts a host session.
  }
}
