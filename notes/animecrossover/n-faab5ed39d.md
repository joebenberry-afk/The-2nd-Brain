---
id: n-faab5ed39d
kind: decision
at: 2026-10-27T22:28:53Z
source: agent
evidence:
  - Endfield_Blender_Skill.zip
evidence_sha:
  - Endfield_Blender_Skill.zip=557d8b859b3a
---

Owner verdict 2026-10-27: Astra (openai-codex/gpt-6-astra, spawned via performance-engineer agent) beats Terra (gpt-6.1-terra, default task agent) at 3D character modelling. Rimuru rounds 3 (cc-blender-skill) and 4 (endfield-agent-character-pipeline skill, from repo Endfield_Blender_Skill.zip, installed at ~/.agents/skills). Terra spent ~4-12 min per round and stopped early. Astra ran 1-2+ h with 14-18 inspected cycles. For 3D art, use Astra. Subagent models can only be set through agentModelOverrides in ~/.omp/agent/config.yml.
