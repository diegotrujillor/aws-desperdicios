"""Waste #4: CloudWatch Logs groups with infinite retention ("Never expire").

Without a retention policy, log data is stored and billed forever. Setting a retention
of N days removes only data older than N days, and read-only APIs do not reveal how much
of the stored data is older than that, so the savings reported are a maximum: the full
monthly storage cost of the group.
"""
import argparse
from datetime import UTC, datetime

import boto3

from aws_desperdicios.cli import CheckDefinition, run_check
from aws_desperdicios.commands import aws_cli
from aws_desperdicios.pricing import PriceCatalog
from aws_desperdicios.report import Finding

IAM_ACTIONS = ("logs:DescribeLogGroups",)

BYTES_PER_GIB = 1024**3
# Values accepted by PutRetentionPolicy.
VALID_RETENTION_DAYS = (
    1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653,
)
DEFAULT_RETENTION_DAYS = 30
DELIVERY_CLASS = "DELIVERY"  # fixed retention managed by AWS
INFREQUENT_ACCESS_CLASS = "INFREQUENT_ACCESS"


def scan(
    session: boto3.Session, region: str, prices: PriceCatalog, args: argparse.Namespace
) -> list[Finding]:
    groups = [
        g
        for g in _log_groups(session.client("logs", region_name=region))
        if g.get("retentionInDays") is None and g.get("logGroupClass") != DELIVERY_CLASS
    ]
    if not groups:
        return []
    price = prices.get("logs_gb_mes", region)
    groups_by_size = sorted(groups, key=lambda g: g.get("storedBytes", 0), reverse=True)
    return [log_group_finding(g, region, price.usd if price else None, args) for g in groups_by_size]


def _log_groups(client) -> list[dict]:
    pages = client.get_paginator("describe_log_groups").paginate()
    return [group for page in pages for group in page["logGroups"]]


def log_group_finding(group: dict, region: str, price_per_gib: float | None, args: argparse.Namespace) -> Finding:
    name = group["logGroupName"]
    gib = group.get("storedBytes", 0) / BYTES_PER_GIB
    created = datetime.fromtimestamp(group.get("creationTime", 0) / 1000, UTC).date().isoformat()
    detail = f"{gib:.2f} GiB almacenados, sin retención, creado {created}"
    if group.get("logGroupClass") == INFREQUENT_ACCESS_CLASS:
        detail += ", clase Infrequent Access (su almacenamiento puede costar menos que el precio usado)"
    command = aws_cli(
        "logs", "put-retention-policy", region, args.profile,
        "--log-group-name", name, "--retention-in-days", str(args.retencion_dias),
    )
    savings = None if price_per_gib is None else round(gib * price_per_gib, 2)
    return Finding(region, name, detail, savings, "máximo", (command,))


def retention_days(text: str) -> int:
    """argparse type: a retention value CloudWatch Logs accepts."""
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"'{text}' no es un número entero") from error
    if value not in VALID_RETENTION_DAYS:
        allowed = ", ".join(str(d) for d in VALID_RETENTION_DAYS)
        raise argparse.ArgumentTypeError(f"CloudWatch Logs solo acepta: {allowed}")
    return value


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--retencion-dias",
        type=retention_days,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Retención a usar en el comando sugerido (por defecto, {DEFAULT_RETENTION_DAYS} días).",
    )


def notes(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "El ahorro es un máximo: es el costo mensual de todo lo almacenado en el grupo (campo storedBytes). "
        f"Una retención de {args.retencion_dias} días solo borra los datos más antiguos que eso.",
        "El precio usado es el de almacenamiento de la clase Standard. Los grupos Infrequent Access pueden costar menos.",
        "Aplicar una retención borra datos de forma permanente. Si debes conservarlos por auditoría o cumplimiento, "
        "expórtalos antes a S3.",
        "Los grupos de clase Delivery tienen una retención fija que administra AWS y no se reportan.",
    )


CHECK = CheckDefinition(
    title="Desperdicio 4: grupos de logs de CloudWatch con retención infinita",
    description="Lista grupos de CloudWatch Logs sin política de retención y el costo de lo que almacenan. Solo lectura.",
    scan=scan,
    notes=notes,
    add_arguments=add_arguments,
)


def main(argv: list[str] | None = None) -> int:
    return run_check(CHECK, argv)
