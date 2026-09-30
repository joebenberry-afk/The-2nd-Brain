/** One-shot import of V3 records. */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { basename, join } from "node:path";
import { errorPatternProblem, loadNotes, parseFrontmatter, saveNote, type Note, GLOBAL } from "./notes.ts";
import { idFor, loadProjects } from "./project.ts";
import { nowIso, slug, writeAtomic } from "./util.ts";

export interface ConvertReport {
  written: number;
  skipped: number;
  errors: string[];
  projects: number;
}

interface V3Record {
  id?: string;
  title?: string;
  type?: string;
  scope?: string;
  project?: string;
  domains?: string[];
  status?: string;
  grade?: string;
  recorded_at?: string;
  valid_from?: string;
  superseded_at?: string;
  superseded_by?: string;
  supersedes?: string;
  evidence?: string[];
  terms?: string[];
  trigger_errors?: string[];
  edited_at?: string;
}

function parseV3Record(text: string): V3Record & { body: string } {
  const { fields, body } = parseFrontmatter(text);

  const record: V3Record = {};
  for (const [key, value] of fields) {
    // Convert to arrays for list fields
    const listFields = ["domains", "evidence", "terms", "trigger_errors"];
    if (listFields.includes(key)) {
      const arr = Array.isArray(value) ? value : value ? [value] : [];
      (record as any)[key] = arr;
    } else {
      const str = Array.isArray(value) ? value.join(", ") : value;
      (record as any)[key] = str;
    }
  }
  return { ...record, body: body.trim() };
}

function mapV3ToV4Kind(v3Type: string | undefined): string {
  if (!v3Type) return "note";
  if (["fact", "decision", "gotcha", "procedure"].includes(v3Type)) return v3Type;
  if (v3Type === "locator") return "fact";
  if (v3Type === "correction") return "gotcha";
  if (v3Type === "state") return "note";
  return "note";
}

function mapV3ToV4Project(scope: string | undefined, project: string | undefined, domains: string[] | undefined): string {
  if (scope === "project") return project || "unknown";
  if (scope === "domain") {
    if (domains && domains.length > 0) return GLOBAL;
    return project || GLOBAL;
  }
  if (scope === "global") return GLOBAL;
  return "unknown";
}

function mapV3ToV4Tags(scope: string | undefined, domains: string[] | undefined, terms: string[] | undefined): string[] {
  const tags: string[] = [];
  if (scope === "domain" && domains) {
    tags.push(...domains);
  } else if (scope === "project" && terms) {
    tags.push(...terms);
  }
  return tags.sort();
}

function parseTomlString(content: string): Record<string, string | string[]> {
  const result: Record<string, string | string[]> = {};
  const lines = content.split("\n");

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    // Try to match key = "value"
    const scalarMatch = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]*)"/.exec(trimmed);
    if (scalarMatch && scalarMatch[1] && scalarMatch[2] !== undefined) {
      result[scalarMatch[1]] = scalarMatch[2];
      continue;
    }

    // Try to match key = ["a", "b"]
    const listMatch = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\[(.*)\]/.exec(trimmed);
    if (listMatch && listMatch[1] && listMatch[2] !== undefined) {
      const items = listMatch[2]
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s)
        .map((s) => s.replace(/^"(.*)"$/, "$1"));
      result[listMatch[1]] = items;
    }
  }

  return result;
}

