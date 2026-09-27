---
id: mem-d8227d4a3e7b
kind: fact
at: 2026-09-21T10:17:45.485326+00:00
source: convert
evidence:
  - docs/gates/G1A2-grid-analysis.json@09fa6c9050fc (repo C:\Users\assas\Documents\BasicUpscaler\The Basic Upscaler)
  - docs/research/BLOCKER-G1A2-grid-correction-2026-09-21.md@87cbd0227866 (repo C:\Users\assas\Documents\BasicUpscaler\The Basic Upscaler)
---

The WGC Direct3D11CaptureFrame.SystemRelativeTime stamp is later than the applic

The WGC Direct3D11CaptureFrame.SystemRelativeTime stamp is later than the application's dequeue and Present-return on 92-96% of frames and its deltas fit the display vblank grid (165 Hz, 10.0 us mean residual over 380 deltas, 6060.686 us fitted period); the 100ns-to-QPC conversion is an identity at 10 MHz, so the retired |dequeue-wgc|<=2ms budget was ill-posed and G1 stays BLOCKED with the mechanism explained.
