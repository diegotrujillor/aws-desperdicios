"""Prices from the AWS Pricing API, with a sourced local table as fallback.

No price is ever invented: if neither source has a value, `get` returns None and
the finding is shown without a savings figure.

The same PriceSpec filters are used to query the Pricing API at runtime and by
tools/generar_precios.py to build config/precios.toml from the public price list.
"""
import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from aws_desperdicios.errors import AwsSetupError, is_access_denied

DEFAULT_PRICE_TABLE = Path(__file__).resolve().parent.parent / "config" / "precios.toml"
# The Pricing API is only served from a few regions; us-east-1 covers all commercial regions.
PRICING_API_REGION = "us-east-1"
MAX_API_RESULTS = 100
MIB_PER_GIB = 1024
GB_MONTH_UNITS = ("GB-Mo", "GB-month")


@dataclass(frozen=True)
class Price:
    usd: float
    source: str


@dataclass(frozen=True)
class PriceSpec:
    """How to find one on-demand price and convert it to the unit the scripts use."""

    service_code: str
    filters: tuple[tuple[str, str], ...]
    units: tuple[str, ...]
    divisor: float = 1.0
    # Applied to the returned products, for attributes the API cannot filter on
    # (usagetype carries a region prefix such as "USE2-").
    usagetype_suffix: str | None = None

    def region_filters(self, region: str) -> list[tuple[str, str]]:
        return [*self.filters, ("locationType", "AWS Region"), ("regionCode", region)]

    def matches_product(self, attributes: dict, region: str) -> bool:
        return all(attributes.get(field) == value for field, value in self.region_filters(region))

    def accepts(self, attributes: dict, unit: str) -> bool:
        unit_ok = unit.lower() in {u.lower() for u in self.units}
        suffix_ok = self.usagetype_suffix is None or attributes.get("usagetype", "").endswith(
            self.usagetype_suffix
        )
        return unit_ok and suffix_ok


def _fixed(spec: PriceSpec) -> Callable[[str | None], PriceSpec]:
    def factory(variant: str | None) -> PriceSpec:
        if variant is not None:
            raise ValueError(f"Price key does not take a variant: {variant}")
        return spec

    return factory


def _variant(build: Callable[[str], PriceSpec]) -> Callable[[str | None], PriceSpec]:
    def factory(variant: str | None) -> PriceSpec:
        if variant is None:
            raise ValueError("Price key requires a variant")
        return build(variant)

    return factory


# variant -> (volumeApiName, Pricing API group)
EBS_IOPS_VARIANTS = {
    "gp3": ("gp3", "EBS IOPS"),
    "io1": ("io1", "EBS IOPS"),
    "io2": ("io2", "EBS IOPS"),
    "io2.tier2": ("io2", "EBS IOPS Tier 2"),
    "io2.tier3": ("io2", "EBS IOPS Tier 3"),
}


def _ebs_storage(volume_type: str) -> PriceSpec:
    return PriceSpec("AmazonEC2", (("productFamily", "Storage"), ("volumeApiName", volume_type)), GB_MONTH_UNITS)


def _ebs_iops(variant: str) -> PriceSpec:
    volume_type, group = EBS_IOPS_VARIANTS[variant]
    filters = (("productFamily", "System Operation"), ("volumeApiName", volume_type), ("group", group))
    return PriceSpec("AmazonEC2", filters, ("IOPS-Mo",))


def _ec2_linux(instance_type: str) -> PriceSpec:
    filters = (
        ("productFamily", "Compute Instance"),
        ("instanceType", instance_type),
        ("operatingSystem", "Linux"),
        ("tenancy", "Shared"),
        ("preInstalledSw", "NA"),
        ("capacitystatus", "Used"),
        ("licenseModel", "No License required"),
    )
    return PriceSpec("AmazonEC2", filters, ("Hrs",))


def rds_variant(engine: str, deployment: str, instance_class: str, storage: str) -> str:
    """Variant key for rds_hora, e.g. 'PostgreSQL|Single-AZ|db.t3.micro|EBS Only'."""
    return "|".join((engine, deployment, instance_class, storage))


def _rds(variant: str) -> PriceSpec:
    engine, deployment, instance_class, storage = variant.split("|")
    filters = (
        ("productFamily", "Database Instance"),
        ("instanceType", instance_class),
        ("databaseEngine", engine),
        ("deploymentOption", deployment),
        ("storage", storage),
        ("licenseModel", "No license required"),
    )
    return PriceSpec("AmazonRDS", filters, ("Hrs",))


