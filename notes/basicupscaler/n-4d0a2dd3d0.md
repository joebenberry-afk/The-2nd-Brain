---
id: n-4d0a2dd3d0
kind: note
at: 2026-10-02T04:39:21Z
source: agent
---

Claude Code Bash tool on Windows (Git Bash): every double backslash in the command text is collapsed to a single one before the shell runs, even inside single quotes and quoted heredocs (cat <<'EOF' with a\nb prints a\nb). So a Python patch script fed by heredoc that writes "\n" gets a real newline: symptom 'SyntaxError: unterminated string literal' in the patched file, or an anchor that matches 0 times. Fix: write such scripts with the Write tool, or avoid backslash escapes in heredoc text.
