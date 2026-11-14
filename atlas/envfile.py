"""Load local .env files without printing secrets.

The farm demo reads DEEPINFRA_API_KEY and ANTHROPIC_API_KEY. The sibling
rotation-atlas project stores the same credentials as DREX_API_KEY and
FRONTIER_API_KEY. This copies those across when the farm names are unset.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def load_local_env() -> None:
    for path in (_ROOT / ".env", _ROOT.parent / "rotation-atlas" / ".env"):
        _apply(path)
    if not os.environ.get("DEEPINFRA_API_KEY") and os.environ.get("DREX_API_KEY"):
        os.environ["DEEPINFRA_API_KEY"] = os.environ["DREX_API_KEY"]
    if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("FRONTIER_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["FRONTIER_API_KEY"]


def _apply(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
