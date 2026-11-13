"""Monthly cost of an EBS volume from public on-demand prices.

gp3 includes 3,000 IOPS and 125 MiB/s; io1 bills every provisioned IOPS; io2 bills
IOPS in tiers (up to 32,000; 32,001-64,000; above 64,000). Other types bill storage only.
"""
from aws_desperdicios.pricing import PriceCatalog

GP3_BASELINE_IOPS = 3_000
GP3_BASELINE_THROUGHPUT_MIBPS = 125
IO2_TIERS = ((32_000, "io2"), (64_000, "io2.tier2"), (None, "io2.tier3"))


def volume_monthly_cost(
    volume_type: str, size_gib: int, iops: int, throughput: int, region: str, prices: PriceCatalog
) -> float | None:
    """USD per month, or None if any needed price is unknown."""
    storage = prices.get("ebs_gb_mes", region, volume_type)
    performance = _performance_cost(volume_type, iops, throughput, region, prices)
    if storage is None or performance is None:
        return None
    return size_gib * storage.usd + performance


def _performance_cost(volume_type: str, iops: int, throughput: int, region: str, prices: PriceCatalog):
    if volume_type == "gp3":
        return _gp3_extras(iops, throughput, region, prices)
    if volume_type == "io1":
        return _priced(iops, prices, "ebs_iops_mes", region, "io1")
    if volume_type == "io2":
        return _io2_iops(iops, region, prices)
    return 0.0


def _priced(quantity: float, prices: PriceCatalog, key: str, region: str, variant: str | None = None):
    """quantity * unit price; 0 when quantity is 0 (no lookup); None when the price is unknown."""
    if not quantity:
        return 0.0
    price = prices.get(key, region, variant)
    return None if price is None else quantity * price.usd


def _gp3_extras(iops: int, throughput: int, region: str, prices: PriceCatalog) -> float | None:
    iops_cost = _priced(max(0, iops - GP3_BASELINE_IOPS), prices, "ebs_iops_mes", region, "gp3")
    throughput_cost = _priced(
        max(0, throughput - GP3_BASELINE_THROUGHPUT_MIBPS), prices, "ebs_gp3_mibps_mes", region
    )
    if iops_cost is None or throughput_cost is None:
        return None
    return iops_cost + throughput_cost


def _io2_iops(iops: int, region: str, prices: PriceCatalog) -> float | None:
    total, lower = 0.0, 0
    for upper, variant in IO2_TIERS:
        in_tier = (iops if upper is None else min(iops, upper)) - lower
        cost = _priced(max(0, in_tier), prices, "ebs_iops_mes", region, variant)
        if cost is None:
            return None
        total += cost
        if upper is None or iops <= upper:
            return total
        lower = upper
    return total
