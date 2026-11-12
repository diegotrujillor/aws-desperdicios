import json
from datetime import date

import boto3
import pytest
from botocore.stub import Stubber

from aws_desperdicios.errors import AwsSetupError
from aws_desperdicios.pricing import PRICE_SPECS, Price, PriceCatalog, load_price_table, spec_for
from tests.conftest import PRICE_TABLE_PATH

TODAY = date(2026, 11, 12)


def price_item(unit, usd, usagetype="EBS:VolumeUsage.gp2"):
    return json.dumps(
        {
            "product": {"productFamily": "Storage", "attributes": {"usagetype": usagetype}},
            "terms": {
                "OnDemand": {
                    "SKU.TERM": {
                        "priceDimensions": {
                            "SKU.TERM.DIM": {"unit": unit, "pricePerUnit": {"USD": str(usd)}}
                        }
                    }
                }
            },
        }
    )


@pytest.fixture
def pricing_client():
    return boto3.client("pricing", region_name="us-east-1")


@pytest.fixture
def table():
    return load_price_table(PRICE_TABLE_PATH)


def table_entries(table):
    for region, prices in table["precios"].items():
        for key, value in prices.items():
            if "usd" in value:
                yield region, key, None, value
            else:
                for variant, entry in value.items():
                    yield region, key, variant, entry


def test_every_table_entry_has_a_spec_and_a_declared_source(table):
    for region, key, variant, entry in table_entries(table):
        spec_for(key, variant)  # raises if the key/variant is unknown
        assert entry["fuente"] in table["fuentes"], (region, key, variant)
        assert entry["usd"] > 0


def test_every_spec_key_is_in_the_table_for_each_region(table):
    for region, prices in table["precios"].items():
        assert set(PRICE_SPECS) <= set(prices), region


