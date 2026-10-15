---
id: n-e4c8f33b8f
kind: note
at: 2026-10-09T03:11:08Z
source: agent
---

Decision 8 Oct 2026: owner's deep-research plugin lives at ~/.claude/skills/deep-research (skills-dir plugin, own git repo) and replaces anthropic-skills:deep-research via permissions.deny Skill(anthropic-skills:deep-research). Why: two research skills matching the same prompts fire unpredictably. Spec: docs/superpowers/specs/2026-10-08-deep-research-plugin-design.md in that repo. Owner wants a temporal lens: old sources show how knowledge and the thing changed, modern ones show current state.
