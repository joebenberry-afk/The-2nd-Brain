---
id: n-d02ddab167
kind: note
at: 2026-11-15T02:45:04Z
source: agent
---

FE Fortune's Weave black dialogue background (regression 1109->1112): bad builds log 'Colour target 1280x720 format 16 (RGBA16F) sampled by its own draw: copying it' from texture_cache.h ReplaceColorFeedbackViews (commit 020 a2cefedfc4); good 1109 lacks the code. Ruled out by env: EDEN_NX2_PERF_OPT=0, EDEN_NX2_ASYNC_TRANSLATION=0. User config skip_cpu_inner_invalidation=false (commit 119 irrelevant). Unconfirmed until EDEN_NX2_FEEDBACK_COPY=0 run.
