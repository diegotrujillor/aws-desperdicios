"""Shared command-line driver: arguments, region loop, error handling and output."""
import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from aws_desperdicios.errors import AwsSetupError, explain_error, iam_action_name
from aws_desperdicios.pricing import (
    DEFAULT_PRICE_TABLE,
    PRICING_API_REGION,
    PriceCatalog,
    load_price_table,
)
from aws_desperdicios.report import Finding, RegionError, Report, render_json, render_table
from aws_desperdicios.session import create_session, resolve_regions

EXIT_OK = 0
EXIT_PARTIAL = 1  # some regions failed (usually a missing permission)
EXIT_FATAL = 2  # nothing could be scanned

# Permissions used by the shared driver itself (region discovery and prices).
CORE_IAM_ACTIONS = ("ec2:DescribeRegions", "pricing:GetProducts")

ScanFn = Callable[[boto3.Session, str, PriceCatalog, argparse.Namespace], list[Finding]]


@dataclass(frozen=True)
class CheckDefinition:
    title: str
    description: str
    scan: ScanFn
    notes: Callable[[argparse.Namespace], tuple[str, ...]] = lambda args: ()
    add_arguments: Callable[[argparse.ArgumentParser], None] = lambda parser: None


def build_parser(check: CheckDefinition) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=check.description)
    parser.add_argument("--profile", help="Perfil de AWS CLI a usar (por defecto, la cadena estándar).")
    parser.add_argument("--region", help="Revisar solo esta región (por defecto, todas las habilitadas).")
    parser.add_argument("--json", action="store_true", help="Imprimir el resultado en JSON.")
    parser.add_argument(
        "--precios-locales",
        action="store_true",
        help="No consultar la AWS Pricing API; usar solo la tabla local de precios.",
    )
    parser.add_argument(
        "--precios",
        default=str(DEFAULT_PRICE_TABLE),
        help="Ruta a la tabla local de precios (por defecto, config/precios.toml).",
    )
    check.add_arguments(parser)
    return parser


def run_check(check: CheckDefinition, argv: list[str] | None = None) -> int:
    args = build_parser(check).parse_args(argv)
    try:
        report = build_report(check, args)
    except AwsSetupError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_FATAL
    except NoCredentialsError as error:
        print(f"Error: {explain_error(error)}", file=sys.stderr)
        return EXIT_FATAL
    sys.stdout.write(render_json(report) + "\n" if args.json else render_table(report))
    return EXIT_PARTIAL if report.errors else EXIT_OK


def build_report(check: CheckDefinition, args: argparse.Namespace) -> Report:
    session = create_session(args.profile)
    prices = _build_catalog(session, args)
    last_call = _track_last_action(session)
    regions = _regions_or_fail(session, args.region, last_call)

    findings: list[Finding] = []
    errors: list[RegionError] = []
    for region in regions:
        try:
            findings.extend(check.scan(session, region, prices, args))
        except (ClientError, EndpointConnectionError) as error:
            errors.append(RegionError(region, explain_error(error, last_call.get("action"))))

    return Report(
        title=check.title,
        findings=tuple(findings),
        errors=tuple(errors),
        notes=check.notes(args) + prices.notes(),
        price_sources=prices.sources(),
    )


def _build_catalog(session: boto3.Session, args: argparse.Namespace) -> PriceCatalog:
    table = load_price_table(Path(args.precios))
    client = None if args.precios_locales else session.client("pricing", region_name=PRICING_API_REGION)
    return PriceCatalog(client, table)


def _track_last_action(session: boto3.Session) -> dict:
    """Remember the IAM action of the latest API call, to name it if AWS denies access."""
    last_call: dict[str, str] = {}

    def remember(model, **_kwargs):
        last_call["action"] = iam_action_name(model)

    session.events.register("before-call", remember)
    return last_call


def _regions_or_fail(session: boto3.Session, region: str | None, last_call: dict) -> list[str]:
    try:
        return resolve_regions(session, region)
    except (ClientError, EndpointConnectionError) as error:
        raise AwsSetupError(
            f"{explain_error(error, last_call.get('action'))} También puedes usar --region para revisar una sola región."
        ) from error
