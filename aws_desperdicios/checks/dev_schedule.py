"""Waste #3: development and test environments running 24/7.

Finds running EC2 instances and available RDS instances tagged as non-production and
estimates what they would save running only N hours per week. AWS prices on-demand
compute per hour and uses 730 hours per month.
"""
import argparse

import boto3

from aws_desperdicios.cli import CheckDefinition, int_in_range, run_check
from aws_desperdicios.commands import aws_cli
from aws_desperdicios.pricing import PriceCatalog, rds_variant
from aws_desperdicios.report import Finding

IAM_ACTIONS = ("ec2:DescribeInstances", "rds:DescribeDBInstances")

HOURS_PER_WEEK = 168
HOURS_PER_MONTH = 730
DEFAULT_WEEKLY_HOURS = 60  # 12 h x 5 working days
DEFAULT_TAG_KEYS = ("Environment", "Env", "Entorno", "Stage")
DEFAULT_TAG_VALUES = (
    "dev", "development", "desarrollo", "test", "testing", "pruebas", "qa", "staging", "stage", "stg", "sandbox", "uat",
)
ASG_TAG = "aws:autoscaling:groupName"
LINUX_PLATFORM = "Linux/UNIX"
RDS_ENGINES = {
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "mariadb": "MariaDB",
    "aurora-mysql": "Aurora MySQL",
    "aurora-postgresql": "Aurora PostgreSQL",
}
AURORA_IO_OPTIMIZED = "aurora-iopt1"


def monthly_hours_off(weekly_hours_on: int) -> float:
    return HOURS_PER_MONTH * (HOURS_PER_WEEK - weekly_hours_on) / HOURS_PER_WEEK


def matching_tag(tags: list[dict], args: argparse.Namespace) -> str | None:
    """'Key=Value' of the first tag marking the resource as non-production, or None."""
    keys = {k.lower() for k in (args.etiqueta or DEFAULT_TAG_KEYS)}
    values = {v.lower() for v in args.valores}
    return next(
        (f"{t['Key']}={t['Value']}" for t in tags if t["Key"].lower() in keys and t["Value"].lower() in values),
        None,
    )


def scan(
    session: boto3.Session, region: str, prices: PriceCatalog, args: argparse.Namespace
) -> list[Finding]:
    return _ec2_findings(session, region, prices, args) + _rds_findings(session, region, prices, args)


def _running_instances(session, region: str):
    pages = session.client("ec2", region_name=region).get_paginator("describe_instances").paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )
    for page in pages:
        for reservation in page["Reservations"]:
            yield from reservation["Instances"]


def _ec2_findings(session, region: str, prices: PriceCatalog, args: argparse.Namespace) -> list[Finding]:
    findings = []
    for instance in _running_instances(session, region):
        tag = matching_tag(instance.get("Tags", []), args)
        if tag:
            findings.append(ec2_finding(instance, region, _ec2_hourly(instance, region, prices), args, tag))
    return findings


def _platform(instance: dict) -> str:
    # AWS always returns PlatformDetails; Platform is only a fallback for partial responses.
    return instance.get("PlatformDetails") or ("Windows" if instance.get("Platform") == "windows" else LINUX_PLATFORM)


def _ec2_hourly(instance: dict, region: str, prices: PriceCatalog) -> float | None:
    if instance.get("InstanceLifecycle") == "spot" or _platform(instance) != LINUX_PLATFORM:
        return None
    if instance.get("Placement", {}).get("Tenancy", "default") != "default":
        return None
    price = prices.get("ec2_linux_hora", region, instance["InstanceType"])
    return None if price is None else price.usd


def ec2_finding(instance: dict, region: str, hourly: float | None, args: argparse.Namespace, tag: str) -> Finding:
    instance_id = instance["InstanceId"]
    tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
    detail = f"EC2 {instance['InstanceType']}{_name(tags)}, {tag}"
    platform = _platform(instance)
    if platform != LINUX_PLATFORM:
        detail += f", plataforma {platform} (sin precio: solo se calcula Linux/UNIX)"
    if instance.get("InstanceLifecycle") == "spot":
        detail += ", instancia spot (el precio on-demand no aplica)"
    commands = (aws_cli("ec2", "stop-instances", region, args.profile, "--instance-ids", instance_id),)
    if ASG_TAG in tags:
        detail += f", grupo de Auto Scaling {tags[ASG_TAG]}: programa la capacidad del grupo en vez de detenerla"
        commands = ()
    return Finding(region, instance_id, detail, _savings(hourly, args), "exacto", commands)


