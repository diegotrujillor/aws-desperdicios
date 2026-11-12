"""Waste #1: EBS gp2 volumes that could be gp3 with equal or better performance.

gp2 performance (AWS EBS docs, "General Purpose SSD volumes"):
- IOPS: 3 per GiB, minimum 100, maximum 16,000.
- Throughput: up to 128 MiB/s for volumes <= 170 GiB; up to 250 MiB/s above 170 GiB.
gp3 includes 3,000 IOPS and 125 MiB/s; extra IOPS and throughput are billed separately.
"""
import argparse
import shlex

import boto3

from aws_desperdicios.cli import CheckDefinition, run_check
from aws_desperdicios.pricing import PriceCatalog
from aws_desperdicios.report import Finding

IAM_ACTIONS = ("ec2:DescribeVolumes",)

GP2_IOPS_PER_GIB = 3
GP2_MIN_IOPS = 100
GP2_MAX_IOPS = 16_000
GP2_SMALL_VOLUME_MAX_GIB = 170
GP2_SMALL_THROUGHPUT_MIBPS = 128
GP2_LARGE_THROUGHPUT_MIBPS = 250
GP3_BASELINE_IOPS = 3_000
GP3_BASELINE_THROUGHPUT_MIBPS = 125

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
    keys = ("ebs_gp2_gb_mes", "ebs_gp3_gb_mes", "ebs_gp3_iops_mes", "ebs_gp3_mibps_mes")
    gp2_gb, gp3_gb, gp3_iops, gp3_mibps = (prices.get(key, region) for key in keys)
    if None in (gp2_gb, gp3_gb, gp3_iops, gp3_mibps):
        return None
    iops, throughput = gp3_equivalent(size_gib)
    gp3_cost = (
        size_gib * gp3_gb.usd
        + (iops - GP3_BASELINE_IOPS) * gp3_iops.usd
        + (throughput - GP3_BASELINE_THROUGHPUT_MIBPS) * gp3_mibps.usd
    )
    return round(size_gib * gp2_gb.usd - gp3_cost, 2)


def suggested_command(volume_id: str, region: str, size_gib: int, profile: str | None) -> str:
    iops, throughput = gp3_equivalent(size_gib)
    profile_flag = f"--profile {shlex.quote(profile)} " if profile else ""
    return (
        f"aws ec2 modify-volume {profile_flag}--region {region} --volume-id {volume_id} "
        f"--volume-type gp3 --iops {iops} --throughput {throughput}"
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
        suggested_command=suggested_command(volume["VolumeId"], region, size, args.profile),
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
