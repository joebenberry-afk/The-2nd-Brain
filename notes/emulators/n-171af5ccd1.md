---
id: n-171af5ccd1
kind: fact
at: 2026-11-23T17:34:16Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-23T17:34:16Z
tested_sha: b8e15a9c9503
replaced_by: n-1f49b53ba2
retired: 2026-11-23T18:05:55Z
---

FE GPU-thread "tick" zone (~550 ms/s) is the synchronous present, not pushbuffer parsing
Zone::Tick wraps GPU::TickWork -> RequestComposite -> RendererVulkan::Composite; with async_presentation=false (desktop default) Present runs WaitWorker+CopyToSwapchain (vkAcquireNextImageKHR infinite timeout, submit, vkQueuePresentKHR) on the GPU thread with no Nx2Bottleneck WaitScope, so the verdict calls it "GPU thread own work". Measured 2026-11-23 a370145 FE deep runs: async_presentation=true drops tick to 13-150 ms/s and GPU thread 98%->52% working. Command stream (push+method+macro) is only ~240 ms/s and the profiler forces fast_maxwell3d off (maxwell_3d.cpp:67), so NVN-HLE ceiling <=~24% of FE GPU thread. Same-value register skip already exists (SkipSameValueWrites).
