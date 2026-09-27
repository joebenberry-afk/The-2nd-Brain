#!/usr/bin/env bash
# Claude Code cloud-session bootstrap (SessionStart hook, .claude/settings.json).
# Installs brain/'s test dependencies, puts a `brain` shim on PATH and points
# SECOND_BRAIN_HOME at this checkout. Local sessions exit immediately.
set -euo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
home="$PWD"

# brain/ has no runtime dependencies; node_modules is only for its tests.
if [ ! -f brain/node_modules/.package-lock.json ] ||
    [ brain/package-lock.json -nt brain/node_modules/.package-lock.json ]; then
    (cd brain && npm ci --no-audit --no-fund --loglevel=error)
fi
mkdir -p state/bin
printf '#!/usr/bin/env bash\nexec node "%s/brain/bin/brain.mjs" "$@"\n' "$home" >state/bin/brain
chmod +x state/bin/brain

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    {
        echo "export SECOND_BRAIN_HOME=\"$home\""
        echo "export PATH=\"$home/state/bin:\$PATH\""
    } >>"$CLAUDE_ENV_FILE"
fi
