---
id: n-dfed81ada1
kind: gotcha
at: 2026-11-25T21:05:53Z
source: agent
---

Kernel-side wait() on eval agent handles dies with exit 130 when the user interjects and cancels those agents (seen 2026-11, not re-verified 2026-11-25)
For long fan-outs use the task tool, or have agents write result files, so a cancel does not lose finished results.
