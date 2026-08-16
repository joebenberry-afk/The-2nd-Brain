# JUDGE — t14-trivial (T14 — trivial task / no worker)

Deterministic acceptance sequence for the analysis phase. Run EVERY command
from the ARM COPY root (git-initialized with a baseline commit before the arm
starts). Exit code 0 on every command = acceptance PASS; any non-zero = FAIL.
Both arms of a pair run the IDENTICAL sequence.

Anti-tamper rule: step 0 restores the pristine oracle (test.js / verify.js)
from the FIXTURE SOURCE so an arm can never pass by editing its own tests.
`<FIXTURE_SOURCE>` = the fixture directory in this repo (never the copy).

1. `node app.js | grep -qx "title: P3 Eval"`
2. `node -e "const cp=require('child_process');const out=cp.execSync('git diff --name-only').toString().trim().split('\n').filter(Boolean);if(out.length!==1||out[0]!=='config.json')process.exit(1);"`
