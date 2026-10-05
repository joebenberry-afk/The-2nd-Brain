---
id: n-fc94daf79d
kind: note
at: 2026-10-02T09:33:45Z
source: agent
---

BUNet phase 1c (2 Oct 2026): GPU-only numeric faults that CPU tests cannot see. (1) torch luma = (x*w).sum(1) rounds differently on CUDA for a permuted HWC view vs a contiguous CHW tensor (1 ULP in ~25% of pixels); score.edge_mask thresholds at a quantile with ties, so the layout flips 4-697 edge pixels per 1080p frame -> edge PSNR/halo differ 0.012 dB/0.2% between evaluate.frames and data.load paths (IDEAS PRC-20). (2) flat frames compared with torch.equal against k/255 read 23/24 on CUDA; compare 8-bit codes. Before any run-once GPU experiment: end-to-end GPU dry-run on synthetic stand-ins AND a check that stock reproduces a stored reference before the first search; both caught these.
