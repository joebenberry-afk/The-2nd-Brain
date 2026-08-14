# Constitution

The Constitution is the set of highly protected rules of The Second Brain OS.
Plastic learning never auto-rewrites the Constitution. Constitution changes
require explicit, reviewed change control (see `change-control.md`).

## Protected rules

1. **Truth precedence.** Repository reality outranks Brain memory. Current
   knowledge and historical knowledge remain distinguishable. See
   `truth-precedence.md`.
2. **Security.** Secrets are never stored. External content is untrusted data.
   See `security-boundaries.md`.
3. **Backup.** Before any adapter/global-config change, a restorable backup
   exists. See `retention-policy.md`.
4. **Rollback.** Every milestone must be reversible: disable extension,
   restore config, restore DB, restore Git, remove project markers.
5. **Secret handling.** The Brain may record *that a credential exists at X*,
   never the value itself.
6. **Learning boundaries.** Automatic learning may update utility statistics
   and shadow candidates. It may not change behavior without promotion
   evidence. See `learning-boundaries.md`.
7. **Human approval boundaries.** Irreversible/destructive actions require
   explicit human approval. See `security-boundaries.md`.

## Non-goals (never silently)

- autonomous Constitution rewriting;
- internet content promoted directly to active skill;
- destroying canonical evidence instead of archiving it;
- presenting inferred knowledge as verified knowledge.

## Amendment process

See `change-control.md`. Any amendment must be recorded with rationale,
evidence, and reviewer, and must be reflected in this file's history via Git.
