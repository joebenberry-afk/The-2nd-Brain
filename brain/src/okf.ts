/**
 * Export to an Open Knowledge Format v0.2 bundle (github.com/GoogleCloudPlatform/open-knowledge-format):
 * one concept per public note, an index.md per folder, so OKF readers (graph views, MCP servers,
 * other agents) can read the Brain. One way only: notes/ stays the truth. Private notes never
 * leave the machine.
 */
import { existsSync, readdirSync, rmSync } from "node:fs";
import { isAbsolute, join, relative, resolve, win32 } from "node:path";
import { GLOBAL, headline, KINDS, restOfBody, type Note } from "./notes.ts";
import { writeAtomic } from "./util.ts";

export const OKF_VERSION = "0.2";
/** Marks a folder this exporter wrote: a re-export replaces it, and nothing else. */
const MARKER = ".brain-okf-export";

/** OKF actors (§7) for a note's `source` and `tested_by`; the Brain records no model or person id. */
const GENERATED_BY: Record<string, string> = {
  user: "human:owner",
  agent: "agent/unrecorded",
  capture: "process:brain-capture",
  commit: "process:brain-commit",
  convert: "process:brain-convert",
};
const VERIFIED_BY: Record<string, string> = {
  owner: "human:owner",
  agent: "agent/unrecorded",
  capture: "process:brain-capture",
  convert: "process:brain-convert",
};

export interface ExportReport {
  concepts: number;
  projects: number;
  /** Private notes left out. */
  private: number;
}

/** A YAML double-quoted scalar: JSON strings are valid YAML. */
const q = (value: string) => JSON.stringify(value);

const isInside = (child: string, parent: string) => {
  const rel = relative(parent, child);
  return rel === "" || (!!rel && !rel.startsWith("..") && !isAbsolute(rel));
};

/** Text for a markdown link label or list item: one line, brackets escaped. */
const inline = (text: string) => text.replace(/\s+/g, " ").trim().replace(/([[\]])/g, "\\$1");

function description(note: Note): string | undefined {
  const sentence = restOfBody(note).split(/(?<=[.!?])\s+/)[0]?.trim();
  if (!sentence) return undefined;
  return sentence.length <= 200 ? sentence : `${sentence.slice(0, 199).trimEnd()}…`;
}

/** File evidence is relative to a project checkout, not to the bundle: say so instead of linking. */
function source(evidence: string, project: string): string {
  const scheme = /^[a-z][a-z\d+.-]*:/i.test(evidence) && !/^[a-z]:[\\/]/i.test(evidence);
  if (scheme || isAbsolute(evidence) || win32.isAbsolute(evidence)) return evidence;
  return `${evidence} in the ${project === GLOBAL ? "project" : project} checkout`;
}

function concept(note: Note, exported: Map<string, Note>): string {
  const lines = ["---", `type: ${q(note.kind[0]!.toUpperCase() + note.kind.slice(1))}`, `title: ${q(headline(note))}`];
  const about = description(note);
  if (about) lines.push(`description: ${q(about)}`);
  if (note.tags.length) lines.push(`tags: [${note.tags.map(q).join(", ")}]`);
  lines.push(`generated: { by: ${q(GENERATED_BY[note.source] ?? `process:brain-${note.source}`)}, at: ${q(note.at)} }`);
  if (note.tested) {
    const by = (note.testedBy && VERIFIED_BY[note.testedBy]) ?? "process:unrecorded";
    lines.push(`verified: { by: ${q(by)}, at: ${q(note.testedAt ?? note.at)} }`);
  }
  if (note.retired) lines.push("status: deprecated");
  // OKF timestamps carry an explicit offset; a bare date means its start, UTC.
  if (note.staleAfter) lines.push(`stale_after: ${q(note.staleAfter.length === 10 ? `${note.staleAfter}T00:00:00Z` : note.staleAfter)}`);
  if (note.evidence.length) {
    lines.push("sources:");
    for (const e of note.evidence) lines.push(`  - resource: ${q(source(e, note.project))}`);
  }
  // Brain fields with no OKF equivalent, kept as extension keys (§4.1).
  if (note.errors.length) lines.push(`errors: [${note.errors.map(q).join(", ")}]`);
  if (note.host) lines.push(`host: ${q(note.host)}`);
  if (note.replaces) lines.push(`replaces: ${q(note.replaces)}`);
  if (note.replacedBy) lines.push(`replaced_by: ${q(note.replacedBy)}`);
  if (note.retired) lines.push(`retired: ${q(note.retired)}`);
  lines.push("---", "", note.body.trim());
  // Lineage as links (§6.1), only to notes in the bundle.
  const link = (id: string | undefined, label: string) => {
    const target = id ? exported.get(id) : undefined;
    return target ? `${label} [${target.id}](/${target.project}/${target.id}.md).` : "";
  };
  const lineage = [link(note.replaces, "Replaces"), link(note.replacedBy, "Replaced by")].filter(Boolean);
  if (lineage.length) lines.push("", lineage.join(" "));
  lines.push("");
  return lines.join("\n");
}

