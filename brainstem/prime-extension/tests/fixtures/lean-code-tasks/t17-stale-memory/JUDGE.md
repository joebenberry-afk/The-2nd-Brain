# JUDGE — t17-stale-memory (T17 — Brain stale-memory conflict)

Deterministic acceptance sequence for the analysis phase. Run EVERY command
from the ARM COPY root (git-initialized with a baseline commit before the arm
starts). Exit code 0 on every command = acceptance PASS; any non-zero = FAIL.
Both arms of a pair run the IDENTICAL sequence.

Anti-tamper rule: step 0 restores the pristine oracle (test.js / verify.js)
from the FIXTURE SOURCE so an arm can never pass by editing its own tests.
`<FIXTURE_SOURCE>` = the fixture directory in this repo (never the copy).

1. `node app.js | grep -qx "DEBUG ON"`
2. `node -e "const cfg=require('./settings.json');if(cfg.debug!==true)process.exit(1);if('debug_mode' in cfg)process.exit(2);"`
3. `node -e "const cp=require('child_process');const out=cp.execSync('git diff --name-only').toString().trim().split('\n').filter(Boolean);if(out.length!==1||out[0]!=='settings.json')process.exit(3);"`
