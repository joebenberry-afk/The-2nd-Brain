"""Harness adapter modules (Codex, Antigravity, Claude Code).

Each adapter module exports one public ``run(home: Path) -> int`` entry
point that ``cli.py``'s autoinject dispatcher delegates to. Adapters
depend on the rest of the ``second_brain`` package (e.g. ``autoinject``,
``contracts``); nothing in ``second_brain`` may import from ``adapters``.
"""
