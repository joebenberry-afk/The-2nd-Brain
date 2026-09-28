/** Shared Brain tools; transports supply identity, rendering and telemetry. */
import { createNote, differentBody, findSameHeadline, GLOBAL, KINDS, loadNotes, upgradeNote, type Kind } from "./notes.ts";
import { resolveProject } from "./project.ts";
import { answerWithHits } from "./search.ts";
import type { UseKind } from "./telemetry.ts";
import { stateSaved, writeWork } from "./work.ts";

export interface Param {
  type: "string" | "boolean";
  description: string;
  optional?: boolean;
}

export interface ToolContext {
  home: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
  sub: boolean;
  session: string | undefined;
}

export interface BrainTool {
  name: string;
  description: string;
  params: Record<string, Param>;
  run(params: Record<string, unknown>, context: ToolContext): { text: string; kind?: UseKind; project: string; hits?: number };
}

export function jsonSchema(props: Record<string, Param>) {
  return {
    type: "object",
    properties: Object.fromEntries(Object.entries(props).map(([k, p]) => [k, { type: p.type, description: p.description }])),
    required: Object.entries(props).filter(([, p]) => !p.optional).map(([k]) => k),
    additionalProperties: false,
  };
}

function requireString(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${name} is required`);
  return value;
}

export const brainTools: BrainTool[] = [
  {
    name: "brain_recall",
    description: "Before exploring unfamiliar ground, choosing a tool/stack, or retrying a failing command: cheaper than re-reading files. A note id returns the full note.",
    params: { query: { type: "string", description: "a question, keywords, or a note id" }, all: { type: "boolean", description: "search every project", optional: true } },
    run(params, { home, cwd, env }) {
      const query = requireString(params.query, "query");
      const project = resolveProject(home, cwd, env);
      return { ...answerWithHits(loadNotes(home).notes, query, { home, project, all: params.all === true }), kind: "recall", project: project.id };
    },
  },
  {
    name: "brain_note",
    description: "Save what the repo cannot tell you: a decision and why, an environment gotcha with its error line, what failed before, an owner preference. Not facts readable from code.",
    params: {
      text: { type: "string", description: "the learning; first line is the headline" },
      kind: { type: "string", description: `one of ${KINDS.join(", ")}`, optional: true },
      error: { type: "string", description: "the error message this fixes", optional: true },
      tested: { type: "boolean", description: "you verified it works", optional: true },
      global: { type: "boolean", description: "useful beyond this project", optional: true },
    },
    run(params, { home, cwd, env, sub }) {
      const text = requireString(params.text, "text");
      const kind = typeof params.kind === "string" && (KINDS as readonly string[]).includes(params.kind) ? (params.kind as Kind) : undefined;
      const error = typeof params.error === "string" && params.error.trim() ? params.error.trim() : undefined;
      const project = resolveProject(home, cwd, env);
      const scope = params.global === true ? GLOBAL : project.id;
      const same = findSameHeadline(loadNotes(home).notes, text, scope, project.tags);
      if (same && differentBody(same, text)) return { text: `not saved: ${same.id} has this headline with a different body; use a new headline, or \`brain retire ${same.id}\` first`, kind: "note", project: project.id };
      // Only a parent can vouch for a project fix; global fixes need the owner's confirmation.
      const wantsTested = params.tested === true;
      const tested = wantsTested && !sub && (same?.project ?? scope) !== GLOBAL;
      const untested = sub ? " (untested: the parent or `brain tested <id>` confirms)"
        : wantsTested && !tested ? " (untested: a global fix is confirmed with `brain tested <id>`)" : "";
      if (same) {
        const upgraded = upgradeNote(home, same, { kind, errors: error ? [error] : [], tested });
        return { text: `${upgraded ? "updated" : "already noted"} ${same.id}${untested}`, kind: "note", project: project.id };
      }
      const note = createNote(home, { text, project: scope, kind, errors: error ? [error] : [], tested, source: "agent" });
      return { text: `saved ${note.id}${untested}`, kind: "note", project: project.id };
    },
  },
  {
    name: "brain_state",
    description: "When the goal or next step changes, save working state for resuming: Goal:/Next:/Watch out:/Done:, under 60 words.",
    params: { text: { type: "string", description: "goal, done, next, watch out" } },
    run(params, { home, cwd, env, sub }) {
      const project = resolveProject(home, cwd, env);
      if (sub) return { text: "not saved: working state belongs to the parent session", project: project.id };
      const work = writeWork(home, project.id, requireString(params.text, "text"));
      return { text: stateSaved(work), kind: "state", project: project.id };
    },
  },
];
