"""Waste #5: NAT Gateway traffic to S3/DynamoDB that could use free gateway endpoints.

For each available NAT Gateway, finds the route tables that send traffic through it and
checks whether those route tables have S3 and DynamoDB gateway endpoints. Gateway
endpoints have no hourly or per-GB charge, while the NAT Gateway bills every GB it
processes. CloudWatch does not split NAT traffic by destination, so the savings reported
are a maximum: the processing cost of all NAT traffic.
"""
import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import boto3

from aws_desperdicios.cli import CheckDefinition, int_in_range, run_check
from aws_desperdicios.commands import aws_cli
from aws_desperdicios.pricing import PriceCatalog
from aws_desperdicios.report import Finding

IAM_ACTIONS = (
    "ec2:DescribeNatGateways",
    "ec2:DescribeRouteTables",
    "ec2:DescribeVpcEndpoints",
    "cloudwatch:GetMetricStatistics",
)

GATEWAY_SERVICES = {"s3": "S3", "dynamodb": "DynamoDB"}
# Bytes entering the NAT from the VPC and from the internet: both are billed as processed data.
PROCESSED_BYTES_METRICS = ("BytesInFromSource", "BytesInFromDestination")
BYTES_PER_GIB = 1024**3
SECONDS_PER_DAY = 86_400
DAYS_PER_MONTH = 730 / 24  # AWS 730-hour month
DEFAULT_METRIC_DAYS = 30
MAX_METRIC_DAYS = 455  # CloudWatch keeps 1-hour (and coarser) datapoints for 455 days


@dataclass(frozen=True)
class EndpointGap:
    service: str
    endpoint_id: str | None  # existing endpoint to extend, or None to create one
    route_tables: tuple[str, ...]


def scan(
    session: boto3.Session, region: str, prices: PriceCatalog, args: argparse.Namespace
) -> list[Finding]:
    ec2 = session.client("ec2", region_name=region)
    nats = _available_nat_gateways(ec2)
    if not nats:
        return []
    tables_by_nat = _route_tables_by_nat(ec2, [n["NatGatewayId"] for n in nats])
    endpoints = _gateway_endpoints(ec2, sorted({n["VpcId"] for n in nats}))
    cloudwatch = session.client("cloudwatch", region_name=region)
    findings = []
    for nat in nats:
        gaps = endpoint_gaps(region, nat["VpcId"], tables_by_nat.get(nat["NatGatewayId"], ()), endpoints)
        if gaps:
            monthly_gib = _monthly_processed_gib(cloudwatch, nat["NatGatewayId"], args.dias)
            findings.append(_finding(nat, region, gaps, monthly_gib, prices, args.profile))
    return findings


def _available_nat_gateways(ec2) -> list[dict]:
    pages = ec2.get_paginator("describe_nat_gateways").paginate(
        Filters=[{"Name": "state", "Values": ["available"]}]
    )
    return [nat for page in pages for nat in page["NatGateways"]]


def _route_tables_by_nat(ec2, nat_ids: list[str]) -> dict[str, tuple[str, ...]]:
    pages = ec2.get_paginator("describe_route_tables").paginate(
        Filters=[{"Name": "route.nat-gateway-id", "Values": nat_ids}]
    )
    tables: dict[str, list[str]] = {}
    for table in (t for page in pages for t in page["RouteTables"]):
        for nat_id in {r.get("NatGatewayId") for r in table["Routes"]} & set(nat_ids):
            tables.setdefault(nat_id, []).append(table["RouteTableId"])
    return {nat_id: tuple(sorted(ids)) for nat_id, ids in tables.items()}


def _gateway_endpoints(ec2, vpc_ids: list[str]) -> list[dict]:
    pages = ec2.get_paginator("describe_vpc_endpoints").paginate(
        Filters=[{"Name": "vpc-id", "Values": vpc_ids}, {"Name": "vpc-endpoint-type", "Values": ["Gateway"]}]
    )
    return [e for page in pages for e in page["VpcEndpoints"] if e.get("State", "").lower() in ("available", "pending")]


