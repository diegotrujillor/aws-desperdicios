#!/usr/bin/env python3
"""Generate config/precios.toml from the public AWS Price List Bulk API.

Uses exactly the same PriceSpec filters the scripts send to the Pricing API, so a
successful run also validates those filters against real AWS data.

Usage (maintainers only; downloads ~1.3 GB the first time):
    pip install -r requirements-dev.txt
    python tools/generar_precios.py --cache /tmp/aws-price-list
"""
import argparse
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

import ijson

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aws_desperdicios.pricing import (  # noqa: E402
    DEFAULT_PRICE_TABLE,
    EBS_IOPS_VARIANTS,
    PRICE_SPECS,
    PriceSpec,
    rds_variant,
    select_price,
    spec_for,
)

OFFER_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{service}/current/{region}/index.json"
REGIONS = ("us-east-1", "us-east-2", "sa-east-1")

VOLUME_TYPES = ("gp2", "gp3", "io1", "io2", "st1", "sc1", "standard")
SMALL_SIZES = ("nano", "micro", "small", "medium", "large", "xlarge", "2xlarge")
LARGE_SIZES = ("large", "xlarge", "2xlarge")
EC2_TYPES = tuple(f"{family}.{size}" for family in ("t3", "t3a", "t4g") for size in SMALL_SIZES) + tuple(
    f"{family}.{size}"
    for family in ("m5", "m6i", "m6g", "m7i", "m7g", "c5", "c6i", "c6g", "c7g", "r5", "r6i", "r6g", "r7g")
    for size in LARGE_SIZES
)
RDS_CLASSES = tuple(
    f"db.{family}.{size}" for family in ("t3", "t4g") for size in ("micro", "small", "medium", "large")
) + tuple(f"db.{family}.{size}" for family in ("m5", "m6g", "m6i", "m7g", "r6g") for size in ("large", "xlarge"))
AURORA_CLASSES = (
    "db.t3.medium", "db.t3.large", "db.t4g.medium", "db.t4g.large",
    "db.r6g.large", "db.r6g.xlarge", "db.r7g.large", "db.r7g.xlarge",
)
RDS_VARIANTS = tuple(
    rds_variant(engine, deployment, instance_class, "EBS Only")
    for engine in ("MySQL", "PostgreSQL", "MariaDB")
    for deployment in ("Single-AZ", "Multi-AZ")
    for instance_class in RDS_CLASSES
) + tuple(
    rds_variant(engine, "Single-AZ", instance_class, storage)
    for engine in ("Aurora MySQL", "Aurora PostgreSQL")
    for instance_class in AURORA_CLASSES
    for storage in ("EBS Only", "Aurora IO Optimization Mode")
)

# (key, variant or None). Variants that do not exist in a region are skipped with a warning.
WANTED = (
    [("ebs_gb_mes", v) for v in VOLUME_TYPES]
    + [("ebs_iops_mes", v) for v in EBS_IOPS_VARIANTS]
    + [("ebs_gp3_mibps_mes", None), ("ebs_snapshot_gb_mes", None), ("nat_gb_procesado", None)]
    + [("logs_gb_mes", None)]
    + [("ec2_linux_hora", v) for v in EC2_TYPES]
    + [("rds_hora", v) for v in RDS_VARIANTS]
)


def offer_path(cache: Path, service: str, region: str) -> Path:
    path = cache / f"{service}-{region}.json"
    if not path.exists():
        print(f"Descargando {service} {region}...", file=sys.stderr)
        cache.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(OFFER_URL.format(service=service, region=region), path)
    return path


def read_offer(path: Path, specs: list[PriceSpec], region: str) -> tuple[str, dict, dict]:
    """Return (publicationDate, sku -> attributes, sku -> [(unit, usd)]) for products any spec matches."""
    families = {dict(spec.filters)["productFamily"] for spec in specs}
    with open(path, "rb") as handle:
        published = next(v for k, v in ijson.kvitems(handle, "") if k == "publicationDate")
    attributes = {}
    with open(path, "rb") as handle:
        for sku, product in ijson.kvitems(handle, "products"):
            if product.get("productFamily") not in families:
                continue
            attrs = {**product.get("attributes", {}), "productFamily": product["productFamily"]}
            if any(spec.matches_product(attrs, region) for spec in specs):
                attributes[sku] = attrs
    prices = defaultdict(list)
    with open(path, "rb") as handle:
        for sku, terms in ijson.kvitems(handle, "terms.OnDemand"):
            if sku in attributes:
                for term in terms.values():
                    for dim in term["priceDimensions"].values():
                        prices[sku].append((dim["unit"], float(dim["pricePerUnit"].get("USD", 0))))
    return published, attributes, prices


