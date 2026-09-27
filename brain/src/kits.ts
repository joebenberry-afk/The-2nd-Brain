/** MVP kits (Agent Skills format). */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { estimateTokens, slug, tagList, writeAtomic } from "./util.ts";
import { parseFrontmatter, type Note, isActive } from "./notes.ts";
import type { Project } from "./project.ts";

export class KitError extends Error {}

export const KIT_BUDGET = 600;

export interface Kit {
  name: string;
  description: string;
  tags: string[];
  path: string;
  body: string;
}

export function kitsDir(home: string): string {
  return join(home, "kits");
}

export function loadKits(home: string): Kit[] {
  const dir = kitsDir(home);
  if (!existsSync(dir)) return [];

  const kits: Kit[] = [];
  let names: string[];
  try {
    names = readdirSync(dir, { withFileTypes: true })
      .filter((d) => d.isDirectory() && !d.name.startsWith("."))
      .map((d) => d.name)
      .sort();
  } catch {
    return [];
  }

  for (const name of names) {
    const skillPath = join(dir, name, "SKILL.md");
    try {
      const text = readFileSync(skillPath, "utf8");
      const { fields, body } = parseFrontmatter(text);

      const description = fields.get("description");
      if (!description || (Array.isArray(description) && !description.length)) {
        continue;
      }

      const kitName = (fields.get("name") as string) ?? name;
      const tagsRaw = fields.get("tags");
      let tags: string[] = [];
      if (Array.isArray(tagsRaw)) {
        tags = tagList(tagsRaw.filter((t): t is string => typeof t === "string"));
      }

      kits.push({
        name: kitName,
        description: Array.isArray(description) ? description.join("\n") : description,
        tags,
        path: skillPath,
        body,
      });
    } catch {
      // Skip kits that fail to parse
      continue;
    }
  }

  return kits;
}

export function findKit(kits: Kit[], name: string): Kit | undefined {
  return kits.find((k) => k.name === name);
}

export function kitsFor(kits: Kit[], project: Project): Kit[] {
  return kits.filter((kit) => kit.tags.some((tag) => project.tags.includes(tag)));
}

export function draftKit(
  home: string,
  name: string,
  project: string,
  notes: Note[],
  tags?: string[],
): Kit {
  const slugName = slug(name);
  const kitPath = join(kitsDir(home), slugName);
  const skillPath = join(kitPath, "SKILL.md");

  if (existsSync(skillPath)) {
    throw new KitError(`${slugName} already has a SKILL.md`);
  }

  // Filter to active notes in this project
  // Kits are synced and shared: private notes never go into one.
  const projectNotes = notes.filter((n) => n.project === project && isActive(n) && !n.private);

  // Collect notes by kind
  const decisions = projectNotes
    .filter((n) => n.kind === "decision")
    .sort((a, b) => (a.at > b.at ? -1 : a.at < b.at ? 1 : 0));
  const procedures = projectNotes
    .filter((n) => n.kind === "procedure")
    .sort((a, b) => (a.at > b.at ? -1 : a.at < b.at ? 1 : 0));
  const gotchas = projectNotes
    .filter((n) => n.kind === "gotcha")
    .sort((a, b) => Number(b.tested) - Number(a.tested) || (a.at > b.at ? -1 : a.at < b.at ? 1 : 0));

  // The first non-empty line after the headline
  function getFirstLine(body: string): string {
    return (body.split("\n").filter((l) => l.trim())[1] ?? "").trim();
  }

  // Helper to get headline
  function getHeadline(body: string): string {
    const line = body.split("\n").find((l) => l.trim()) ?? "";
    return line.replace(/^#+\s*/, "").trim();
  }

  // Build sections
  const sections: Array<{ name: string; items: Array<{ headline: string; detail: string }> }> = [];

  // Stack and why section (decisions)
  const stackItems = decisions.slice(0, 6).map((n) => ({
    headline: getHeadline(n.body),
    detail: ` (${n.id})`,
  }));
  sections.push({
    name: "## Stack and why",
    items: stackItems.length ? stackItems : [{ headline: "none recorded yet", detail: "" }],
  });

  // Scaffold section (procedures)
  const scaffoldItems = procedures.slice(0, 6).map((n) => {
    const firstLine = getFirstLine(n.body);
    const detail = firstLine ? ` — ${firstLine}` : "";
    return {
      headline: getHeadline(n.body),
      detail,
    };
  });
  sections.push({
    name: "## Scaffold",
    items: scaffoldItems.length ? scaffoldItems : [{ headline: "none recorded yet", detail: "" }],
  });

  // Gotchas section
  const gotchasItems = gotchas.slice(0, 8).map((n) => {
    const errorText = n.errors.length ? ` — symptom: \`${n.errors[0]}\`` : "";
    return {
      headline: getHeadline(n.body),
      detail: errorText,
    };
  });
  sections.push({
    name: "## Gotchas",
    items: gotchasItems.length ? gotchasItems : [{ headline: "none recorded yet", detail: "" }],
  });

  // Build the markdown content
  const lines: string[] = ["---"];
  lines.push(`name: ${slugName}`);
  lines.push(`description: "MVP kit drafted from ${project}: stack, scaffold steps, gotchas. Edit before use."`);
  if (tags && tags.length) {
    lines.push("tags:");
    for (const tag of tagList(tags)) {
      lines.push(`  - ${tag}`);
    }
  }
  lines.push("---", "", `# ${slugName}`, "");

  // When to use
  lines.push("## When to use", "- TODO: the kind of project this kit starts, in one line.", "");

  // Add sections with budget control
  let totalTokens = estimateTokens(lines.join("\n"));
  for (const section of sections) {
    if (section.items.length === 0) {
      lines.push(section.name);
      lines.push("- none recorded yet");
      lines.push("");
      totalTokens = estimateTokens(lines.join("\n"));
      if (totalTokens > KIT_BUDGET) break;
      continue;
    }

    lines.push(section.name);
    const isNumbered = section.name.includes("Scaffold");
    let itemNum = 1;
    for (const item of section.items) {
      if (isNumbered) {
        lines.push(`${itemNum}. ${item.headline}${item.detail}`);
        itemNum++;
      } else {
        lines.push(`- ${item.headline}${item.detail}`);
      }
      totalTokens = estimateTokens(lines.join("\n"));
      if (totalTokens > KIT_BUDGET) {
        lines.pop();
        break;
      }
    }
    lines.push("");
    totalTokens = estimateTokens(lines.join("\n"));
    if (totalTokens > KIT_BUDGET) break;
  }

  // MVP done when section
  lines.push("## MVP done when", "- [ ] TODO: the check that proves the MVP runs.", "");

  const content = lines.join("\n");
  writeAtomic(skillPath, content);

  // Parse and return the Kit
  const { fields, body } = parseFrontmatter(content);
  const tagsField = fields.get("tags");
  let kitTags: string[] = [];
  if (Array.isArray(tagsField)) {
    kitTags = tagsField.filter((t): t is string => typeof t === "string");
  }

  return {
    name: slugName,
    description: `MVP kit drafted from ${project}: stack, scaffold steps, gotchas. Edit before use.`,
    tags: kitTags,
    path: skillPath,
    body,
  };
}
