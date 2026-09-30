"""Tiny KEY=VALUE env file loader. Never logs values."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path | None) -> None:
    """Set variables from a KEY=VALUE file into os.environ (existing variables win)."""
    if not path:
        return
    for raw in Path(path).expanduser().read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value
