---
id: n-ac2df2794b
kind: decision
at: 2026-11-25T18:10:07Z
source: agent
evidence:
  - projects.json
  - brain/src/project.ts
evidence_sha:
  - projects.json=bf4315573094
  - brain/src/project.ts=ac3944ce9a4d
---

Changed evidence costs a note nothing (D6-11) and evidence resolves through evidenceRoots() (D6-3)
Owner 2026-11-25: "Drop the penalties" — changedEvidence deleted; only missing evidence or stale_after marks stale. D6-3: the unresolved paths were not bad data; projects.json declares Documents/BasicUpscaler but the git repo is one level down and 11,641 of 11,669 events ran from the outer folder. Project.repos + evidenceRoots(project, home) in project.ts fix it (stale 24 -> 6 of 51). Kill rules 2026-12-02, plan §7.11/§7.12. `brain sync` push fails in agent shells: no GitHub credentials for joebenberry-afk (gh is logged in as logicdelos).
