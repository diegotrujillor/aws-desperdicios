"""Shared fixtures. Tests never reach real AWS: credentials are fake and moto intercepts calls."""
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from aws_desperdicios.errors import iam_action_name
from aws_desperdicios.pricing import PriceCatalog, load_price_table

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "iam" / "politica-minima.json"
PRICE_TABLE_PATH = REPO_ROOT / "config" / "precios.toml"


@pytest.fixture(autouse=True)
def fake_aws_credentials(monkeypatch, tmp_path):
    """Isolate every test from the developer's real AWS config and credentials."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "credentials"))
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture
def aws():
    with mock_aws():
        yield


@pytest.fixture
def session(aws):
    return boto3.Session(region_name="us-east-1")


@pytest.fixture
def local_prices():
    """Catalog backed only by the local price table (no Pricing API)."""
    return PriceCatalog(pricing_client=None, table=load_price_table(PRICE_TABLE_PATH))


@pytest.fixture
def api_calls(session):
    """Record every AWS API call made through `session` as an IAM action string."""
    calls = set()

    def record(model, **_kwargs):
        calls.add(iam_action_name(model))

    session.events.register("before-call", record)
    return calls


@pytest.fixture
def policy_actions():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return {action for stmt in policy["Statement"] for action in stmt["Action"]}
