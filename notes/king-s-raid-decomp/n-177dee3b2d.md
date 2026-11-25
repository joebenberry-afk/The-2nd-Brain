---
id: n-177dee3b2d
kind: procedure
at: 2026-11-04T19:32:13Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-04T19:32:13Z
tested_sha: 04db510d3092
---

REA (morluto/rea) installed for DSH: portable Node 24.22.2 at %LOCALAPPDATA%\Programs\nodejs-rea (system Node 26.7.0 is below REA's floor 26.12.1/24.22.1), rea-agents 6.8.0 global in that prefix, MCP registered as ~/.dsh/cordis.patch.yml entry id rea-mcp -> tools mcp__rea__*, skill reverse-engineer-anything in ~/.agents/skills. `rea doctor` reports healthy=true, environment_healthy=false only because no native engine (Ghidra/IDA/JADX/Kuna) is configured; static JS/desktop/IL2CPP/PE-ELF inspection works without one. Update with `rea update`.
