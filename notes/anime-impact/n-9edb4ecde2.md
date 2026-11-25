---
id: n-9edb4ecde2
kind: gotcha
at: 2026-11-09T21:29:17Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-09T21:29:17Z
tested_sha: 4baf7e582e34
---

Godot toon shader gotchas (anime-impact render/toon): (1) inverted-hull outline width must use abs(PROJECTION_MATRIX[1][1]); the sign is negative in SubViewport/flipped-Y paths and pushes the hull inward (black interiors on capes/coats). (2) With render_mode cull_disabled Godot already flips NORMAL on back faces; a manual `if (!FRONT_FACING) N = -N` double-flips and turns linings pale grey-blue. (3) `source_color` uniforms are sRGB-encoded: a shadow tint of 0.6 multiplies by ~0.32 linear; measure reference stills in linear and encode. (4) GLTFDocument.generate_scene(state) bakes animations at 30 fps by default: 60 fps clips lose one-frame contact poses; pass bake_fps 60.
