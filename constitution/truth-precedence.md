# Truth Precedence

What counts as truth when sources disagree, in order:

1. **Verified repository reality** — current code, tests, and reproduced
   runtime behavior of the project being worked on.
2. **Verified tool output** — deterministic tool/command results at the moment
   they were captured (freshness matters).
3. **Current canonical knowledge** — the highest-status current entry in the
   Brain with evidence grade VERIFIED, TESTED, or OBSERVED and a recent
   `last_verified_at`.
4. **Decisions** — accepted recorded decisions (`decisions/`, project
   `decisions.md`).
5. **Historical knowledge** — superseded or archived entries. Never presented
   as current.
6. **Inferred knowledge** — must carry grade INFERRED and must never be
   presented as verified.
7. **User instruction** — overrides all of the above when it is an explicit
   current instruction; user *preferences* are protected knowledge.

## Rules

- Repo contradiction supersedes stale memory. When repo reality contradicts a
  memory, the memory is marked labile and enters reconsolidation — it is not
  silently deleted.
- A memory retrieved from the Brain may never override what the agent can
  directly verify in the working repository.
- Evidence grades: OBSERVED < TESTED < VERIFIED; HISTORICAL and REJECTED are
  not current; INFERRED is explicitly not verification.
- Never equate retrieval count with truth.
