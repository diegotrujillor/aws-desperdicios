#!/usr/bin/env python3
"""Desperdicio 3: entornos de desarrollo y pruebas encendidos 24/7. Solo lectura."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aws_desperdicios.checks.dev_schedule import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
