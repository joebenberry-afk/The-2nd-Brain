/** Shared Brain tools; transports supply identity, rendering and telemetry. */
import { createNote, differentBody, findNote, findSameHeadline, GLOBAL, KINDS, loadNotes, retireNote, upgradeNote, type Kind } from "./notes.ts";
import { resolveProject } from "./project.ts";
import { judgedAnswer, typesafeJudge, typesafePairJudge, type ToraRecall } from "./judge.ts";
import { toraScorer } from "./tora.ts";
import type { UseKind } from "./telemetry.ts";
import { stateSaved, writeWork } from "./work.ts";
import { noteHint } from "./tidy.ts";
import { autoEvidence, sessionEdits } from "./capture.ts";

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
  edited?: string[];
}

type ToolResult = { text: string; kind?: UseKind; project: string; hits?: number; query?: string; ids?: string[]; judged?: boolean; dropped?: number; tora?: ToraRecall };

export interface BrainTool {
  name: string;
  description: string;
  params: Record<string, Param>;
  run(params: Record<string, unknown>, context: ToolContext): ToolResult | Promise<ToolResult>;
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
    description: "Before exploring unfamiliar ground, choosing a tool/stack, or retrying a failing command; call it in the same batch as your first search or read, since a recall alone costs a full turn. A note id returns the full note.",
    params: { query: { type: "string", description: "a question, keywords, or a note id" }, all: { type: "boolean", description: "search every project", optional: true } },
    async run(params, { home, cwd, env }) {
      const query = requireString(params.query, "query");
      const project = resolveProject(home, cwd, env);
      return { ...await judgedAnswer(loadNotes(home).notes, query, { home, project, all: params.all === true }, typesafeJudge(env), toraScorer(env), env.BRAIN_TORA_SKIP === "on"), query, kind: "recall", project: project.id };
    },
  },
  {
    name: "brain_note",
    description: "Save what the repo cannot tell you: a decision and why, an environment gotcha with its error line, what failed before, an owner preference. Not facts readable from code. replaces: id of a note this corrects.",
    params: {
      text: { type: "string", description: "the learning; first line is the headline" },
      kind: { type: "string", description: `one of ${KINDS.join(", ")}`, optional: true },
      error: { type: "string", description: "the error message this fixes", optional: true },
      tested: { type: "boolean", description: "you verified it works", optional: true },
      global: { type: "boolean", description: "useful beyond this project", optional: true },
      replaces: { type: "string", description: "id of a note this corrects", optional: true },
    },
    async run(params, { home, cwd, env, sub, session, edited }) {
      const text = requireString(params.text, "text");
      // As the CLI does: a kind silently stored as "note" loses the classification without a word.
      const kind = (params.kind == null || params.kind === "" ? undefined : String(params.kind)) as Kind | undefined;
      if (kind !== undefined && !(KINDS as readonly string[]).includes(kind)) throw new Error(`unknown kind ${kind} (${KINDS.join(", ")})`);
      const error = typeof params.error === "string" && params.error.trim() ? params.error.trim() : undefined;
      const project = resolveProject(home, cwd, env);
      const scope = params.global === true ? GLOBAL : project.id;
      const notes = loadNotes(home).notes;
      const replaces = params.replaces === undefined ? undefined : requireString(params.replaces, "replaces");
      const old = replaces === undefined ? undefined : findNote(notes, replaces);
      if (replaces !== undefined && !old) throw new Error(`no note ${replaces}`);
      if (old?.retired) throw new Error(`${old.id} is already retired`);
      const same = replaces === undefined ? findSameHeadline(notes, text, scope, project.tags) : undefined;
      if (same && differentBody(same, text)) return { text: `not saved: ${same.id} has this headline with a different body; use a new headline, or \`brain retire ${same.id}\` first`, kind: "note", project: project.id };
      // Only a parent can vouch for a project fix; global fixes need the owner's confirmation.
      const wantsTested = params.tested === true;
      const tested = wantsTested && !sub && (same?.project ?? scope) !== GLOBAL;
      const untested = same?.tested ? "" : sub ? " (untested: the parent or `brain tested <id>` confirms)"
        : wantsTested && !tested ?" (untested: the owner confirms a global fix with `brain tested <id>`)" : "";
      if (same) {
        const upgraded = upgradeNote(home, same, { kind, errors: error ? [error] : [], tested, testedBy: "agent", evidenceRoots: [project.root, project.docRoot].filter((root): root is string => !!root) });
        return { text: `${upgraded ? "updated" : "already noted"} ${same.id}${untested}`, kind: "note", project: project.id };
      }
      const note = createNote(home, { text, project: scope, kind, errors: error ? [error] : [], evidence: autoEvidence(text, project.root, project.root ? (edited ?? (session ? sessionEdits(home, session, project.root) : [])) : []), tested, testedBy: "agent", evidenceRoots: [project.root, project.docRoot].filter((root): root is string => !!root), source: "agent" });
      if (old) retireNote(home, old.id, note.id);
      const hint = sub ? "" : await noteHint(home, note, loadNotes(home).notes, typesafePairJudge(env));
      return { text: `saved ${note.id}${old ? ` (retired ${old.id})` : ""}${untested}${hint}`, kind: "note", project: project.id };
    },
  },
  {
    name: "brain_state",
    description: "When the goal or next step changes, save working state: Goal:/Next:/Watch out:/Done:, under 60 words. See: path#heading keeps it anchored to the repo plan.",
    params: { text: { type: "string", description: "goal, done, next, watch out" } },
    run(params, { home, cwd, env, sub }) {
      const project = resolveProject(home, cwd, env);
      if (sub) return { text: "not saved: working state belongs to the parent session", project: project.id };
      const work = writeWork(home, project.id, requireString(params.text, "text"));
      return { text: stateSaved(work, home, project), kind: "state", project: project.id };
    },
  },
];
