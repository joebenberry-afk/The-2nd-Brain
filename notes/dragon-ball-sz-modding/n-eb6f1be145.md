---
id: n-eb6f1be145
kind: gotcha
at: 2026-09-28T14:11:01Z
source: agent
tested: "true"
---

SZ game install gotchas found at restart (2026-09-28)
- Stale AIplusUltraPlus v0.1a plugin (built for 24497537) sat in SparkingZERO/Mods from 2026-08-15 until 2026-09-28. Lab captures in that window may have run with it mounted; moved to ultimate-ai/.local/backups/2026-09-28-restart/.
- Steam appmanifest_1790600 AutoUpdateBehavior=0 (always update): the game can change build under you.
- AIplus_AES_KEY env var absent. Builders use the Toolkit's installed-24953175 legacy extracts, not fresh reads from the encrypted game containers.
- Shipping game writes no logs (%LOCALAPPDATA%/SparkingZERO/Saved/Logs is empty), so mount state is visible only through runtime reads.
