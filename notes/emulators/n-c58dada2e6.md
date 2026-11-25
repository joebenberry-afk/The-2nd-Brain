---
id: n-c58dada2e6
kind: fact
at: 2026-11-25T21:09:30Z
source: agent
evidence:
  - src/fe-lab/research/inventory.json
evidence_sha:
  - src/fe-lab/research/inventory.json=1a4f88519c9d
checked: holds
checked_at: 2026-11-25T21:10:20Z
checked_why: six JSON exist; memory_manager.cpp:333 in both trees; vulkan_device.cpp follows_reported_vram_budget 1970-1995 (fe-buf) and 1988-2013 (fork), 6GiB+1GiB cap and integrated cap as stated
checked_sha: 34d8242d858c
replaces: n-031c39afb3
---

Emulator performance research (2026-11-16, not re-verified) is in src/fe-lab/research/{cpu,gpu,inventory,shaders,timing,verified}.json; some conclusions have changed
Seen 2026-11-25: those six JSON files exist. EDEN_NX2_NO_TRANSLATION_CACHE is the GPU address translation cache, not a JIT cache (src/video_core/memory_manager.cpp:333, same line in both trees). Texture budget cap is no longer unconditional: src/video_core/vulkan_common/vulkan_device.cpp (lines 1970-1995 in src/Eglantine-f7c0cc30ac on fe-buf, 1988-2013 in src/eglantine-fork) applies 6 GiB + 1 GiB x resolution scale only when follows_reported_vram_budget is false (and not Aggressive); an integrated GPU is capped at device_access_memory. Original 2026-11-16 claims not re-checked: 139 sources, inventory lacks persistent CPU translation cache / graphics_pipeline_library / shader_object / audio stretching, MWAITX in HostTiming, ASUS ROG G16 capped RTX 5070 Ti at 65 W until power mode changed (check nvidia-smi --query-gpu=enforced.power.limit before GPU benchmarks).
