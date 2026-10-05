---
id: n-0b4b7cd3a9
kind: note
at: 2026-10-01T20:21:28Z
source: agent
---

Fable round 3 (1 Oct 2026): term D (softness-matched deblur) LOSES on naturally soft content: aa scenes + world blur 0.5-1.0 input px -> D alone -0.27..-0.39 dB vs stock FSR1; K alone gains +0.2..+1.1 there. A frame-level softness constant (oracle) is worth +0.17 dB more on VS-19 (aliased 0, aa 0.6, soft 1.0) but does not fix natural blur (-0.44 dB at 0.5 px); local floor/fade rules only move the loss. D on aa edges is clamped steepening of under-resolved steps, not variance bookkeeping (my first derivation was wrong, corrected in FORMULAS.md round 3). Safe order: tap rewrite, K; D conditional on softness coming from anti-aliasing. K+D+A-lite confirmed on 4th split: +0.579 dB at +0.076 ms.
