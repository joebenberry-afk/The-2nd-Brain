# Change Control

## Constitution amendments

- Require: explicit review, written rationale, evidence, reviewer identity.
- Performed only through Git (visible history), never silently by learning
  machinery.
- Conflicts between Constitution rules are STOP conditions — stop and report,
  do not improvise.

## Milestones and gates

- Each phase gate requires its acceptance criteria to be demonstrably
  satisfied, with a milestone report at `outputs/reports/<milestone>.md`
  containing: what changed, exact files, tests, results, metrics, deviations,
  known risks, rollback, next gate.

## Rollback requirements

Every milestone must support:

1. disable extension;
2. restore config;
3. restore DB;
4. restore Git;
5. remove project manifest markers.

The Brainstem must be removable without breaking managed projects.

## Git policy

- `main` = stable Brain state.
- Large structural changes on `brain/<feature>` branches.
- Commit categories: `brain(core|memory|skill|policy|project|immune|db|adapter)`.

## Stop conditions (plan §147)

Stop and report if: root conflicts with unrelated data; global config cannot
merge safely; Prime hook API differs materially from the assumed architecture;
adapter would overwrite unrelated skill dirs; DB migration not idempotent;
artifact recovery not byte-identical; PID/process ownership ambiguous; context
pruning could delete unrecoverable data; skill security review fails;
Constitution rules conflict; a benchmark shows a meaningful regression.
