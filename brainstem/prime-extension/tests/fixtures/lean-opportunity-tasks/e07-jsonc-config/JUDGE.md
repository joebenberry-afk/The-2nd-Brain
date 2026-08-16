# JUDGE — e07-jsonc-config (E7 — legitimate dependency)

Deterministic acceptance for the analysis phase. Run EVERY command from the
ARM COPY root (git-initialized with a baseline commit before the arm starts).
Exit code 0 on every numbered command = acceptance PASS; any non-zero = FAIL.
Both arms of a pair run the IDENTICAL sequence.

Anti-tamper rule: step 0 restores the pristine oracle (tests/test.js /
verify.js) from the FIXTURE SOURCE so an arm can never pass by editing its
own tests. `<FIXTURE_SOURCE>` = the fixture directory in this repo (never the
copy).

Step 0 (anti-tamper): restore the pristine oracle — `node -e "require('fs').copyFileSync(process.argv[1],process.argv[2])" <FIXTURE_SOURCE>/tests/test.js ./tests/test.js`
1. `node tests/test.js`
2. `node -e "const s=require('fs').readFileSync('src/config.js','utf8');if(!/jsonc-simple/.test(s))process.exit(3);"`


METRICS (recorded as evidence, NOT gates — the analysis phase captures these
from the arm copy and reports them per arm):
- `git diff --numstat` (added/deleted per file)
- `git diff --name-only` (changed files)
- `git status --porcelain` (untracked/new files)
- LC decision codes from the arm report (LC_REUSE, LC_NEW_TOOL_JUSTIFIED,
  LC_DEP_REJECTED, LC_DEP_ACCEPTED, LC_PREP_REFACTOR,
  LC_ABSTRACTION_JUSTIFIED, LC_DEFERRED_DEBT, LC_STOP)
