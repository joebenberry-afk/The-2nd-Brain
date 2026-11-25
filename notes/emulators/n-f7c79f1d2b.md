---
id: n-f7c79f1d2b
kind: fact
at: 2026-11-16T06:01:50Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-16T06:01:50Z
tested_sha: e3ccd6823fce
checked: moved
checked_at: 2026-11-25T17:59:22Z
checked_why: The research JSON files exist, and EDEN_NX2_NO_TRANSLATION_CACHE is the GPU translation cache (memory_manager.cpp:333). The texture budget cap is no longer unconditional. It now applies only when the driver does not report a VRAM budget (follows_reported_vram_budget is false) and the mode is not Agg
checked_sha: e3ccd6823fce
---

Emulator performance research (2026-11-16) saved at src/fe-lab/research/{cpu,shaders,gpu,timing,inventory,verified}.json — 139 sources, 9 pivotal ones re-opened.
Repo inventory: has fastmem, block linking, async pipeline builds, EDS1-3, GPU thread + front/back split (off at High), page dirty tracking, lazy guest-RAM commit. Lacks: persistent CPU translation cache, VK_EXT_graphics_pipeline_library, shader_object, audio stretching. EDEN_NX2_NO_TRANSLATION_CACHE is the GPU address translation cache, not a JIT cache. Texture budget cap = 6 GiB + 1 GiB x resolution scale (vulkan_device.cpp:1911-1916) unless vram_usage_mode Aggressive. HostTiming waits with MWAITX (looks 100% busy, is not a spin).
Host gotcha: ASUS ROG G16 capped the RTX 5070 Ti at 65 W (max 140 W) until the user changed power mode; check `nvidia-smi --query-gpu=enforced.power.limit` before any GPU benchmark.
