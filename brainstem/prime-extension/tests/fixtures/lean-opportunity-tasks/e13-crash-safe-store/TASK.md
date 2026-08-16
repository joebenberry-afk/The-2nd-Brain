# TASK — e13-crash-safe-store

store.js persists user data to data/db.json. Make set() crash-safe: an interruption mid-write must never leave a corrupt db.json. This stores real user data, so verify the change carefully (the repo's tests should pass and the write pattern must be one that cannot corrupt the file).
