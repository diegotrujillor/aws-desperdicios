"""Prices from the AWS Pricing API, with a sourced local table as fallback.

No price is ever invented: if neither source has a value, `get` returns None and
the finding is shown without a savings figure.
"""
import json
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from aws_desperdicios.errors import AwsSetupError, is_access_denied

DEFAULT_PRICE_TABLE = Path(__file__).resolve().parent.parent / "config" / "precios.toml"
# The Pricing API is only served from a few regions; us-east-1 covers all commercial regions.
PRICING_API_REGION = "us-east-1"
MAX_API_RESULTS = 10
MIB_PER_GIB = 1024


@dataclass(frozen=True)
class Price:
    usd: float
    source: str


@dataclass(frozen=True)
class PriceSpec:
    """How to find one on-demand price in the Pricing API and convert it to the table unit."""

    service_code: str
    filters: tuple[tuple[str, str], ...]
    api_unit: str
    divisor: float = 1.0


PRICE_SPECS: dict[str, PriceSpec] = {
    "ebs_gp2_gb_mes": PriceSpec(
        "AmazonEC2", (("productFamily", "Storage"), ("volumeApiName", "gp2")), "GB-Mo"
    ),
    "ebs_gp3_gb_mes": PriceSpec(
        "AmazonEC2", (("productFamily", "Storage"), ("volumeApiName", "gp3")), "GB-Mo"
    ),
    "ebs_gp3_iops_mes": PriceSpec(
        "AmazonEC2",
        (("productFamily", "System Operation"), ("volumeApiName", "gp3"), ("group", "EBS IOPS")),
        "IOPS-Mo",
    ),
    # The API prices gp3 throughput per GiBps-month; the table stores USD per MiBps-month.
    "ebs_gp3_mibps_mes": PriceSpec(
        "AmazonEC2",
        (("productFamily", "Provisioned Throughput"), ("volumeApiName", "gp3")),
        "GiBps-mo",
        divisor=MIB_PER_GIB,
    ),
}


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


class PriceCatalog:
    """Resolves prices per (key, region). Caches results and collects user-facing notes."""

    def __init__(self, pricing_client, table: dict, today: date | None = None):
        self._client = pricing_client
        self._table = table
        self._today = today or date.today()
        self._cache: dict[tuple[str, str], Price | None] = {}
        self._notes: dict[str, None] = {}  # insertion-ordered set
        self._sources: dict[str, None] = {}

    @property
    def uses_api(self) -> bool:
        return self._client is not None

    def notes(self) -> tuple[str, ...]:
        return tuple(self._notes)

    def sources(self) -> tuple[str, ...]:
        return tuple(self._sources)

    def get(self, key: str, region: str) -> Price | None:
        spec = PRICE_SPECS[key]
        cache_key = (key, region)
        if cache_key not in self._cache:
            price = self._from_api(spec, region) or self._from_table(key, region)
            if price:
                self._sources[price.source] = None
            self._cache[cache_key] = price
        return self._cache[cache_key]

    def _note(self, message: str) -> None:
        self._notes[message] = None

    def _from_api(self, spec: PriceSpec, region: str) -> Price | None:
        if self._client is None:
            return None
        filters = [*spec.filters, ("locationType", "AWS Region"), ("regionCode", region)]
        try:
            response = self._client.get_products(
                ServiceCode=spec.service_code,
                Filters=[{"Type": "TERM_MATCH", "Field": f, "Value": v} for f, v in filters],
                MaxResults=MAX_API_RESULTS,
            )
        except (ClientError, BotoCoreError) as error:
            self._disable_api(error)
            return None
        candidates = _on_demand_prices(response.get("PriceList", []), spec)
        if len(candidates) != 1:
            return None
        return Price(usd=candidates.pop(), source=f"AWS Pricing API (consultada {self._today.isoformat()})")

    def _disable_api(self, error: Exception) -> None:
        self._client = None
        if isinstance(error, ClientError) and is_access_denied(error):
            reason = "falta el permiso IAM 'pricing:GetProducts'"
        else:
            reason = f"error al consultarla ({error})"
        self._note(f"No se usó la AWS Pricing API: {reason}. Se usa la tabla local config/precios.toml.")

    def _from_table(self, key: str, region: str) -> Price | None:
        entry = self._table["precios"].get(region, {}).get(key)
        if entry is None:
            self._note(
                f"Sin precio para la región {region} (ni en la Pricing API ni en config/precios.toml): "
                "sus hallazgos se muestran sin cifra de ahorro."
            )
            return None
        published = self._table["fuentes"][entry["fuente"]]["publicacion"][:10]
        return Price(
            usd=float(entry["usd"]),
            source=f"Tabla local config/precios.toml (AWS Price List publicado {published})",
        )


def _on_demand_prices(price_list: list[str], spec: PriceSpec) -> set[float]:
    """Distinct positive USD prices whose unit matches the spec."""
    found = set()
    for raw in price_list:
        terms = json.loads(raw).get("terms", {}).get("OnDemand", {})
        for term in terms.values():
            for dimension in term.get("priceDimensions", {}).values():
                if dimension.get("unit", "").lower() != spec.api_unit.lower():
                    continue
                usd = float(dimension.get("pricePerUnit", {}).get("USD", 0))
                if usd > 0:
                    found.add(usd / spec.divisor)
    return found