def endpoint_gaps(region: str, vpc_id: str, route_tables: tuple[str, ...], endpoints: list[dict]) -> list[EndpointGap]:
    """Services whose gateway endpoint is missing from some route table that uses the NAT."""
    gaps = []
    for service in GATEWAY_SERVICES:
        matching = [
            e for e in endpoints if e["VpcId"] == vpc_id and e["ServiceName"] == f"com.amazonaws.{region}.{service}"
        ]
        covered = {table for e in matching for table in e.get("RouteTableIds", [])}
        missing = tuple(t for t in route_tables if t not in covered)
        if missing:
            gaps.append(EndpointGap(service, matching[0]["VpcEndpointId"] if matching else None, missing))
    return gaps


def _monthly_processed_gib(cloudwatch, nat_id: str, days: int) -> float:
    end = datetime.now(UTC)
    total_bytes = 0.0
    for metric in PROCESSED_BYTES_METRICS:
        response = cloudwatch.get_metric_statistics(
            Namespace="AWS/NATGateway",
            MetricName=metric,
            Dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
            StartTime=end - timedelta(days=days),
            EndTime=end,
            Period=SECONDS_PER_DAY,
            Statistics=["Sum"],
        )
        total_bytes += sum(point["Sum"] for point in response["Datapoints"])
    return total_bytes / BYTES_PER_GIB / days * DAYS_PER_MONTH


def _finding(
    nat: dict, region: str, gaps: list[EndpointGap], monthly_gib: float, prices: PriceCatalog, profile: str | None
) -> Finding:
    price = prices.get("nat_gb_procesado", region)
    missing = ", ".join(GATEWAY_SERVICES[g.service] for g in gaps)
    detail = f"NAT en {nat['VpcId']}{_name(nat)}, {monthly_gib:.1f} GiB procesados al mes; sin endpoint gateway para: {missing}"
    savings = None if price is None else round(monthly_gib * price.usd, 2)
    commands = tuple(_command(gap, region, nat["VpcId"], profile) for gap in gaps)
    return Finding(region, nat["NatGatewayId"], detail, savings, "máximo", commands)


def _command(gap: EndpointGap, region: str, vpc_id: str, profile: str | None) -> str:
    if gap.endpoint_id:
        return aws_cli(
            "ec2", "modify-vpc-endpoint", region, profile,
            "--vpc-endpoint-id", gap.endpoint_id, "--add-route-table-ids", *gap.route_tables,
        )
    return aws_cli(
        "ec2", "create-vpc-endpoint", region, profile,
        "--vpc-id", vpc_id, "--vpc-endpoint-type", "Gateway",
        "--service-name", f"com.amazonaws.{region}.{gap.service}", "--route-table-ids", *gap.route_tables,
    )


def _name(resource: dict) -> str:
    name = next((t["Value"] for t in resource.get("Tags", []) if t["Key"] == "Name"), None)
    return f" ({name})" if name else ""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dias",
        type=int_in_range(1, MAX_METRIC_DAYS),
        default=DEFAULT_METRIC_DAYS,
        help=f"Días de métricas del NAT a promediar (1 a {MAX_METRIC_DAYS}; por defecto, {DEFAULT_METRIC_DAYS}).",
    )


def notes(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "El ahorro es un máximo: CloudWatch no separa el tráfico del NAT por destino, así que se supone que todo "
        "va a S3 o DynamoDB. Para saber cuánto va realmente, analiza los VPC Flow Logs.",
        f"Tráfico = BytesInFromSource + BytesInFromDestination de los últimos {args.dias} días, llevado a un mes de 730 horas.",
        "Los endpoints gateway de S3 y DynamoDB no tienen cargo por hora ni por GB. El NAT se sigue cobrando por hora.",
        "Solo el tráfico hacia S3 o DynamoDB de la misma región pasa por el endpoint. Si alguna política de bucket "
        "filtra por IP pública (aws:SourceIp), revísala antes: con el endpoint, el tráfico llega por la red privada.",
        "El script hace 2 consultas GetMetricStatistics por NAT. CloudWatch cobra las solicitudes de API "
        "(USD 0.01 por cada 1.000 en us-east-1, según el AWS Price List).",
    )


CHECK = CheckDefinition(
    title="Desperdicio 5: NAT Gateway sin endpoints gateway para S3 y DynamoDB",
    description=(
        "Lista NAT Gateways cuyas tablas de rutas no tienen endpoints gateway de S3 o DynamoDB "
        "y el costo máximo del tráfico que procesan. Solo lectura."
    ),
    scan=scan,
    notes=notes,
    add_arguments=add_arguments,
)


def main(argv: list[str] | None = None) -> int:
    return run_check(CHECK, argv)
