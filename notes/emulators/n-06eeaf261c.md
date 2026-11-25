---
id: n-06eeaf261c
kind: fact
at: 2026-11-16T18:17:00Z
source: agent
checked: wrong
checked_at: 2026-11-25T17:52:13Z
checked_why: The 404 holds, and the 7z backup and the engine/fefw-recomp copy (no .git) both exist. But the mirror recomp-study/src/Recompia.git does not exist, because the clone log is empty. Recompia's API record names the owner Dittobyte, not featureJosh. The '648 identical files' figure does not match the 95
checked_sha: 26d524999c40
replaced_by: n-33ecc793f0
retired: 2026-11-25T21:02:39Z
---

github.com/Goldoire/fefw-recomp (FE:FW recompilation, engine of EmblemWeave) returns 404 since 2026-11-16; author had announced deletion. Our only source copy: Emulators/EmblemWeave/EmblemWeave-v0.1.35/engine/fefw-recomp (no .git), backup 7z in Emulators/recomp-study/backup/. Never delete either. Sister project sharing the nxrt runtime (648 byte-identical files): featureJosh/Recompia, GPL-3.0, still active; mirror in recomp-study/src/Recompia.git.
