---
id: n-2d22ee64de
kind: fact
at: 2026-10-15T17:59:15Z
source: agent
---

OMP has no reranker role. The model-kind roles are image, web, speech, dictation and judge. The judge role takes System One judgment APIs (typesafe -> {baseUrl}/v1/systemone, openrouter-decisions, openai-decisions, workers-ai-systemone) or tiny/chat models such as local/lfm2-1.2b. It serves general typed Choice/probability questions for auto-thinking, stop detection, eval judge() and git staging, not query-note relevance, so Tora's Qwen3-Reranker does not fit it. Brain calls Tora directly over /score and /judge.
