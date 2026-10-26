---
id: n-ac059f9d6c
kind: note
at: 2026-10-25T21:42:31Z
source: agent
evidence:
  - AETHERFRACTURE_Technical_Architecture_v0.1.md
evidence_sha:
  - AETHERFRACTURE_Technical_Architecture_v0.1.md=8a192165f112
---

AetherFracture arch doc (AETHERFRACTURE_Technical_Architecture_v0.1.md) decisions: HD-2D Sprite3D; 4 heroes; ult separate (R), transform F; sim = integer mm (x,d,h) own collision/nav, no Godot physics; 60Hz tick, ms authored->ticks; AI outside sim.step (runner loop, cmds stamped t+1); one Legality for player/AI/enemy; replay = build+data hash+seed+all accepted commands; pacing float accumulator (director slow-mo never changes outcomes); cut-in vs telegraph enforced by 2D ThreatOverlay CanvasLayer (z vfx-threat 50 > ult-cutin 45) since CanvasLayer always over 3D; D13 leans .tres for defs (owner 'no .tres' was palette only) - unconfirmed. Why: Bible 21 Priority A contracts.
