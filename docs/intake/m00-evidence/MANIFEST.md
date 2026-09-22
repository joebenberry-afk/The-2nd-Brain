# M00 evidence pack — tracked copies and provenance

The campaign's working references lived in `outputs/reports/**`, which is **gitignored** (`.gitignore:73`):
a fresh worktree, a fresh clone or a later session could not open them, and a register row that says
"see that report" then costs the next session an archaeology step. This directory brings forward the
**bounded material the current claims rest on**, with provenance.

Rule for every entry: *origin tree, path, revision where applicable, digest of the copy, and the scope
of what it supports*. A digest proves the copy is the bytes it claims to be; it does **not** make the
source authoritative or current — that is what the revision and the verdict columns are for.

| Copy | Origin tree / path | Revision | sha256 | Scope it supports |
| --- | --- | --- | --- | --- |
| `replay-authority.md` | `.worktrees/m00.3-producer-guard` → `outputs/reports/m00.3-replay-authority-20260922/REPORT.md` | `9a32a9b` (report frozen at `f6e817f`) | `114b4cef…115db` | #3-R.2/#3-R.4 corrected replay expectation, the 8 cases, mutation sensitivity, the read-only finding under #4 |
| `mutation-evidence.json` | same tree → `…/mutation-evidence.json` | `b5f809f` | `1a90be26…7ab0` | guard-removal 5/8 failed, reconstruction-removal 7/8 failed, exact byte restoration, baseline hashes |
| `vitest-full-transcript.txt` | same tree → `…/vitest-full-transcript.txt` | `9a32a9b` | `2c642bdc…12ec` | extension suite 771/771 including the replay cases and per-case identity lines |
| `schema-authority.md` | same tree → `outputs/reports/m00.3-schema-authority-20260922/REPORT.md` | `b5f809f` | `67913db5…d5df` | #2b increment: reserved names unowned, import-time registration, authority-chosen transition, version namespaces, `schema_dump`, gate repairs |
| `pytest-schema-neighborhood.txt` | same tree → `…/pytest-schema-neighborhood.txt` | `b5f809f` | `40ceaa0a…1bef` | 398 passed on the applicable Python set (the transcript names each test) |
| `admission-issuance.md` | same tree → `outputs/reports/m00.3-admission-issuance-20260922/REPORT.md` | `40c0c96` | `f4db94c5…1250` | #4/ADM: `worker_context` hands the caller the credential it mints; issuer closure isolated as a partial external blocker |
| `worker-settlement.md` | same tree → `outputs/reports/m00.3-worker-settlement-20260922/REPORT.md` | `b5f809f` | `87043a64…d39ce` | #5: ten sequential workers; ownership/receipt/cancellation matrix; finalization-vs-release distinction |
| `ownership-edges.json` | same tree → `…/ownership-edges.json` | `b5f809f` | `ed1bb4db…98cf` | raw observations behind the #5 edge matrix (quarantine, `WORKTREE_WRITER_BUSY`, duplicate/conflict, cancellation) |
| `ten-worker-sequence.json` | same tree → `…/ten-worker-sequence.json` | `9a32a9b` | `83932116…5cd9` | raw observations behind the ten-worker sequence (10 × `COMPLETED`/`released`, 1 result each) |

Also referenced and **not** copied here, with their retrieval route:

| Reference | Where it lives | Route |
| --- | --- | --- |
| `Second_Brain_M00_OneShot_Closure_Mandate.md` | `docs/intake/` (this tree and `main`) | tracked in this worktree already |
| `M00.3_Phase_A_Host_Authority_Continuation.md` | `docs/requirements/` in `main` only | absent from this branch; read from the main checkout |
| `schema-bootstrap-20260921/QUALIFICATION.md` | `outputs/reports/` in `main` only (gitignored) | read from the main checkout; the #2b debt list it carries is restated in `schema-authority.md` §8 |
| `m00.2-p2-lease-and-manifest-20260921/REPORT.md` | `outputs/reports/` in `main` only | read from the main checkout |

That last group is the honest residue: those sources are outside this candidate, the register must
keep naming the tree they live in, and the campaign must not claim a candidate seal includes them.

## Correction applied to a claim in this pack

The #2b acceptance item "prove reopening performs no writes" was previously phrased around a *write
witness* without scoping it. That is now split, because the cheap candidate witness does not carry the
claim:

- **Logical idempotency** — reopening preserves the required data and schema. Demonstrated by structural
  comparison plus the surviving rows (`schema-authority.md` §7).
- **Write-free reopening** — the tested path performs no prohibited writes. This needs instrumentation
  that covers rolled-back work and other files, not a single counter. `PRAGMA data_version` is **not**
  sufficient on its own: it reports *another* connection's commits, only when compared before/after on
  the *same* connection, and says nothing about rolled-back work or non-database writes. `total_changes`
  counts specified row modifications through one connection. Whatever witness is used must itself be
  tested with a deliberately introduced change. `#2b` therefore stays `IN_PROGRESS` on this point.
