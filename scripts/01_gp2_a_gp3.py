#!/usr/bin/env python3
"""Desperdicio 1: volúmenes EBS gp2 que podrían ser gp3. Solo lectura."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aws_desperdicios.checks.gp2_to_gp3 import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