def resolve(spec: PriceSpec, region: str, attributes: dict, prices: dict) -> tuple[float, str] | None:
    """Unique price for the spec, plus the usagetype it came from, for traceability."""
    candidates = [
        (attrs, unit, usd)
        for sku, attrs in attributes.items()
        if spec.matches_product(attrs, region)
        for unit, usd in prices.get(sku, [])
    ]
    if not candidates:
        return None
    usd = select_price(candidates, spec)
    if usd is None:
        raise SystemExit(f"Ambiguous or invalid price for {spec} in {region}: {candidates}")
    usagetypes = sorted(
        {a.get("usagetype", "") for a, unit, value in candidates if value > 0 and spec.accepts(a, unit)}
    )
    return usd, ",".join(usagetypes)


def build_region(cache: Path, region: str) -> tuple[dict, dict]:
    by_service = defaultdict(list)
    for key, variant in WANTED:
        by_service[spec_for(key, variant).service_code].append((key, variant))
    sources, entries = {}, {}
    for service, wanted in by_service.items():
        specs = [spec_for(k, v) for k, v in wanted]
        published, attributes, prices = read_offer(offer_path(cache, service, region), specs, region)
        source = f"{service}:{region}"
        sources[source] = {"url": OFFER_URL.format(service=service, region=region), "publicacion": published}
        for key, variant in wanted:
            result = resolve(spec_for(key, variant), region, attributes, prices)
            if result is None:
                print(f"Sin producto: {key} {variant or ''} en {region}", file=sys.stderr)
                continue
            usd, usagetype = result
            entries[(key, variant)] = {"usd": round(usd, 10), "fuente": source, "usagetype": usagetype}
    return sources, entries


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def entry_inline(entry: dict) -> str:
    return (
        f"{{ usd = {entry['usd']!r}, fuente = {toml_string(entry['fuente'])}, "
        f"usagetype = {toml_string(entry['usagetype'])} }}"
    )


def region_section(region: str, entries: dict) -> list[str]:
    lines = [f"[precios.{toml_string(region)}]"]
    lines += [f"{key} = {entry_inline(entry)}" for (key, variant), entry in entries.items() if variant is None]
    lines.append("")
    for key in PRICE_SPECS:
        variants = [(variant, entry) for (k, variant), entry in entries.items() if k == key and variant]
        if variants:
            lines.append(f"[precios.{toml_string(region)}.{key}]")
            lines += [f"{toml_string(variant)} = {entry_inline(entry)}" for variant, entry in variants]
            lines.append("")
    return lines


def render(all_sources: dict, all_entries: dict, consulted: str) -> str:
    lines = [
        "# GENERATED by tools/generar_precios.py from the public AWS Price List Bulk API. Do not edit by hand.",
        "# Fallback only: the scripts prefer the live AWS Pricing API (pricing:GetProducts).",
        "# To verify a price, open the source URL and search for its usagetype.",
        "",
    ]
    for name, source in sorted(all_sources.items()):
        lines += [
            f"[fuentes.{toml_string(name)}]",
            f"url = {toml_string(source['url'])}",
            f"publicacion = {toml_string(source['publicacion'])}",
            f"consultado = {toml_string(consulted)}",
            "",
        ]
    for region, entries in all_entries.items():
        lines += region_section(region, entries)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", type=Path, required=True, help="Folder for downloaded offer files.")
    parser.add_argument("--salida", type=Path, default=DEFAULT_PRICE_TABLE, help="Output TOML file.")
    args = parser.parse_args()

    all_sources, all_entries = {}, {}
    for region in REGIONS:
        sources, entries = build_region(args.cache, region)
        all_sources.update(sources)
        all_entries[region] = entries
    args.salida.write_text(render(all_sources, all_entries, date.today().isoformat()), encoding="utf-8")
    print(f"Escrito {args.salida}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
