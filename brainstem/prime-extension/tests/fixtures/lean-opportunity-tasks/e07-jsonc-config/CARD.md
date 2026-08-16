# Evaluation Card — e07 (E7 — legitimate dependency)  [EVALUATOR-ONLY — never shown to arms]

- **task_id**: e07
- **user-style request**: Parse JSONC (comments + trailing commas, '//' inside strings preserved).
- **repository/fixture baseline**: config/server.json5 is JSONC; loadConfig uses JSON.parse (fails); jsonc-simple 1.4.2 is ALREADY in package.json dependencies (vendored).
- **acceptance criteria** (behavior; enforced by JUDGE.md): tests/test.js passes: host/port parsed and the URL keeps its inner '//'.
- **current reusable capabilities**: jsonc-simple (maintained, listed dependency) handles the exact edge case; no network needed (vendored).
- **risk level**: LOW
- **known legitimate solution classes** (any of these satisfy acceptance):
A. use the listed jsonc-simple dependency (one require + parse)\nB. jsonc-simple through a tiny wrapper
- **known unjustified expansion classes** (pass acceptance but cost tokens/
  context; measured as metrics — never gates):
C. hand-rolled regex comment-stripper (breaks the URL case or adds fragile code)\nD. a NEW different parser dependency\nE. preprocessing the file into strict JSON
- **metrics to collect**: files touched, added/deleted lines, new files,
  new deps/tools/modules, LC codes, input/output/cache_read/cache_write/cost,
  turns, tool_calls, wall_ms, AutoInject packet tokens (separate), judge
  exits, acceptance.
