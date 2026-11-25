---
id: n-4a87be32fd
kind: decision
at: 2026-11-06T03:05:35Z
source: agent
checked: moved
checked_at: 2026-11-25T17:59:11Z
checked_why: "The config now differs from the note: reviewer, verifier, perf and architect agents use GPT-6.2 Sol/Astra, rlm/librarian/deep-research use Sonnet 5.5, and sonic uses Haiku 5.5, not Grok build or Grok 4.7. Only sentinel=Grok 4.7, commit=DeepSeek Flash and scout=Haiku match. [~/.omp/agent/config.yml l"
checked_sha: bb64d6ce0f59
replaced_by: n-c3642ddc10
retired: 2026-11-25T21:00:03Z
---

Model routing reassigned 2026-11-06 (owner approved, saved globally): implementer/task=Sonnet 5.5, verifier/reviewer/perf=GPT-6.1 Sol, architect/evidence-auditor=GPT-6 Astra, librarian/deep-research/sentinel=Grok 4.7, sonic=grok-build-0.1, rlm+commit role=DeepSeek Flash, scout=Haiku 5.5, Mythos kept for security/blocker/advisor. Cross-provider retry.fallbackChains per model. Owner has NO OpenRouter. Gemini unusable while aseprite MCP is mounted (validate tool nested-array schema lacks items -> HTTP 400); Antigravity Claude quota exhausted until 2026-11-09.
