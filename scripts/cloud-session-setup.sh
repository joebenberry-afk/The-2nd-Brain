#!/usr/bin/env bash
# Claude Code cloud-session bootstrap (SessionStart hook, .claude/settings.json).
# Builds the Python venv, the Prime extension's node_modules, and a Brain home
# rooted at this checkout whose memory corpus comes from the committed seed
# (scripts/cloud_corpus.py). Local sessions exit immediately: the Windows
# machine keeps its own venv and live Brain home.
set -euo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
unset PYTHONHOME PYTHONPATH
home="$PWD"

[ -x .venv/bin/python ] || uv venv --quiet .venv
uv pip install --quiet --python .venv/bin/python -e ".[dev]"

ext=brainstem/prime-extension
if [ ! -f "$ext/node_modules/.package-lock.json" ] ||
    [ "$ext/package-lock.json" -nt "$ext/node_modules/.package-lock.json" ]; then
    (cd "$ext" && npm ci --no-audit --no-fund --loglevel=error)
fi

export SECOND_BRAIN_HOME="$home"
.venv/bin/python -m second_brain init >/dev/null
.venv/bin/python scripts/cloud_corpus.py load
.venv/bin/python -m second_brain memory reindex

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    {
        echo "export SECOND_BRAIN_HOME=\"$home\""
        echo "export PATH=\"$home/.venv/bin:\$PATH\""
    } >>"$CLAUDE_ENV_FILE"
fi
