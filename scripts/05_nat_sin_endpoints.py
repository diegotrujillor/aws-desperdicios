#!/usr/bin/env python3
"""Desperdicio 5: NAT Gateway sin endpoints gateway para S3 y DynamoDB. Solo lectura."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aws_desperdicios.checks.nat_endpoints import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
