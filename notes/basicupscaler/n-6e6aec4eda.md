---
id: n-6e6aec4eda
kind: note
at: 2026-10-01T19:04:28Z
source: agent
---

Fable round (1 Oct 2026, IQ 19) on NIS+FSR1+AA fusion: EASU kernel centroid is off the sample (0.115 px no-edge, 0.254 px edge at 1.5x); RCAS amplifies the ramp ripple 1.7-2.2x. Term K (centroid correction, 8-tap LS slope, faded on hard steps by EASU ratio r) = +0.24 dB on once-run synthetic split, Kodak LPIPS +0.0000 (1.5x) / +0.0014 (2x), GPU +0.023 ms with tap rewrite. B (Catmull-Rom below contrast) + A-lite (colour axis into luma) + K = tier 2 +0.43 dB, +0.087 ms. R (run-length redraw) +0.70 dB on aliased only, CPU reference only. Sharpening terms S/P/T all failed PSNR. Evidence synthetic+Kodak only; no game pairs. Everything in FORMULAS.md Fable section + 19_verification.
