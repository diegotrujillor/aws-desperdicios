"""Waste #1: EBS gp2 volumes that could be gp3 with equal or better performance.

gp2 performance (AWS EBS docs, "General Purpose SSD volumes"):
- IOPS: 3 per GiB, minimum 100, maximum 16,000.
- Throughput: up to 128 MiB/s for volumes <= 170 GiB; up to 250 MiB/s above 170 GiB.
gp3 includes 3,000 IOPS and 125 MiB/s; extra IOPS and throughput are billed separately.
"""
import argparse

import boto3

from aws_desperdicios.cli import CheckDefinition, run_check
from aws_desperdicios.commands import aws_cli
from aws_desperdicios.ebs import GP3_BASELINE_IOPS, GP3_BASELINE_THROUGHPUT_MIBPS, volume_monthly_cost
from aws_desperdicios.pricing import PriceCatalog
from aws_desperdicios.report import Finding

IAM_ACTIONS = ("ec2:DescribeVolumes",)

GP2_IOPS_PER_GIB = 3
GP2_MIN_IOPS = 100
GP2_MAX_IOPS = 16_000
GP2_SMALL_VOLUME_MAX_GIB = 170
GP2_SMALL_THROUGHPUT_MIBPS = 128
GP2_LARGE_THROUGHPUT_MIBPS = 250

STATE_LABELS = {"in-use": "en uso", "available": "sin adjuntar"}


def gp2_performance(size_gib: int) -> tuple[int, int]:
    """Maximum (IOPS, MiB/s) a gp2 volume of this size can deliver."""
    iops = min(max(GP2_IOPS_PER_GIB * size_gib, GP2_MIN_IOPS), GP2_MAX_IOPS)
    if size_gib <= GP2_SMALL_VOLUME_MAX_GIB:
        return iops, GP2_SMALL_THROUGHPUT_MIBPS
    return iops, GP2_LARGE_THROUGHPUT_MIBPS


def gp3_equivalent(size_gib: int) -> tuple[int, int]:
    """gp3 (IOPS, MiB/s) that never falls below the gp2 maximums, including gp2 burst (3,000 IOPS)."""
    iops, throughput = gp2_performance(size_gib)
    return max(iops, GP3_BASELINE_IOPS), max(throughput, GP3_BASELINE_THROUGHPUT_MIBPS)


def monthly_savings(size_gib: int, region: str, prices: PriceCatalog) -> float | None:
    """gp2 cost minus equivalent gp3 cost, in USD/month. None if any price is unknown."""
    iops, throughput = gp3_equivalent(size_gib)
    gp2_cost = volume_monthly_cost("gp2", size_gib, 0, 0, region, prices)
    gp3_cost = volume_monthly_cost("gp3", size_gib, iops, throughput, region, prices)
    if gp2_cost is None or gp3_cost is None:
        return None
    return round(gp2_cost - gp3_cost, 2)


def suggested_command(volume_id: str, region: str, size_gib: int, profile: str | None) -> str:
    iops, throughput = gp3_equivalent(size_gib)
    return aws_cli(
        "ec2", "modify-volume", region, profile,
        "--volume-id", volume_id, "--volume-type", "gp3", "--iops", str(iops), "--throughput", str(throughput),
    )


def scan(
    session: boto3.Session, region: str, prices: PriceCatalog, args: argparse.Namespace
) -> list[Finding]:
    ec2 = session.client("ec2", region_name=region)
    pages = ec2.get_paginator("describe_volumes").paginate(
        Filters=[{"Name": "volume-type", "Values": ["gp2"]}]
    )
    findings = []
    for page in pages:
        for volume in page["Volumes"]:
            finding = _finding(volume, region, prices, args)
            if finding:
                findings.append(finding)
    return findings


def _finding(volume: dict, region: str, prices: PriceCatalog, args: argparse.Namespace) -> Finding | None:
    size = volume["Size"]
    savings = monthly_savings(size, region, prices)
    if savings is not None and savings <= 0:
        return None
    iops, throughput = gp3_equivalent(size)
    state = STATE_LABELS.get(volume["State"], volume["State"])
    return Finding(
        region=region,
        resource_id=volume["VolumeId"],
        detail=f"{size} GiB gp2, {state} -> gp3 {iops} IOPS / {throughput} MiB/s",
        monthly_savings_usd=savings,
        savings_kind="exacto",
        suggested_commands=(suggested_command(volume["VolumeId"], region, size, args.profile),),
    )


def notes(_args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "El gp3 sugerido iguala o supera el máximo de IOPS y throughput que el gp2 puede entregar "
        "(incluida la ráfaga de 3.000 IOPS), así que el rendimiento no baja.",
        "El cambio de gp2 a gp3 se hace en caliente con modify-volume, sin detener la instancia; "
        "un mismo volumen solo se puede modificar una vez cada 6 horas.",
        "Los volúmenes 'sin adjuntar' también aparecen en el script 02: quizá conviene borrarlos en vez de migrarlos.",
    )


CHECK = CheckDefinition(
    title="Desperdicio 1: volúmenes EBS gp2 que podrían ser gp3",
    description="Lista volúmenes gp2 y calcula el ahorro mensual de migrarlos a gp3. Solo lectura.",
    scan=scan,
    notes=notes,
)


def main(argv: list[str] | None = None) -> int:
    return run_check(CHECK, argv)
