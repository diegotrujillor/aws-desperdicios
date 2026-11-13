#!/usr/bin/env python3
"""Desperdicio 4: grupos de logs de CloudWatch con retención infinita. Solo lectura."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aws_desperdicios.checks.log_retention import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
