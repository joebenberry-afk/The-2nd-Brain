# JUDGE — t02-existing-reuse (T2 — existing function reuse)

Deterministic acceptance sequence for the analysis phase. Run EVERY command
from the ARM COPY root (git-initialized with a baseline commit before the arm
starts). Exit code 0 on every command = acceptance PASS; any non-zero = FAIL.
Both arms of a pair run the IDENTICAL sequence.

Anti-tamper rule: step 0 restores the pristine oracle (test.js / verify.js)
from the FIXTURE SOURCE so an arm can never pass by editing its own tests.
`<FIXTURE_SOURCE>` = the fixture directory in this repo (never the copy).

1. `node cli.js title hello world | grep -qx "Hello World"`
2. `node cli.js title oNCE uPON A | grep -qx "Once Upon A"`
3. `node -e "const s=require('fs').readFileSync('cli.js','utf8');if(!/lib\/strings/.test(s))process.exit(1);"`
4. `node -e "const cp=require('child_process');const out=cp.execSync('git status --porcelain').toString();if(/\?\?/.test(out))process.exit(2);"`
