---
id: n-24fb3b4af3
kind: decision
at: 2026-10-06T10:44:51Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-BasicUpscaler\memory\fast-reliable-efficient.md
---

Every BasicUpscaler and BUNet feature must be fast, reliable and power efficient; weigh it in every design, plan and review (DECISIONS.md item 16).

**Why:** owner stated it as the predominant goal for all BU and BUNet work (29 Sep 2026), after approving the UI-aware Smart fill design.
**How to apply:** designs state their per-frame cost and fallback; recompute on change, not per frame; fuse GPU passes; no polling; training/analysis only when idle and plugged in. Related: [[agents-use-sonnet]].
