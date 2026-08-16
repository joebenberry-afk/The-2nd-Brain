# Evaluation Card — e01 (E1 — config instead of code)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e01
- **user-style request**: Add staging profile with 15s timeout; prod keeps 30s.
- **repository/fixture baseline**: deploy.js + lib/runner.js read config/profiles.json; only prod + a default timeout exist.
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: run('prod') prints timeout=30000 and run('staging') prints timeout=15000.
- **current reusable capabilities**: profiles.json already drives timeouts; runner already resolves profiles with a default fallback.
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. add a 'staging' entry to config/profiles.json (timeout_ms 15000)\nB. A + a tiny default-timeout tweak
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. new ProfileManager/Environment class\nD. CLI flag machinery (--timeout)\nE. new config format or env abstraction\nF. new dependency
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
