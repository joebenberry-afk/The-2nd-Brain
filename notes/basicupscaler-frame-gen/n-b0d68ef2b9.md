---
id: n-b0d68ef2b9
kind: note
at: 2026-10-10T01:29:52Z
source: agent
evidence:
  - BasicUpscaler Research/reports/Hybrid interpolation and extrapolation.md
  - BasicUpscaler/Frame Gen.md
evidence_sha:
  - BasicUpscaler Research/reports/Hybrid interpolation and extrapolation.md=c22ad136467d
  - BasicUpscaler/Frame Gen.md=bcdd79d8d1cd
---

Hybrid interpolation+extrapolation research (9-10 Oct, Fable; built-in /deep-research workflow wf_9f95ec0a-491, 101 agents, 21 confirmed / 4 refuted claims). Report: BasicUpscaler Research/reports/Hybrid interpolation and extrapolation.md; pack research_notes/Hybrid interpolation and extrapolation/. Core finding: no system makes one frame both interpolated and latency-free; hybrids split by component (camera late-warp over content: ASW 2.0 rule 'only one stage moves the camera'), by perception (Didyk 2010 blur+resharpen), by timing (Phase Sync). Refuted, never cite: uniVIP long-horizon joint gain; Outatime 4-degree threshold and Kalman snap hiding; AppSW net latency. BUFG design: (1) camera-now/content-mid mouse late warp over interpolation (O8=yes), (2) FGF-041 late-slot interpolation (holdback Ts/k at k>=3: 10.6->6.1 ms at 165 Hz; nothing at 2x per M4), (3) Didyk-style hiding on extrapolated slots. Kill: blending real frames toward predictions; dual-mode nets at 1080p/4 ms. Ledger: Frame Gen.md section 21 + change-log; FG row needs an ID from the lead (FG-196 highest taken).
