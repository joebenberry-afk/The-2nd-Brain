---
id: n-0fad6af720
kind: note
at: 2026-10-01T21:45:15Z
source: agent
---

Fable round 5 (1 Oct 2026, last pass with all contributors' ideas): kept Grok's per-channel RCAS limiter (flag in alpha LSB), Antigravity's coherence damping of EASU len (half strength, only below contrast window; tensor coherence), Codex's L as option; dropped clamp widening (X12) and gamma-2 accumulation (X17) — both lose. Sixth once-run split 1.5x: F2 (K+D+A-lite+chlim+damping) +0.629 dB [0.557,0.706] vs base +0.582; F2+L +0.661 (346/18, halo 0.61); F1 (SP+A-lite+damping, one pass) +0.916 [0.840,0.996]; F1+K +1.018. Kodak F2 +0.527 dB LPIPS -0.0051 (24/24). Damping repairs D's natural-blur loss (-0.55 -> -0.16 dB at 0.5 px). Quiet-GPU run 9: stock 0.136, SP 0.123 (0.90x), F1 0.191, KDA 0.213, F2 0.267, F2+B 0.311 ms. Open: one-pass LPIPS gap at 1.5x (+0.012), thin-line pan jitter, game pairs.
