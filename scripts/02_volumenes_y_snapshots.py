#!/usr/bin/env python3
"""Desperdicio 2: volúmenes EBS sin adjuntar y snapshots antiguos. Solo lectura."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aws_desperdicios.checks.orphan_storage import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
