"""Waste #2: unattached EBS volumes and old EBS snapshots.

- Unattached volume: you pay its full monthly cost (storage + provisioned IOPS/throughput)
  while it does nothing. Savings are exact.
- Old snapshot: snapshots are incremental, and read-only APIs do not expose the bytes each
  one actually bills. The source volume size is used as an upper bound, so savings are a maximum.
"""
import argparse
from datetime import UTC, datetime, timedelta

import boto3

from aws_desperdicios.cli import CheckDefinition, non_negative_int, run_check
from aws_desperdicios.commands import aws_cli
from aws_desperdicios.ebs import volume_monthly_cost
from aws_desperdicios.pricing import PriceCatalog
from aws_desperdicios.report import Finding

IAM_ACTIONS = ("ec2:DescribeVolumes", "ec2:DescribeSnapshots", "ec2:DescribeImages")

DEFAULT_SNAPSHOT_AGE_DAYS = 90
BACKUP_DESCRIPTION_PREFIX = "This snapshot is created by the AWS Backup service"


def scan(
    session: boto3.Session, region: str, prices: PriceCatalog, args: argparse.Namespace
) -> list[Finding]:
    ec2 = session.client("ec2", region_name=region)
    volumes = _all_volumes(ec2)
    unattached = [
        _volume_finding(v, region, prices, args.profile) for v in volumes if v["State"] == "available"
    ]
    return unattached + _snapshot_findings(ec2, region, prices, args, {v["VolumeId"] for v in volumes})


def _all_volumes(ec2) -> list[dict]:
    pages = ec2.get_paginator("describe_volumes").paginate()
    return [volume for page in pages for volume in page["Volumes"]]


def _volume_finding(volume: dict, region: str, prices: PriceCatalog, profile: str | None) -> Finding:
    volume_type, size = volume["VolumeType"], volume["Size"]
    cost = volume_monthly_cost(
        volume_type, size, volume.get("Iops", 0), volume.get("Throughput", 0), region, prices
    )
    return Finding(
        region=region,
        resource_id=volume["VolumeId"],
        detail=f"Volumen {size} GiB {volume_type} sin adjuntar{_name(volume)}, creado {_date(volume['CreateTime'])}",
        monthly_savings_usd=None if cost is None else round(cost, 2),
        savings_kind="exacto",
        suggested_commands=(aws_cli("ec2", "delete-volume", region, profile, "--volume-id", volume["VolumeId"]),),
    )


def _snapshot_findings(
    ec2, region: str, prices: PriceCatalog, args: argparse.Namespace, existing_volumes: set[str]
) -> list[Finding]:
    cutoff = datetime.now(UTC) - timedelta(days=args.dias)
    snapshots = [
        snapshot
        for page in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=["self"])
        for snapshot in page["Snapshots"]
        if snapshot["StartTime"] <= cutoff and snapshot.get("StorageTier", "standard") == "standard"
    ]
    if not snapshots:
        return []
    images_by_snapshot = _images_by_snapshot(ec2)
    price = prices.get("ebs_snapshot_gb_mes", region)
    return [
        _snapshot_finding(s, region, price, args.profile, images_by_snapshot, existing_volumes) for s in snapshots
    ]


def _images_by_snapshot(ec2) -> dict[str, str]:
    """snapshot id -> id of an AMI owned by this account that uses it."""
    images = ec2.describe_images(Owners=["self"])["Images"]
    return {
        mapping["Ebs"]["SnapshotId"]: image["ImageId"]
        for image in images
        for mapping in image.get("BlockDeviceMappings", [])
        if mapping.get("Ebs", {}).get("SnapshotId")
    }


def _snapshot_finding(
    snapshot: dict, region: str, price, profile: str | None, images: dict[str, str], existing_volumes: set[str]
) -> Finding:
    snapshot_id, size = snapshot["SnapshotId"], snapshot["VolumeSize"]
    detail = f"Snapshot de {size} GiB{_name(snapshot)}, creado {_date(snapshot['StartTime'])}"
    if snapshot.get("VolumeId") not in existing_volumes:
        detail += ", su volumen de origen ya no existe"
    blocker = _deletion_blocker(snapshot, images)
    if blocker:
        return Finding(region, snapshot_id, f"{detail}; {blocker}", None, "máximo")
    return Finding(
        region=region,
        resource_id=snapshot_id,
        detail=detail,
        monthly_savings_usd=None if price is None else round(size * price.usd, 2),
        savings_kind="máximo",
        suggested_commands=(aws_cli("ec2", "delete-snapshot", region, profile, "--snapshot-id", snapshot_id),),
    )


def _deletion_blocker(snapshot: dict, images: dict[str, str]) -> str | None:
    """Reason a snapshot cannot simply be deleted, or None."""
    if snapshot["SnapshotId"] in images:
        return f"lo usa la AMI {images[snapshot['SnapshotId']]}: primero hay que desregistrarla"
    if snapshot.get("Description", "").startswith(BACKUP_DESCRIPTION_PREFIX):
        return "lo administra AWS Backup: ajusta la retención del plan de respaldo"
    return None


def _name(resource: dict) -> str:
    name = next((t["Value"] for t in resource.get("Tags", []) if t["Key"] == "Name"), None)
    return f" ({name})" if name else ""


def _date(value: datetime) -> str:
    return value.date().isoformat()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dias",
        type=non_negative_int,
        default=DEFAULT_SNAPSHOT_AGE_DAYS,
        help=f"Antigüedad mínima, en días, de los snapshots a reportar (por defecto, {DEFAULT_SNAPSHOT_AGE_DAYS}).",
    )


def notes(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "Volúmenes: el ahorro es exacto (todo lo que cuesta el volumen). Si dudas en borrarlo, "
        "crea antes un snapshot: guardarlo cuesta menos por GB que el volumen.",
        f"Snapshots: se listan los propios con más de {args.dias} días. El ahorro es un máximo: se calcula "
        "con el tamaño del volumen de origen, pero los snapshots son incrementales y cada uno puede "
        "facturar menos. Borrar uno no borra los datos que otros snapshots todavía necesitan.",
        "Los snapshots usados por una AMI o administrados por AWS Backup se listan sin comando ni ahorro.",
    )


CHECK = CheckDefinition(
    title="Desperdicio 2: volúmenes EBS sin adjuntar y snapshots antiguos",
    description="Lista volúmenes EBS sin adjuntar y snapshots antiguos, con su costo mensual. Solo lectura.",
    scan=scan,
    notes=notes,
    add_arguments=add_arguments,
)


def main(argv: list[str] | None = None) -> int:
    return run_check(CHECK, argv)