PRICE_SPECS: dict[str, Callable[[str | None], PriceSpec]] = {
    "ebs_gb_mes": _variant(_ebs_storage),
    "ebs_iops_mes": _variant(_ebs_iops),
    # The API prices gp3 throughput per GiBps-month; scripts use USD per MiBps-month.
    "ebs_gp3_mibps_mes": _fixed(
        PriceSpec(
            "AmazonEC2",
            (("productFamily", "Provisioned Throughput"), ("volumeApiName", "gp3")),
            ("GiBps-mo",),
            divisor=MIB_PER_GIB,
        )
    ),
    "ebs_snapshot_gb_mes": _fixed(
        PriceSpec(
            "AmazonEC2",
            (("productFamily", "Storage Snapshot"), ("storageMedia", "Amazon S3")),
            GB_MONTH_UNITS,
            usagetype_suffix="EBS:SnapshotUsage",
        )
    ),
    "nat_gb_procesado": _fixed(
        PriceSpec(
            "AmazonEC2",
            (("productFamily", "NAT Gateway"), ("operation", "NatGateway")),
            ("GB",),
            usagetype_suffix="NatGateway-Bytes",
        )
    ),
    "logs_gb_mes": _fixed(
        PriceSpec(
            "AmazonCloudWatch",
            (
                ("productFamily", "Storage Snapshot"),
                ("group", "Amazon CloudWatch Standard Storage pricing current"),
            ),
            GB_MONTH_UNITS,
            usagetype_suffix="TimedStorage-ByteHrs",
        )
    ),
    "ec2_linux_hora": _variant(_ec2_linux),
    "rds_hora": _variant(_rds),
}


def spec_for(key: str, variant: str | None = None) -> PriceSpec:
    return PRICE_SPECS[key](variant)


def load_price_table(path: Path) -> dict:
    """Load and minimally validate the local price table."""
    try:
        with open(path, "rb") as handle:
            table = tomllib.load(handle)
    except FileNotFoundError as error:
        raise AwsSetupError(f"No se encontró la tabla de precios: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise AwsSetupError(f"La tabla de precios {path} no es TOML válido: {error}") from error
    if not {"fuentes", "precios"} <= set(table):
        raise AwsSetupError(f"La tabla de precios {path} debe tener las secciones [fuentes] y [precios].")
    return table


def select_price(products: list[tuple[dict, str, float]], spec: PriceSpec) -> float | None:
    """Single positive price among (attributes, unit, usd) candidates, or None if absent/ambiguous."""
    found = {usd / spec.divisor for attributes, unit, usd in products if usd > 0 and spec.accepts(attributes, unit)}
    return found.pop() if len(found) == 1 else None


class PriceCatalog:
    """Resolves prices per (key, region, variant). Caches results and collects user-facing notes."""

    def __init__(self, pricing_client, table: dict, today: date | None = None):
        self._client = pricing_client
        self._table = table
        self._today = today or date.today()
        self._cache: dict[tuple[str, str, str | None], Price | None] = {}
        self._notes: dict[str, None] = {}  # insertion-ordered set
        self._sources: dict[str, None] = {}

    @property
    def uses_api(self) -> bool:
        return self._client is not None

    def notes(self) -> tuple[str, ...]:
        return tuple(self._notes)

    def sources(self) -> tuple[str, ...]:
        return tuple(self._sources)

    def get(self, key: str, region: str, variant: str | None = None) -> Price | None:
        spec = spec_for(key, variant)
        cache_key = (key, region, variant)
        if cache_key not in self._cache:
            price = self._from_api(spec, region) or self._from_table(key, region, variant)
            if price:
                self._sources[price.source] = None
            self._cache[cache_key] = price
        return self._cache[cache_key]

    def _note(self, message: str) -> None:
        self._notes[message] = None

    def _from_api(self, spec: PriceSpec, region: str) -> Price | None:
        if self._client is None:
            return None
        try:
            response = self._client.get_products(
                ServiceCode=spec.service_code,
                Filters=[{"Type": "TERM_MATCH", "Field": f, "Value": v} for f, v in spec.region_filters(region)],
                MaxResults=MAX_API_RESULTS,
            )
        except (ClientError, BotoCoreError) as error:
            self._disable_api(error)
            return None
        usd = select_price(_api_products(response.get("PriceList", [])), spec)
        if usd is None:
            return None
        return Price(usd=usd, source=f"AWS Pricing API (consultada {self._today.isoformat()})")

    def _disable_api(self, error: Exception) -> None:
        self._client = None
        if isinstance(error, ClientError) and is_access_denied(error):
            reason = "falta el permiso IAM 'pricing:GetProducts'"
        else:
            reason = f"error al consultarla ({error})"
        self._note(f"No se usó la AWS Pricing API: {reason}. Se usa la tabla local config/precios.toml.")

    def _from_table(self, key: str, region: str, variant: str | None) -> Price | None:
        entry = self._table["precios"].get(region, {}).get(key)
        if entry is not None and variant is not None:
            entry = entry.get(variant)
        if entry is None:
            what = f"{key} ({variant})" if variant else key
            self._note(
                f"Sin precio de {what} en la región {region} (ni en la Pricing API ni en config/precios.toml): "
                "esos hallazgos se muestran sin cifra de ahorro."
            )
            return None
        published = self._table["fuentes"][entry["fuente"]]["publicacion"][:10]
        return Price(
            usd=float(entry["usd"]),
            source=f"Tabla local config/precios.toml (AWS Price List publicado {published})",
        )


def _api_products(price_list: list[str]) -> list[tuple[dict, str, float]]:
    """Flatten Pricing API PriceList JSON strings into (attributes, unit, usd) tuples."""
    products = []
    for raw in price_list:
        item = json.loads(raw)
        attributes = item.get("product", {}).get("attributes", {})
        for term in item.get("terms", {}).get("OnDemand", {}).values():
            for dimension in term.get("priceDimensions", {}).values():
                usd = float(dimension.get("pricePerUnit", {}).get("USD", 0))
                products.append((attributes, dimension.get("unit", ""), usd))
    return products