def _rds_findings(session, region: str, prices: PriceCatalog, args: argparse.Namespace) -> list[Finding]:
    pages = session.client("rds", region_name=region).get_paginator("describe_db_instances").paginate()
    findings = []
    for db in (db for page in pages for db in page["DBInstances"]):
        tag = matching_tag(db.get("TagList", []), args)
        if not tag or db.get("DBInstanceStatus") != "available":
            continue
        variant = rds_price_variant(db)
        price = prices.get("rds_hora", region, variant) if variant else None
        findings.append(rds_finding(db, region, price.usd if price else None, args, tag))
    return findings


def rds_price_variant(db: dict) -> str | None:
    """Price variant for an RDS instance, or None for engines the price table does not cover."""
    engine = RDS_ENGINES.get(db["Engine"])
    if engine is None:
        return None
    if db["Engine"].startswith("aurora"):
        storage = "Aurora IO Optimization Mode" if db.get("StorageType") == AURORA_IO_OPTIMIZED else "EBS Only"
        return rds_variant(engine, "Single-AZ", db["DBInstanceClass"], storage)
    deployment = "Multi-AZ" if db.get("MultiAZ") else "Single-AZ"
    return rds_variant(engine, deployment, db["DBInstanceClass"], "EBS Only")


def rds_finding(db: dict, region: str, hourly: float | None, args: argparse.Namespace, tag: str) -> Finding:
    identifier = db["DBInstanceIdentifier"]
    multi_az = " Multi-AZ" if db.get("MultiAZ") else ""
    detail = f"RDS {db['Engine']} {db['DBInstanceClass']}{multi_az}, {tag}"
    if db.get("ReadReplicaSourceDBInstanceIdentifier"):
        detail += ", réplica de lectura: AWS no permite detenerla; considera borrarla fuera de horario"
        return Finding(region, identifier, detail, None, "exacto")
    if db["Engine"] not in RDS_ENGINES:
        detail += " (motor sin precio: solo se calcula MySQL, PostgreSQL, MariaDB y Aurora)"
    cluster = db.get("DBClusterIdentifier")
    if cluster:
        command = aws_cli("rds", "stop-db-cluster", region, args.profile, "--db-cluster-identifier", cluster)
    else:
        command = aws_cli("rds", "stop-db-instance", region, args.profile, "--db-instance-identifier", identifier)
    return Finding(region, identifier, detail, _savings(hourly, args), "exacto", (command,))


def _savings(hourly: float | None, args: argparse.Namespace) -> float | None:
    return None if hourly is None else round(hourly * monthly_hours_off(args.horas_semana), 2)


def _name(tags: dict) -> str:
    return f" ({tags['Name']})" if tags.get("Name") else ""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--etiqueta",
        action="append",
        metavar="CLAVE",
        help=f"Clave de etiqueta que marca el entorno; se puede repetir (por defecto: {', '.join(DEFAULT_TAG_KEYS)}).",
    )
    parser.add_argument(
        "--valores",
        type=lambda text: tuple(v.strip() for v in text.split(",") if v.strip()),
        default=DEFAULT_TAG_VALUES,
        help=f"Valores separados por coma que indican dev/test (por defecto: {','.join(DEFAULT_TAG_VALUES)}).",
    )
    parser.add_argument(
        "--horas-semana",
        type=int_in_range(0, HOURS_PER_WEEK),
        default=DEFAULT_WEEKLY_HOURS,
        help=f"Horas por semana que el entorno sí debe estar encendido (por defecto, {DEFAULT_WEEKLY_HOURS}: 12 h x 5 días).",
    )


def notes(args: argparse.Namespace) -> tuple[str, ...]:
    keys = ", ".join(args.etiqueta or DEFAULT_TAG_KEYS)
    return (
        f"Supuesto: el entorno solo necesita estar encendido {args.horas_semana} h por semana. Ahorro = precio por hora "
        f"x {monthly_hours_off(args.horas_semana):.0f} h apagadas al mes (730 h/mes x (168 - {args.horas_semana}) / 168). "
        "Ajusta el supuesto con --horas-semana.",
        f"Solo se detectan recursos con alguna de estas etiquetas: {keys}; con valores: {', '.join(args.valores)}. "
        "Los recursos sin etiqueta no aparecen.",
        "Solo se calcula el cómputo: los volúmenes EBS y el almacenamiento de RDS se siguen cobrando con el recurso apagado.",
        "AWS vuelve a encender automáticamente una base RDS o un clúster Aurora detenidos después de 7 días.",
        "EC2: el precio solo se calcula para Linux/UNIX con tenencia compartida; las demás aparecen sin precio.",
    )


CHECK = CheckDefinition(
    title="Desperdicio 3: entornos de desarrollo y pruebas encendidos 24/7",
    description=(
        "Lista EC2 y RDS etiquetados como dev/test que están encendidos y calcula el ahorro "
        "de apagarlos fuera de horario. Solo lectura."
    ),
    scan=scan,
    notes=notes,
    add_arguments=add_arguments,
)


def main(argv: list[str] | None = None) -> int:
    return run_check(CHECK, argv)
