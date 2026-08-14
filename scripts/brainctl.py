"""brainctl launcher — runs the Brain CLI from a source checkout.

Sanitizes the known-bad PYTHONHOME/PYTHONPATH environment variables before
importing the package (see constitution/../AGENTS.md environment gotchas).
Usage: python scripts/brainctl.py <command...>
"""

import os
import sys

for _k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME"):
    os.environ.pop(_k, None)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from second_brain.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
