---
id: n-c2f1ac3e24
kind: decision
at: 2026-10-19T16:34:56Z
source: agent
replaces: n-c2de1cda9a
---

Keep OMP providers.cacheRetention "auto" (1-hour Anthropic entries on OAuth seats); 5-minute caching costs more, with or without idle warming.
14 days of OMP requests (2026-10-19): 997 came 5m-1h after the previous one. At 5m without warming: Opus input +77%, Sonnet +19.5%. With OMP's warmer rules (cache-warmer.ts: subagents cacheWarming:false; idle refresh only if 0.15*missCost - warmCost >= $0.05, so prompt >= 96k Opus / 192k Sonnet; 30-min idle cap): Opus +7.5%, Sonnet +22%. An earlier estimate (Opus +0.3%, Sonnet -12%) assumed every session was warmed, which is wrong.
For this owner, cacheRetention only affects Anthropic: the openai-codex provider never sends prompt_cache_retention.
