---
id: n-aef06f736e
kind: gotcha
at: 2026-10-23T17:14:11Z
source: agent
---

DSH discovers skills only at `<root>/<name>/SKILL.md` or `<root>/<name>.md` — nested `**/SKILL.md` is deliberately ignored, so plugin-style repos (e.g. a skill living at `<repo>/skills/<name>/SKILL.md`) never appear in the catalog. Scanned roots: `<projectRoot>/.dsh/skills`, `<projectRoot>/.agents/skills`, `customSkillDirs`, `$DSH_HOME/skills`, `~/.agents/skills` (agentsHome). Catalog id comes from frontmatter `name`, not the directory name; symlinks/junctions are followed and the watcher picks up new dirs live (no restart). Fix for such a repo: junction `~/.agents/skills/<anything>` -> `<repo>/skills/<name>` (needs danger-full-access; workspace-write denies the profile path). Done for Oh My Pi's deep-research plugin: `~/.agents/skills/omp-deep-research` -> `~/.agents/skills/deep-research/skills/deep-research`.
