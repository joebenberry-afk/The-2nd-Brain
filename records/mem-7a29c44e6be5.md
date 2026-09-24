---
id: mem-7a29c44e6be5
title: HUD gauge reconciliation: two distinct gold/yellow circular icons, distinguished by glyph not color
type: fact
scope: domain
status: candidate
grade: OBSERVED
recorded_at: 2026-08-28T20:34:44.918560+00:00
origin: MODEL_INFERENCE
evidence:
  - user clarification, session synthesis
---

Resolved an apparent contradiction between this session's synchronized UI/telemetry checkpoint (mem-fec561d368cb, gold circular gauge value 2 matched telemetry blast_stock_current 2, blue box 5 matched blast_stock_max 5) and a separately authored combat-knowledge document's Rule 9 (the yellow/gold HUD change icon is not the Skill Stock count; it represents switch/change readiness). User confirmed directly: the golden gauge WITH CIRCULAR ARROWS specifically represents switch readiness. This means there are two distinct gold/yellow circular HUD elements sharing similar color but different glyphs: (1) a circular-arrows icon = switch readiness (matches the external document's claim), and (2) a separate non-arrow gold circular icon, paired with a blue Skill-Stock-max box, which this session's synchronized checkpoint correctly correlated with blast_stock_current/blast_stock_max. Both findings are correct once the icons are distinguished by their specific glyph rather than by color/position alone. Agent rule going forward: when identifying HUD gold/yellow circular elements, always note the specific icon glyph (arrows vs. other symbol) in addition to color and position, since color alone is insufficient to disambiguate switch-readiness from Skill-Stock/blast-stock gauges on this HUD. No production semantic acceptance change made; this is a UI-attribution clarification only.
