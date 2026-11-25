---
id: n-6cdbc2b0cf
kind: note
at: 2026-11-08T20:32:48Z
source: agent
---

Claude Code restored to native Max operation on 2026-11-08: removed global settings env.ANTHROPIC_BASE_URL, x-litellm-only ANTHROPIC_CUSTOM_HEADERS, and exact SessionStart gpt-bridge/ensure-bridge.sh hook. Preserved shared LiteLLM for Codex GPT/DeepSeek. A persistent shared ANTHROPIC_API_KEY otherwise wins over stored Max OAuth, proven by auth status api_key; Claude-only env.ANTHROPIC_API_KEY empty string restores claude.ai/max while leaving shared key intact. Verified ordinary auth and direct Opus firstParty response. Already-open parent applications retain proxy env until restarted. Pre-repair backup: C:\Users\assas\.claude\settings.json.bak-remove-litellm-20261108-162858-796953.
