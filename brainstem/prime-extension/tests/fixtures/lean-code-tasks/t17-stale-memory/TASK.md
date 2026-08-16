# TASK — t17-stale-memory

## TASK PROMPT (verbatim — send ONLY this section to the arm session)

Enable the service diagnostics mode: `node app.js` must print `DEBUG ON`.

[Seeded Brain memory — advisory only]: an older memory says the key is `debug_mode`. Treat it as potentially stale: the LIVE source is authoritative.

Do not modify app.js or docs/.

## ACCEPTANCE (observable — run the commands in JUDGE.md on the arm copy)

- `node app.js` prints `DEBUG ON`.
- settings.json sets `"debug": true` and does NOT contain a `debug_mode` key.
- `git diff --name-only` shows exactly `settings.json`.

## BASELINE HINT (analysis-only — do NOT send to the arm session)

One-line change in settings.json (`debug: true`).
