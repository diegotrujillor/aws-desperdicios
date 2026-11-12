import pytest

from aws_desperdicios.ebs import volume_monthly_cost
from aws_desperdicios.pricing import PriceCatalog

# us-east-1 prices from config/precios.toml (AWS Price List published 2026-11-10).


@pytest.mark.parametrize(
    ("volume_type", "size", "iops", "throughput", "expected"),
    [
        ("gp2", 100, 300, 128, 10.0),  # 100 * 0.10
        ("gp3", 100, 3000, 125, 8.0),  # baseline IOPS/throughput are included
        ("gp3", 100, 6000, 250, 8.0 + 3000 * 0.005 + 125 * 0.04),
        ("io1", 100, 1000, 0, 100 * 0.125 + 1000 * 0.065),
        ("io2", 100, 40_000, 0, 100 * 0.125 + 32_000 * 0.065 + 8_000 * 0.0455),
        ("io2", 100, 70_000, 0, 100 * 0.125 + 32_000 * 0.065 + 32_000 * 0.0455 + 6_000 * 0.03185),
        ("st1", 500, 0, 0, 500 * 0.045),
        ("sc1", 500, 0, 0, 500 * 0.015),
        ("standard", 10, 0, 0, 10 * 0.05),
    ],
)
def test_monthly_cost_matches_public_prices(local_prices, volume_type, size, iops, throughput, expected):
    cost = volume_monthly_cost(volume_type, size, iops, throughput, "us-east-1", local_prices)
    assert cost == pytest.approx(expected)


def test_cost_is_unknown_when_storage_price_is_missing(local_prices):
    assert volume_monthly_cost("gp2", 100, 300, 128, "ap-southeast-7", local_prices) is None


def test_cost_is_unknown_when_iops_price_is_missing():
    table = {
        "fuentes": {"X": {"publicacion": "2026-01-01T00:00:00Z"}},
        "precios": {"us-east-1": {"ebs_gb_mes": {"io2": {"usd": 0.125, "fuente": "X"}}}},
    }
    assert volume_monthly_cost("io2", 100, 1000, 0, "us-east-1", PriceCatalog(None, table)) is None
