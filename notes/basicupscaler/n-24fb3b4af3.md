---
id: n-24fb3b4af3
kind: decision
at: 2026-10-06T10:44:51Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-BasicUpscaler\memory\fast-reliable-efficient.md
checked: holds
checked_at: 2026-11-25T18:00:01Z
checked_why: Item 16 reads "Every BU and BUNet feature must be fast, reliable and power efficient", as the owner's 29 Sep standing rule, with the same how-to-apply points. [BasicUpscaler/DECISIONS.md:112-118]
checked_sha: 8332cf23eea0
---

Every BasicUpscaler and BUNet feature must be fast, reliable and power efficient; weigh it in every design, plan and review (DECISIONS.md item 16).

**Why:** owner stated it as the predominant goal for all BU and BUNet work (29 Sep 2026), after approving the UI-aware Smart fill design.
**How to apply:** designs state their per-frame cost and fallback; recompute on change, not per frame; fuse GPU passes; no polling; training/analysis only when idle and plugged in. Related: [[agents-use-sonnet]].