function projectIndex(notes: Note[]): string {
  const sections: string[] = [];
  const entry = (n: Note) => {
    const about = description(n);
    return `* [${inline(headline(n))}](${n.id}.md)${about ? ` - ${inline(about)}` : ""}`;
  };
  for (const kind of KINDS) {
    const active = notes.filter((n) => !n.retired && n.kind === kind);
    if (active.length) sections.push(`# ${kind[0]!.toUpperCase()}${kind.slice(1)}\n\n${active.map(entry).join("\n")}`);
  }
  const retired = notes.filter((n) => n.retired);
  if (retired.length) sections.push(`# Deprecated\n\n${retired.map(entry).join("\n")}`);
  return sections.join("\n\n") + "\n";
}

/**
 * Write every public note under `dir` as an OKF bundle. `dir` must be new, empty, or an earlier
 * export (then it is replaced); it may not lie in the Brain home, except under its local `state/`.
 */
export function exportOkf(home: string, notes: Note[], dir: string): ExportReport {
  const target = resolve(dir);
  const brain = resolve(home);
  if (isInside(target, brain) && !isInside(target, join(brain, "state"))) {
    throw new Error(`${target} is inside the Brain home; export outside it or under ${join(brain, "state")}`);
  }
  if (existsSync(target)) {
    const entries = readdirSync(target);
    if (entries.length && !entries.includes(MARKER)) throw new Error(`${target} is not empty and holds no earlier Brain export; choose an empty folder`);
    if (entries.length) rmSync(target, { recursive: true, force: true });
  }
  const shown = notes.filter((n) => !n.private).sort((a, b) => (a.project < b.project ? -1 : a.project > b.project ? 1 : a.id < b.id ? -1 : 1));
  const exported = new Map(shown.map((n) => [n.id, n]));
  const byProject = new Map<string, Note[]>();
  for (const note of shown) {
    const list = byProject.get(note.project) ?? [];
    list.push(note);
    byProject.set(note.project, list);
  }
  for (const [project, list] of byProject) {
    for (const note of list) writeAtomic(join(target, project, `${note.id}.md`), concept(note, exported));
    writeAtomic(join(target, project, "index.md"), projectIndex(list));
  }
  const projects = [...byProject].map(([project, list]) => {
    const active = list.filter((n) => !n.retired).length;
    return `* [${project}](${project}/) - ${active} current note${active === 1 ? "" : "s"}${list.length > active ? `, ${list.length - active} deprecated` : ""}`;
  });
  writeAtomic(join(target, "index.md"), `---\nokf_version: ${q(OKF_VERSION)}\n---\n\n# Projects\n\n${projects.join("\n")}\n`);
  writeAtomic(join(target, MARKER), "Written by `brain export`; the next export replaces this folder.\n");
  return { concepts: shown.length, projects: byProject.size, private: notes.length - shown.length };
}
