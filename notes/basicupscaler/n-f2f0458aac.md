---
id: n-f2f0458aac
kind: note
at: 2026-10-02T05:45:25Z
source: agent
---

BUNet trainer death check (SPD-34, DECISIONS 44): Run.dead reads the first-layer gradient; exactly zero = dead. stop_if_dead runs at each 500-step log and before every save, writes dead.jsonl, sets ckpt.pt aside as ckpt.dead.pt (the check is one update behind the weights), trainer exits 76 (runctl.DEAD) and the supervisor leaves the job and continues the queue. Why exactly zero and not a threshold: in warm-up a healthy net reads 1e-10..1e-7 at step 2.
