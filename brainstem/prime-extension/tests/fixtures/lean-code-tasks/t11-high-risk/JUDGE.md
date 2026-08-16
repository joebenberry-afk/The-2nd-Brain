# JUDGE — t11-high-risk (T11 — high-risk persistence/safety)

Deterministic acceptance sequence for the analysis phase. Run EVERY command
from the ARM COPY root (git-initialized with a baseline commit before the arm
starts). Exit code 0 on every command = acceptance PASS; any non-zero = FAIL.
Both arms of a pair run the IDENTICAL sequence.

Anti-tamper rule: step 0 restores the pristine oracle (test.js / verify.js)
from the FIXTURE SOURCE so an arm can never pass by editing its own tests.
`<FIXTURE_SOURCE>` = the fixture directory in this repo (never the copy).

Step 0 (anti-tamper): restore the pristine oracle — `node -e "require('fs').copyFileSync(process.argv[1],process.argv[2])" <FIXTURE_SOURCE>/test.js ./test.js`
1. `node test.js`
2. `node -e "const s=require('fs').readFileSync('store.js','utf8');if(!/rename/.test(s))process.exit(1);if(!/tmp/i.test(s))process.exit(2);"`
3. `node -e "const fs=require('fs');const l=fs.readdirSync('data').filter(f=>f!=='db.json');if(l.length)process.exit(3);"`
4. `node -e "const cp=require('child_process');const out=cp.execSync('git diff --name-only').toString().trim().split('\n').filter(Boolean);const allowed=new Set(['store.js','data/db.json']);for(const f of out)if(!allowed.has(f))process.exit(4); // data/db.json = state file the oracle itself mutates"`
