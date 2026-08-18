# Second Brain Core Rule for Claude Code

This workspace is integrated with The Second Brain via native SessionStart/
PreCompact/Stop hooks (P3a).

## Operating Principles

1. **Source Authority**: Current repository source, verified tests, and live tool evidence strictly outrank Second Brain memory.
2. **No Automatic Retrieval**: SessionStart and PreCompact never inject memory or project history into context. Nothing here changes that.
3. **Single Source of Truth**: Do not create parallel memory databases or session ledgers. Reuse the existing Second Brain store.
4. **Candidate-Only Writeback**: You may record a durable, evidence-backed finding by ending a turn with this exact block:

   ```
   <!--second-brain-candidate
   title: <one line>
   observation: <what was learned>
   evidence: <reproducible command, file+line, or test name>
   -->
   ```

   The Stop hook writes this as a `candidate` memory only -- never canonical. Omit `evidence` (or leave it blank) and nothing is written: empirical claims without evidence are dropped, not recorded. Do not emit this marker for routine activity (searches, listings, ordinary passing tests) -- only for something plausibly reusable in a future session.
5. **Never Self-Promote**: You cannot and must not promote a candidate to canonical. Promotion is a human/`memory curate` action only.