def test_returns_api_price_and_sends_region_filters(pricing_client, table):
    stubber = Stubber(pricing_client)
    expected_filters = [
        {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"},
        {"Type": "TERM_MATCH", "Field": "volumeApiName", "Value": "gp2"},
        {"Type": "TERM_MATCH", "Field": "locationType", "Value": "AWS Region"},
        {"Type": "TERM_MATCH", "Field": "regionCode", "Value": "eu-west-1"},
    ]
    stubber.add_response(
        "get_products",
        {"PriceList": [price_item("GB-Mo", "0.11")]},
        {"ServiceCode": "AmazonEC2", "Filters": expected_filters, "MaxResults": 100},
    )
    with stubber:
        catalog = PriceCatalog(pricing_client, table, today=TODAY)
        price = catalog.get("ebs_gb_mes", "eu-west-1", "gp2")

    assert price == Price(usd=0.11, source="AWS Pricing API (consultada 2026-11-12)")


def test_accepts_alternative_unit_spelling(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_response("get_products", {"PriceList": [price_item("GB-month", "0.125")]})
    with stubber:
        price = PriceCatalog(pricing_client, table, today=TODAY).get("ebs_gb_mes", "eu-west-1", "io2")
    assert price.usd == 0.125


def test_usagetype_suffix_discards_similar_products(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_response(
        "get_products",
        {
            "PriceList": [
                price_item("GB-Mo", "0.05", usagetype="EUW1-EBS:SnapshotUsage"),
                price_item("GB-Mo", "0.0125", usagetype="EUW1-EBS:SnapshotArchiveStorage"),
            ]
        },
    )
    with stubber:
        price = PriceCatalog(pricing_client, table, today=TODAY).get("ebs_snapshot_gb_mes", "eu-west-1")
    assert price.usd == 0.05


def test_caches_api_prices_per_key_region_and_variant(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_response("get_products", {"PriceList": [price_item("GB-Mo", "0.11")]})
    with stubber:
        catalog = PriceCatalog(pricing_client, table, today=TODAY)
        first = catalog.get("ebs_gb_mes", "eu-west-1", "gp2")
        second = catalog.get("ebs_gb_mes", "eu-west-1", "gp2")
    assert first == second
    stubber.assert_no_pending_responses()


def test_converts_throughput_from_gibps_to_mibps(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_response("get_products", {"PriceList": [price_item("GiBps-mo", "40.96")]})
    with stubber:
        price = PriceCatalog(pricing_client, table, today=TODAY).get("ebs_gp3_mibps_mes", "us-east-1")
    assert price.usd == pytest.approx(0.04)


def test_falls_back_to_table_when_api_unit_is_unexpected(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_response("get_products", {"PriceList": [price_item("Hrs", "1.0")]})
    with stubber:
        price = PriceCatalog(pricing_client, table, today=TODAY).get("ebs_gb_mes", "us-east-1", "gp2")
    assert price.usd == 0.10
    assert "config/precios.toml" in price.source


def test_falls_back_to_table_when_api_prices_are_ambiguous(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_response(
        "get_products", {"PriceList": [price_item("GB-Mo", "0.10"), price_item("GB-Mo", "0.12")]}
    )
    with stubber:
        price = PriceCatalog(pricing_client, table, today=TODAY).get("ebs_gb_mes", "us-east-1", "gp2")
    assert price.usd == 0.10


def test_access_denied_disables_api_and_adds_spanish_note(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_client_error("get_products", service_error_code="AccessDeniedException")
    with stubber:
        catalog = PriceCatalog(pricing_client, table, today=TODAY)
        first = catalog.get("ebs_gb_mes", "us-east-1", "gp2")
        second = catalog.get("ebs_gb_mes", "us-east-1", "gp3")

    assert (first.usd, second.usd) == (0.10, 0.08)
    assert any("pricing:GetProducts" in note for note in catalog.notes())
    stubber.assert_no_pending_responses()


def test_non_permission_api_error_also_falls_back_with_note(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_client_error("get_products", service_error_code="ThrottlingException")
    with stubber:
        catalog = PriceCatalog(pricing_client, table, today=TODAY)
        price = catalog.get("ebs_gb_mes", "us-east-1", "gp2")
    assert price.usd == 0.10
    assert any("error al consultarla" in note for note in catalog.notes())


def test_returns_none_and_notes_region_without_any_price(local_prices):
    assert local_prices.get("ebs_gb_mes", "ap-southeast-7", "gp2") is None
    assert any("ap-southeast-7" in note for note in local_prices.notes())


def test_returns_none_for_variant_missing_in_table(local_prices):
    assert local_prices.get("ec2_linux_hora", "us-east-1", "x99.huge") is None
    assert any("x99.huge" in note for note in local_prices.notes())


def test_unknown_key_is_a_programming_error(local_prices):
    with pytest.raises(KeyError):
        local_prices.get("does_not_exist", "us-east-1")


def test_variant_keys_require_a_variant():
    with pytest.raises(ValueError):
        spec_for("ebs_gb_mes")


def test_table_source_mentions_publication_date(local_prices):
    price = local_prices.get("ebs_gb_mes", "sa-east-1", "gp3")
    assert price.usd == 0.152
    assert "2026-11-10" in price.source


def test_rds_variant_builds_engine_deployment_and_storage_filters():
    spec = spec_for("rds_hora", "PostgreSQL|Multi-AZ|db.t3.micro|EBS Only")
    assert ("databaseEngine", "PostgreSQL") in spec.filters
    assert ("deploymentOption", "Multi-AZ") in spec.filters
    assert ("instanceType", "db.t3.micro") in spec.filters
    assert ("storage", "EBS Only") in spec.filters


def test_invalid_toml_is_a_setup_error(tmp_path):
    path = tmp_path / "precios.toml"
    path.write_text("[precios\n", encoding="utf-8")
    with pytest.raises(AwsSetupError, match="no es TOML válido"):
        load_price_table(path)


def test_table_without_required_sections_is_a_setup_error(tmp_path):
    path = tmp_path / "precios.toml"
    path.write_text("[fuentes]\n", encoding="utf-8")
    with pytest.raises(AwsSetupError, match=r"\[precios\]"):
        load_price_table(path)
