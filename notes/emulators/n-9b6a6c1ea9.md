---
id: n-9b6a6c1ea9
kind: gotcha
at: 2026-11-25T08:01:49Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-11-25T08:01:49Z
tested_sha: 92ba5488cece
---

Eglantine fork builds (lap2, MSYS2 UCRT64 clang) compile NVIDIA DLSS/Streamline OUT: src/video_core/CMakeLists.txt gates ENABLE_NVIDIA_DLSS on MSVC. No fork release up to 0.7.0 has NVIDIA DLSS; nvidia_dlss=true silently does nothing (UsesNvidiaDlss false, no Streamline log lines). Also: harness --baseline-allow rejects EDEN_STREAMLINE_DIR; put Streamline DLLs in <bin>/streamline instead.