export function convertV3(fromHome: string, toHome: string, opts?: { dryRun?: boolean }): ConvertReport {
  const report: ConvertReport = { written: 0, skipped: 0, errors: [], projects: 0 };

  if (!existsSync(join(fromHome, "records")) && !existsSync(join(fromHome, "projects"))) {
    report.errors.push(`${fromHome}: no V3 records/ or projects/ here — nothing to convert`);
    return report;
  }

  // Every note file already present counts, even one that no longer parses: never overwrite it.
  const existingIds = new Set(loadNotes(toHome).notes.map((n) => n.id));
  for (const file of listMarkdown(join(toHome, "notes"))) existingIds.add(basename(file, ".md"));

  // projects.json is merged into as written (raw), and never rewritten when it does not parse.
  const projectsFile = join(toHome, "projects.json");
  let rawFile: Record<string, unknown> = {};
  let rawProjects: Record<string, unknown> = {};
  let projectsWritable = true;
  if (existsSync(projectsFile)) {
    try {
      const parsed: unknown = JSON.parse(readFileSync(projectsFile, "utf8").replace(/^\uFEFF/, ""));
      const inner = (parsed as { projects?: unknown } | null)?.projects;
      if (!inner || typeof inner !== "object") throw new Error('expected { "projects": { … } }');
      rawFile = parsed as Record<string, unknown>;
      rawProjects = inner as Record<string, unknown>;
    } catch (error) {
      projectsWritable = false;
      report.errors.push(`${projectsFile}: ${error instanceof Error ? error.message : String(error)} — left untouched`);
    }
  }
  const existingProjects = loadProjects(toHome);

  // Process V3 records
  const recordDirs: [string, boolean][] = [
    [join(fromHome, "records"), false],
    [join(fromHome, "records", "private"), true],
  ];

  for (const [recordDir, isPrivate] of recordDirs) {
    if (!existsSync(recordDir)) continue;

    for (const file of readdirSync(recordDir)) {
      if (!file.endsWith(".md")) continue;

      const path = join(recordDir, file);
      try {
        const text = readFileSync(path, "utf8");
        const v3Record = parseV3Record(text);

        if (!v3Record.id || !v3Record.title) {
          report.errors.push(`${path}: missing id or title`);
          continue;
        }

        const id = v3Record.id;
        if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id) || id.includes("..")) {
          report.errors.push(`${path}: not a V3 record id: ${JSON.stringify(id)}`);
          continue;
        }
        if (existingIds.has(id)) {
          report.skipped++;
          continue;
        }

        // Map V3 to V4 fields
        const kind = mapV3ToV4Kind(v3Record.type);
        // A V3 project named "Global" is a project, not the scope every project sees, and a device
        // name (aux) is not a folder git can index.
        const mapped = slug(mapV3ToV4Project(v3Record.scope, v3Record.project, v3Record.domains));
        const project = mapped === GLOBAL && v3Record.scope !== "project" ? GLOBAL : idFor(mapped);
        const tags = mapV3ToV4Tags(v3Record.scope, v3Record.domains, v3Record.terms);
        const at = v3Record.valid_from || v3Record.recorded_at || "1970-01-01T00:00:00Z";
        const tested = v3Record.status === "current" && (v3Record.grade === "TESTED" || v3Record.grade === "VERIFIED");
        const retired =
          v3Record.status === "superseded" || v3Record.status === "retracted"
            ? v3Record.superseded_at || v3Record.edited_at || v3Record.recorded_at || nowIso()
            : undefined;

        const body = v3Record.body ? `${v3Record.title}\n\n${v3Record.body}` : v3Record.title;
        const errors = (v3Record.trigger_errors || []).filter((e) => {
          const problem = errorPatternProblem(e);
          if (problem) report.errors.push(`${path}: ${problem}`);
          return !problem;
        });

        // Create note
        const note: Note = {
          id,
          kind: (kind as any) || "note",
          project,
          private: isPrivate,
          at,
          source: "convert",
          tags,
          errors,
          evidence: v3Record.evidence || [],
          tested,
          replaces: v3Record.supersedes,
          replacedBy: v3Record.superseded_by,
          retired,
          body,
          path: "",
        };

        if (!opts?.dryRun) {
          const saved = saveNote(toHome, note);
          existingIds.add(saved.id);
        }

        report.written++;
      } catch (error) {
        report.errors.push(`${path}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }

  // Process projects
  const projectsDir = join(fromHome, "projects");
  const newProjectEntries: Record<string, { paths?: string[]; remote?: string; tags?: string[] }> = {};

  if (existsSync(projectsDir)) {
    for (const projectName of readdirSync(projectsDir, { withFileTypes: true })) {
      if (!projectName.isDirectory()) continue;

      const projectPath = join(projectsDir, projectName.name, "project.toml");
      if (!existsSync(projectPath)) continue;

      try {
        const content = readFileSync(projectPath, "utf8");
        const parsed = parseTomlString(content);

        // Keyed by the slugged id; an entry already present (under any spelling) is kept as is
        const projectId = idFor(typeof parsed.id === "string" && parsed.id ? parsed.id : projectName.name);
        if (existingProjects[projectId]) {
          continue;
        }

        // Build the entry
        const entry: Record<string, any> = {};

        // paths
        if (parsed.repo_path) {
          if (Array.isArray(parsed.repo_path)) {
            entry.paths = parsed.repo_path;
          } else {
            entry.paths = [parsed.repo_path];
          }
        }
        if (Array.isArray(parsed.paths)) {
          if (entry.paths) {
            entry.paths = [...entry.paths, ...parsed.paths];
          } else {
            entry.paths = parsed.paths;
          }
        }

        // remote
        if (parsed.git_remote) {
          entry.remote = Array.isArray(parsed.git_remote) ? parsed.git_remote[0] : parsed.git_remote;
        }

        // tags (from domains)
        if (parsed.domains) {
          const domains = Array.isArray(parsed.domains) ? parsed.domains : [parsed.domains];
          if (domains.length > 0) {
            entry.tags = domains;
          }
        }

        newProjectEntries[projectId] = entry;
      } catch {
        // Skip projects that fail to parse
        continue;
      }
    }
  }

  // Merge new entries into projects.json exactly as it was written (never through the normalized copy)
  if (projectsWritable) {
    if (!opts?.dryRun && Object.keys(newProjectEntries).length > 0) {
      writeAtomic(projectsFile, JSON.stringify({ ...rawFile, projects: { ...rawProjects, ...newProjectEntries } }, null, 2) + "\n");
    }
    report.projects = Object.keys(newProjectEntries).length;
  }

  return report;
}

/** Every *.md file below `dir`, at any depth. */
function listMarkdown(dir: string): string[] {
  const out: string[] = [];
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...listMarkdown(path));
    else if (entry.name.toLowerCase().endsWith(".md")) out.push(path);
  }
  return out;
}
