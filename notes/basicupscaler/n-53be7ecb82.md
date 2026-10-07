---
id: n-53be7ecb82
kind: fact
at: 2026-10-06T10:44:50Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-BasicUpscaler\memory\bufp-owned-by-gpt.md
---

On 3 Oct 2026, while I proposed sequencing frame generation around the BUFP (M2) confirmation, the owner said: "we already have GPT working on BUFP".

**Why:** BUFP and BUFG run in parallel lanes with different agents; BUFG work does not wait on or displace M2.

**How to apply:** don't edit BUFP code, M2 receipts or the m2-bufp checkout; BUFG timing must plug into BUFP's scheduler (FramePacing FP-20) rather than build a second limiter. Coordinate through the shared ledgers and serialize GPU use (the GPU lock is shared). Related: [[frame-gen-ledgers]], [[concurrent-sessions-shared-ledgers]].
