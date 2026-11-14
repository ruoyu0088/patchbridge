"""PatchBridge launcher.

This file intentionally uses only the Python standard library so it can report
missing runtime dependencies before importing the application package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pathspec": "pathspec",
    "charset_normalizer": "charset-normalizer",
}


def missing_packages() -> list[str]:
    return [package for module, package in REQUIRED.items() if importlib.util.find_spec(module) is None]


def main() -> int:
    if sys.version_info < (3, 11):
        print("PatchBridge requires Python 3.11 or newer.")
        print(f"Current interpreter: {sys.version.split()[0]} ({sys.executable})")
        return 1

    missing = missing_packages()
    if missing:
        print("PatchBridge cannot start because these Python packages are missing:")
        for package in missing:
            print(f"  - {package}")
        print()
        print("Install them once with:")
        print("  python -m pip install -r requirements.txt")
        print()
        try:
            input("Press Enter to close this window...")
        except EOFError:
            pass
        return 1

    sys.path.insert(0, str(ROOT / "src"))
    from patchbridge.__main__ import main as run  # imported only after dependency checks

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
