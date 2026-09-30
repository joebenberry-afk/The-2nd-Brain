/** Explicit project plans, read fresh from the checkout; never a derived index. */
import { readFileSync } from "node:fs";
import { basename, isAbsolute, relative } from "node:path";
import { docFile, loadProjects, projectDocPath, type Project } from "./project.ts";
import { fold, tokens } from "./search.ts";
import { cutToTokens } from "./util.ts";

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

/**
 * One best heading pointer, or a short H2 outline when a query names a registered doc. A heading
 * answer carries an excerpt (heading and first paragraph) so recall can check it like a note; the
 * judge scrubs it before cutting it to 450 characters, so it is only bounded here.
 */
export function docAnswer(home: string, project: Project, query: string): { text: string; path: string; excerpt?: string } | undefined {
  const terms = tokens(query, true);
  if (!terms.length || !project.root) return undefined;
  const files = projectDocs(home, project);
  // A doc is named by its whole file name, with or without folders: "release_plan.md" is not
  // "release-plan.md", and "Café.md" is "cafe.md". The named word then leaves the search terms.
  const queryWords = fold(query).split(/[^\p{L}\p{N}._\-/\\]+/u).map(word => word.replace(/\.+$/, ""));
  const names = queryWords.map(word => word.split(/[\\/]/).filter(Boolean).pop() ?? "");
  const named = files.filter(file => names.includes(fold(basename(file))));
  const namedNames = new Set(named.map(file => fold(basename(file))));
  const rest = tokens(queryWords.filter((_, i) => !namedNames.has(names[i]!)).join(" "), true);
  let best: { score: number; text: string; path: string; excerpt: string } | undefined;
  let outline: { text: string; path: string } | undefined;
  for (const file of named.length ? named : files) {
    // Spelled from the repo, so it opens from the agent's cwd; a doc outside the repo (in the declared
    // folder around it) against that folder, the spelling a See: anchor can take.
    const fromRoot = relative(project.root, file);
    const outside = /^\.\.(?:[\\/]|$)/.test(fromRoot) || isAbsolute(fromRoot);
    const path = (outside && project.docRoot ? relative(project.docRoot, file) : fromRoot).replace(/\\/g, "/");
    const headings = sections(file);
    const remaining = named.length ? rest : terms;
    if (named.length && !outline) {
      const h2 = headings.filter(section => section.level === 2).map(section => section.heading);
      if (h2.length) outline = { text: cutToTokens(path + ": " + h2.join(" · "), 30), path };
    }
    for (const section of headings) {
      const heading = new Set(tokens(section.heading, true));
      const words = new Set(tokens((named.length ? "" : path + " ") + section.heading + " " + (section.text.split(/\n\s*\n/)[0] ?? ""), true));
      const matched = remaining.filter(term => words.has(term));
      if (matched.length < (named.length ? 1 : Math.min(2, terms.length))) continue;
      const score = matched.length * 2 + matched.filter(term => heading.has(term)).length;
      if (!best || score > best.score) best = { score, text: path + " › " + section.heading + " (line " + section.line + ")", path, excerpt: `${section.heading}: ${section.text.split(/\n\s*\n/)[0] ?? ""}`.replace(/\s+/g, " ").slice(0, 4000) };
    }
  }
  return best ? { text: best.text, path: best.path, excerpt: best.excerpt } : outline;
}
