import json
from datetime import date

import boto3
import pytest
from botocore.stub import Stubber

from aws_desperdicios.errors import AwsSetupError
from aws_desperdicios.pricing import PRICE_SPECS, Price, PriceCatalog, load_price_table
from tests.conftest import PRICE_TABLE_PATH

TODAY = date(2026, 11, 12)


def price_item(unit, usd):
    return json.dumps(
        {
            "product": {"productFamily": "Storage", "attributes": {}},
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


def test_local_table_has_every_spec_key_for_each_region(table):
    for region, prices in table["precios"].items():
        assert set(PRICE_SPECS) <= set(prices), region


def test_local_table_entries_reference_a_declared_source(table):
    sources = set(table["fuentes"])
    for prices in table["precios"].values():
        for entry in prices.values():
            assert entry["fuente"] in sources
            assert entry["usd"] > 0


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
        {"ServiceCode": "AmazonEC2", "Filters": expected_filters, "MaxResults": 10},
    )
    with stubber:
        catalog = PriceCatalog(pricing_client, table, today=TODAY)
        price = catalog.get("ebs_gp2_gb_mes", "eu-west-1")

    assert price == Price(usd=0.11, source="AWS Pricing API (consultada 2026-11-12)")


def test_caches_api_prices_per_key_and_region(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_response("get_products", {"PriceList": [price_item("GB-Mo", "0.11")]})
    with stubber:
        catalog = PriceCatalog(pricing_client, table, today=TODAY)
        first = catalog.get("ebs_gp2_gb_mes", "eu-west-1")
        second = catalog.get("ebs_gp2_gb_mes", "eu-west-1")
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
        price = PriceCatalog(pricing_client, table, today=TODAY).get("ebs_gp2_gb_mes", "us-east-1")
    assert price.usd == 0.10
    assert "config/precios.toml" in price.source


def test_falls_back_to_table_when_api_prices_are_ambiguous(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_response(
        "get_products", {"PriceList": [price_item("GB-Mo", "0.10"), price_item("GB-Mo", "0.12")]}
    )
    with stubber:
        price = PriceCatalog(pricing_client, table, today=TODAY).get("ebs_gp2_gb_mes", "us-east-1")
    assert price.usd == 0.10


def test_access_denied_disables_api_and_adds_spanish_note(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_client_error("get_products", service_error_code="AccessDeniedException")
    with stubber:
        catalog = PriceCatalog(pricing_client, table, today=TODAY)
        first = catalog.get("ebs_gp2_gb_mes", "us-east-1")
        second = catalog.get("ebs_gp3_gb_mes", "us-east-1")

    assert (first.usd, second.usd) == (0.10, 0.08)
    assert any("pricing:GetProducts" in note for note in catalog.notes())
    stubber.assert_no_pending_responses()


def test_returns_none_and_notes_region_without_any_price(local_prices):
    assert local_prices.get("ebs_gp2_gb_mes", "ap-southeast-7") is None
    assert any("ap-southeast-7" in note for note in local_prices.notes())


def test_unknown_key_is_a_programming_error(local_prices):
    with pytest.raises(KeyError):
        local_prices.get("does_not_exist", "us-east-1")


def test_table_source_mentions_publication_date(local_prices):
    price = local_prices.get("ebs_gp3_gb_mes", "sa-east-1")
    assert price.usd == 0.152
    assert "2026-11-10" in price.source


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


def test_non_permission_api_error_also_falls_back_with_note(pricing_client, table):
    stubber = Stubber(pricing_client)
    stubber.add_client_error("get_products", service_error_code="ThrottlingException")
    with stubber:
        catalog = PriceCatalog(pricing_client, table, today=TODAY)
        price = catalog.get("ebs_gp2_gb_mes", "us-east-1")
    assert price.usd == 0.10
    assert any("error al consultarla" in note for note in catalog.notes())
