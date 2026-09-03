# Second Brain Core Rule for Claude Code

This workspace is integrated with The Second Brain via native SessionStart/
PreCompact/Stop hooks (P3a).

## Operating Principles

1. **Source Authority**: Current repository source, verified tests, and live tool evidence strictly outrank Second Brain memory.
2. **No Automatic Retrieval**: SessionStart and PreCompact never inject memory or project history into context. Nothing here changes that.
3. **Single Source of Truth**: Do not create parallel memory databases or session ledgers. Reuse the existing Second Brain store.
4. **Candidate-Only Writeback**: Durable memory writeback remains candidate-only; the Stop hook marker path is still supported.

To remember: run `brainctl remember "<claim>" --evidence <path>.`
To check: `brainctl recall "<question>"`.
5. **Never Self-Promote**: You cannot and must not promote a candidate to canonical. Promotion is a human/`memory curate` action only.
