# JUDGE — t15-substantial (T15 — substantial independent task)

Deterministic acceptance sequence for the analysis phase. Run EVERY command
from the ARM COPY root (git-initialized with a baseline commit before the arm
starts). Exit code 0 on every command = acceptance PASS; any non-zero = FAIL.
Both arms of a pair run the IDENTICAL sequence.

Anti-tamper rule: step 0 restores the pristine oracle (test.js / verify.js)
from the FIXTURE SOURCE so an arm can never pass by editing its own tests.
`<FIXTURE_SOURCE>` = the fixture directory in this repo (never the copy).

Step 0 (anti-tamper): restore the pristine oracle — `node -e "require('fs').copyFileSync(process.argv[1],process.argv[2])" <FIXTURE_SOURCE>/test.js ./test.js`

1. `node stats.js data/transactions.csv | grep -qx "mean: 19.94"`
2. `node stats.js data/transactions.csv | grep -qx "median: 17.75"`
3. `node stats.js data/transactions.csv | grep -qx "min: 8.25"`
4. `node stats.js data/transactions.csv | grep -qx "max: 40.00"`
5. `node stats.js missing.csv 2>/dev/null; test $? -eq 1`
6. `printf "date,amount\n" > empty.csv; node stats.js empty.csv 2>/dev/null; test $? -eq 2; rm -f empty.csv`
7. `node test.js`
8. `node -e "const cp=require('child_process');const out=cp.execSync('git status --porcelain').toString();for(const line of out.split('\n')){if(!line)continue;const st=line.slice(0,2).trim();const p=line.slice(3);if(st==='??'&&p!=='stats.js'&&p!=='test.js')process.exit(5);}"`