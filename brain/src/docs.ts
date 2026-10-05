/** Explicit project plans, read fresh from the checkout; never a derived index. */
import { spawnSync } from "node:child_process";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { docFile, loadProjects, normalizePath, projectDocPath, type Project } from "./project.ts";
import { fold, tokens } from "./search.ts";
import { cutToTokens } from "./util.ts";
import { parseEvent } from "./capture.ts";

/** Plan docs explicitly listed in projects.json, resolved under project.root (else project.docRoot). */
export function projectDocs(home: string, project: Project): string[] {
  const docs = loadProjects(home)[project.id]?.docs;
  if (!Array.isArray(docs)) return [];
  return [...new Set(docs.flatMap(path => {
    const file = typeof path === "string" ? docFile(project, path) : undefined;
    return file ? [file] : [];
  }))];
}

interface Section { heading: string; slug: string; level: number; line: number; text: string }

/** Heading text as shown: links, HTML, backticks and emphasis stars removed. */
const headingText = (text: string) => text.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/<[^>]*>/g, "").replace(/[`*]/g, "");
/** GitHub-style anchor slug of heading text ("6. Kill rules (V4)" → "6-kill-rules-v4"). */
const slugOf = (text: string) => headingText(text).toLowerCase().replace(/[^\p{L}\p{N}\p{M}_\-\s]/gu, "").replace(/\s/g, "-");

/** A See: anchor as written: surrounding backticks, quotes or angle brackets removed. */
export const bareAnchor = (anchor: string) => anchor.trim().replace(/^[`"'<]+|[`"'>]+$/g, "");

/** ATX and setext headings; fenced examples cannot create anchors. */
function sections(file: string): Section[] {
  let lines: string[];
  try { lines = readFileSync(file, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/); } catch { return []; }
  const found: Array<Section & { start: number }> = [];
  const used = new Set<string>();
  let fence = "", fenceLength = 0;
  const frontEnd = lines[0] === "---" ? lines.findIndex((line, i) => i > 0 && /^(?:---|\.\.\.)[ \t]*$/.test(line)) : -1;
  for (let i = frontEnd + 1; i < lines.length; i++) {
    const line = lines[i]!;
    const fenced = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (fenced) {
      if (!fence) { fence = fenced[1]![0]!; fenceLength = fenced[1]!.length; }
      else if (fenced[1]![0] === fence && fenced[1]!.length >= fenceLength && !fenced[2]!.trim()) fence = "";
      continue;
    }
    if (fence) continue;
    const atx = /^ {0,3}#{1,6}(?:[ \t]+(.*?)|[ \t]*)$/.exec(line);
    const setext = !atx && line.trim() && !/^ {4}|^\t/.test(line) && /^ {0,3}(?:=+|-+)[ \t]*$/.test(lines[i + 1] ?? "");
    if (!atx && !setext) continue;
    const raw = (atx ? atx[1] ?? "" : line).replace(/[ \t]+#+[ \t]*$/, "").trim();
    const heading = headingText(raw);
    const base = slugOf(raw);
    let slug = base, suffix = 0;
    while (used.has(slug)) slug = `${base}-${++suffix}`;
    used.add(slug);
    const level = atx ? line.trimStart().match(/^#+/)![0].length : lines[i + 1]!.trimStart().startsWith("=") ? 1 : 2;
    found.push({ heading, slug, level, line: i + 1, start: i + (setext ? 2 : 1), text: "" });
    if (setext) i++;
  }
  return found.map((section, i) => {
    const body = lines.slice(section.start, found[i + 1] ? found[i + 1]!.line - 1 : lines.length);
    while (body.length && !body[0]!.trim()) body.shift();
    while (body.length && !body[body.length - 1]!.trim()) body.pop();
    return { ...section, text: body.join("\n") };
  });
}

/** Heading metadata and current text for a single safe repo-relative Markdown anchor. */
export function anchorSection(root: string, anchor: string): Section | undefined {
  anchor = bareAnchor(anchor);
  const hash = anchor.indexOf("#");
  if (hash <= 0 || hash === anchor.length - 1) return undefined;
  const file = projectDocPath(root, anchor.slice(0, hash));
  if (!file) return undefined;
  let fragment = anchor.slice(hash + 1);
  try { fragment = decodeURIComponent(fragment); } catch { /* not percent-encoded: keep it as written */ }
  // The exact slug first, so a duplicate's "foo-1" keeps its own section; then heading text or case.
  const all = sections(file);
  return all.find(section => section.slug === fragment) ?? all.find(section => section.slug === slugOf(fragment));
}

/** Text under one heading, excluding the heading itself; missing targets never return stale text. */
export function readAnchor(root: string, anchor: string): string | undefined {
  return anchorSection(root, anchor)?.text;
}

interface SearchSection extends Section { headingWords: Set<string>; words: Set<string> }
interface SearchDoc { path: string; headings: SearchSection[]; pathWords: Set<string> }
type DocAnswer = { text: string; path: string; excerpt?: string };

function searchDoc(file: string, path: string): SearchDoc {
  return { path, pathWords: new Set(tokens(path, true, false)), headings: sections(file).map(section => ({
    ...section, headingWords: new Set(tokens(section.heading, true, false)),
    words: new Set(tokens(section.heading + " " + section.text, true, false)),
  })) };
}

/** More distinct terms always win; heading matches break ties. Unnamed queries need two. */
function sectionScore(section: SearchSection, doc: SearchDoc, terms: string[], named: boolean): number {
  const matched = terms.filter(term => section.words.has(term) || (!named && doc.pathWords.has(term)));
  if (matched.length < (named ? 1 : 2)) return 0;
  return matched.length * (terms.length + 1) + matched.filter(term => section.headingWords.has(term)).length;
}

function bestParagraph(section: Section, terms: string[]): string {
  let best = "", score = -1;
  for (const paragraph of section.text.split(/\n\s*\n/)) {
    const words = new Set(tokens(paragraph, true, false));
    const matched = terms.filter(term => words.has(term)).length;
    if (matched > score) { best = paragraph; score = matched; }
  }
  return best;
}

function answerDocs(docs: SearchDoc[], query: string): DocAnswer | undefined {
  const terms = tokens(query, true, false);
  if (!terms.length) return undefined;
  // Whole file names, not look-alikes: release_plan.md differs from release-plan.md.
  const queryWords = fold(query).split(/[^\p{L}\p{N}._\-/\\]+/u).map(word => word.replace(/\.+$/, ""));
  const names = queryWords.map(word => word.split(/[\\/]/).filter(Boolean).pop() ?? "");
  const named = docs.filter(doc => names.includes(fold(basename(doc.path))));
  const namedNames = new Set(named.map(doc => fold(basename(doc.path))));
  const remaining = named.length ? tokens(queryWords.filter((_, i) => !namedNames.has(names[i]!)).join(" "), true, false) : terms;
  let best: { score: number; section: SearchSection; doc: SearchDoc } | undefined;
  let outline: DocAnswer | undefined;
  for (const doc of named.length ? named : docs) {
    if (named.length && !outline) {
      const h2 = doc.headings.filter(section => section.level === 2).map(section => section.heading);
      if (h2.length) outline = { text: cutToTokens(doc.path + ": " + h2.join(" · "), 30), path: doc.path };
    }
    for (const section of doc.headings) {
      const score = sectionScore(section, doc, remaining, named.length > 0);
      if (score && (!best || score > best.score)) best = { score, section, doc };
    }
  }
  if (!best) return outline;
  const { section, doc } = best;
  return {
    text: doc.path + " › " + section.heading + " (line " + section.line + ")", path: doc.path,
    excerpt: (section.heading + ": " + bestParagraph(section, remaining)).replace(/\s+/g, " ").slice(0, 4000),
  };
}

/** Search whole registered sections; the judge receives the heading and best-matching paragraph. */
export function docAnswer(home: string, project: Project, query: string): DocAnswer | undefined {
  if (!project.root || !tokens(query, true, false).length) return undefined;
  const docs = projectDocs(home, project).map(file => {
    // Docs outside the checkout use the declared folder's spelling, as See: anchors do.
    const fromRoot = relative(project.root!, file);
    const outside = /^\.\.(?:[\\/]|$)/.test(fromRoot) || isAbsolute(fromRoot);
    const path = (outside && project.docRoot ? relative(project.docRoot, file) : fromRoot).replace(/\\/g, "/");
    return searchDoc(file, path);
  });
  return answerDocs(docs, query);
}

/** Live child navigation: registered docs plus safe relative Markdown paths explicitly in the brief. */
export function childDocContext(home: string, project: Project, brief = ""): { outline: string; section?: string } {
  const root = project.root ?? project.docRoot;
  if (!root) return { outline: "" };
  const named = [...brief.matchAll(/(?:^|[\s`"'(<])([^\s`"'<>():#]+\.md)(?=$|[\s`"'>)#:,.;])/gi)]
    .flatMap(match => { const file = docFile(project, match[1]!); return file ? [file] : []; });
  const files = [...new Set([...named, ...projectDocs(home, project)])];
  const terms = new Set(tokens(brief, true));
  const outline: string[] = [];
  let best: { score: number; text: string } | undefined;
  for (const file of files) {
    const fromRoot = relative(root, file);
    const outside = /^\.\.(?:[\\/]|$)/.test(fromRoot) || isAbsolute(fromRoot);
    const path = (outside && project.docRoot ? relative(project.docRoot, file) : fromRoot).replace(/\\/g, "/");
    for (const heading of sections(file)) {
      if (heading.level !== 2 && heading.level !== 3) continue;
      const line = path + ":" + heading.line + " " + heading.heading;
      if ([...outline, line].join("\n").length <= 60 * 4) outline.push(line);
      const score = [...new Set(tokens(heading.heading, true))].filter(word => terms.has(word)).length;
      if (score && heading.text && (!best || score > best.score)) best = { score, text: line + "\n" + heading.text };
    }
  }
  // Full section or silence: clipping a task specification would hide requirements.
  return { outline: outline.join("\n"), section: best && best.text.length <= 120 * 4 ? best.text : undefined };
}

const SCAN_FILES = 2000, SCAN_BYTES = 512 * 1024;

/** Git's tracked Markdown files, otherwise a bounded walk without hidden/dependency directories. */
function markdownFiles(root: string): string[] {
  try {
    const git = spawnSync("git", ["ls-files", "-z", "--", "*.md"], { cwd: root, encoding: "utf8", timeout: 5000, maxBuffer: 4 * 1024 * 1024, windowsHide: true });
    if (git.status === 0) return git.stdout.split("\0").filter(Boolean).sort().slice(0, SCAN_FILES);
  } catch { /* git unavailable: walk below */ }
  const files: string[] = [];
  let visited = 0;
  const walk = (dir: string, depth: number): void => {
    if (depth > 20 || files.length >= SCAN_FILES || visited >= 20_000) return;
    try {
      for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
        if (++visited > 20_000 || files.length >= SCAN_FILES) break;
        if (entry.name.startsWith(".") || entry.name === "node_modules") continue;
        const file = join(dir, entry.name);
        if (entry.isDirectory()) walk(file, depth + 1);
        else if (entry.isFile() && /\.md$/i.test(entry.name)) files.push(relative(root, file).replace(/\\/g, "/"));
      }
    } catch { /* unreadable directory: keep the readable candidates */ }
  };
  walk(root, 0);
  return files;
}

function unansweredQueries(home: string, project: string, now: Date): string[] {
  const queries = new Map<string, string>();
  const since = now.getTime() - 30 * 86_400_000;
  for (const name of ["telemetry.1.jsonl", "telemetry.jsonl"]) {
    let text: string;
    try { text = readFileSync(join(home, "state", name), "utf8"); } catch { continue; }
    for (const line of text.split("\n")) {
      try {
        const row = JSON.parse(line) as { at?: unknown; kind?: unknown; project?: unknown; query?: unknown; hits?: unknown; ids?: unknown };
        if (row.kind !== "recall" || row.project !== project || typeof row.query !== "string" || !row.query.trim() || typeof row.at !== "string") continue;
        const at = Date.parse(row.at);
        if (!(at >= since && at <= now.getTime())) continue;
        if (row.hits !== 0 && !(Array.isArray(row.ids) && row.ids.some(id => typeof id === "string" && id.startsWith("doc:")))) continue;
        const key = fold(row.query).trim().replace(/\s+/g, " ");
        queries.set(key, row.query);
      } catch { /* partial/malformed telemetry rows are not queries */ }
    }
  }
  return [...queries.values()];
}

/** Distinct sessions reading each file in full; paths only, never document contents. */
function fullDocReads(home: string, now: Date): Map<string, Set<string>> {
  const reads = new Map<string, Set<string>>(), dir = join(home, "state", "events");
  let names: string[];
  try { names = readdirSync(dir).filter(name => name.endsWith(".jsonl")); } catch { return reads; }
  const since = now.getTime() - 30 * 86_400_000;
  for (const name of names) {
    let text: string;
    try { text = readFileSync(join(dir, name), "utf8"); } catch { continue; }
    for (const line of text.split("\n")) {
      const event = parseEvent(line);
      if (!event || !event.ok || !/^(?:read|Read)$/.test(event.tool) || !event.path || event.fullRead === false || !event.session) continue;
      if (!/\.md$/i.test(event.path) || /(?:^|[\\/])notes[\\/][^\\/]+[\\/]private(?:[\\/]|$)/i.test(event.path)) continue;
      const at = Date.parse(event.at);
      if (!(at >= since && at <= now.getTime())) continue;
      const path = normalizePath(resolve(event.cwd, event.path));
      const sessions = reads.get(path) ?? new Set<string>();
      sessions.add(event.session); reads.set(path, sessions);
    }
  }
  return reads;
}

/** Local-only registration suggestions. Never writes configuration or sends documents to a judge. */
export function suggestDocs(home: string, project: Project, opts: { limit?: number; now?: Date } = {}): { path: string; queries: number; reads: number }[] {
  if (!project.root) return [];
  const queries = unansweredQueries(home, project.id, opts.now ?? new Date());
  const reads = fullDocReads(home, opts.now ?? new Date());
  if (!queries.length && !reads.size) return [];
  const registered = new Set(projectDocs(home, project).map(normalizePath));
  const suggestions: { path: string; queries: number; reads: number }[] = [];
  for (const path of markdownFiles(project.root)) {
    const file = projectDocPath(project.root, path);
    if (!file || registered.has(normalizePath(file))) continue;
    try { if (statSync(file).size > SCAN_BYTES) continue; } catch { continue; }
    const doc = searchDoc(file, path);
    const count = queries.filter(query => answerDocs([doc], query) !== undefined).length;
    const fullReads = reads.get(normalizePath(file))?.size ?? 0;
    if (count || fullReads) suggestions.push({ path, queries: count, reads: fullReads });
  }
  return suggestions.sort((a, b) => (b.queries + b.reads) - (a.queries + a.reads) || b.queries - a.queries || a.path.localeCompare(b.path)).slice(0, opts.limit ?? 5);
}
