"""CLI entry point for steuer-assistent."""

from __future__ import annotations

import sys

from .core import main


if __name__ == "__main__":
    sys.exit(main())
