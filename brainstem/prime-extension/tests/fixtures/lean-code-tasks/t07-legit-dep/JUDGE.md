# JUDGE — t07-legit-dep (T7 — legitimate dependency)

Deterministic acceptance sequence for the analysis phase. Run EVERY command
from the ARM COPY root (git-initialized with a baseline commit before the arm
starts). Exit code 0 on every command = acceptance PASS; any non-zero = FAIL.
Both arms of a pair run the IDENTICAL sequence.

Anti-tamper rule: step 0 restores the pristine oracle (test.js / verify.js)
from the FIXTURE SOURCE so an arm can never pass by editing its own tests.
`<FIXTURE_SOURCE>` = the fixture directory in this repo (never the copy).

Step 0 (anti-tamper): restore the pristine oracle — `node -e "require('fs').copyFileSync(process.argv[1],process.argv[2])" <FIXTURE_SOURCE>/test.js ./test.js`
1. `node test.js`
2. `node -e "const s=require('fs').readFileSync('load.js','utf8');if(!/confparse/.test(s))process.exit(1);"`
3. `node -e "const cp=require('child_process');const out=cp.execSync('git diff --name-only').toString().trim().split('\n').filter(Boolean);const allowed=new Set(['load.js']);for(const f of out)if(!allowed.has(f))process.exit(2);"`
