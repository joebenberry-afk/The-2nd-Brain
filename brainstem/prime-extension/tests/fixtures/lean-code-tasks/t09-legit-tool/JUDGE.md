# JUDGE — t09-legit-tool (T9 — legitimate new tool)

Deterministic acceptance sequence for the analysis phase. Run EVERY command
from the ARM COPY root (git-initialized with a baseline commit before the arm
starts). Exit code 0 on every command = acceptance PASS; any non-zero = FAIL.
Both arms of a pair run the IDENTICAL sequence.

Anti-tamper rule: step 0 restores the pristine oracle (test.js / verify.js)
from the FIXTURE SOURCE so an arm can never pass by editing its own tests.
`<FIXTURE_SOURCE>` = the fixture directory in this repo (never the copy).

1. `node -e "const out=require('child_process').execFileSync('node',['make_table.js'],{encoding:'utf8'});if(!out.includes('| name | qty |\n| apple | 3 |\n| pear | 5 |'))process.exit(1);if(!out.includes('| name | price |\n| apple | 1.5 |'))process.exit(2);"`
2. `node -e "const cp=require('child_process');const out=cp.execSync('git status --porcelain').toString();for(const line of out.split('\n')){if(!line)continue;const st=line.slice(0,2).trim();const p=line.slice(3);if(st==='??'&&p!=='make_table.js')process.exit(3);}"`
