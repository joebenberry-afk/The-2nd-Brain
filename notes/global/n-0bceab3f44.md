---
id: n-0bceab3f44
kind: decision
at: 2026-11-16T14:44:53Z
source: agent
replaces: n-b1b62ab327
---

Agent roster models as of 2026-11-16 (supersedes the 2026-10-07 roster).
Override (task.agentModelOverrides, ~/.omp/agent/config.yml) beats agent frontmatter (~/.omp/agent/agents/*.md).
Opus 5.5: integration-engineer, pixel-critic (override); character-artist, character-rigger, combat-designer, concept-artist, environment-artist, game-designer, game-ui-designer, gameplay-animator, level-designer, narrative-designer, vfx-artist (frontmatter).
2026-11-16: game-designer moved off stale claude-opus-4-6; pixel-critic pinned by override because the aseprite plugin is Claude-dialect, so its frontmatter `model: opus` is discarded and it would inherit the parent's model.
Left alone on purpose: system-architect (gpt-6-astra) and reviewer (gpt-6.1-sol) were Opus 5.5 until 2026-11-06, when the owner asked for provider diversity; hydrogen on task/scout/sonic/feature-implementer is the owner's 2026-11-15 preference; gameplay-animator-haiku is Haiku by design; Fable/Mythos agents are a higher tier.
