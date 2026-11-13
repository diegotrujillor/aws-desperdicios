import argparse
import json
import time

import boto3
import pytest

from aws_desperdicios.checks import log_retention
from aws_desperdicios.checks.log_retention import BYTES_PER_GIB, log_group_finding, scan

REGION = "us-east-1"


def args(retencion_dias=30, profile=None):
    return argparse.Namespace(retencion_dias=retencion_dias, profile=profile)


@pytest.fixture
def logs(aws):
    return boto3.client("logs", region_name=REGION)


def log_group(logs, name, message_bytes=0, retention=None):
    logs.create_log_group(logGroupName=name)
    if retention:
        logs.put_retention_policy(logGroupName=name, retentionInDays=retention)
    if message_bytes:
        logs.create_log_stream(logGroupName=name, logStreamName="s")
        logs.put_log_events(
            logGroupName=name,
            logStreamName="s",
            logEvents=[{"timestamp": int(time.time() * 1000), "message": "x" * message_bytes}],
        )


def test_reports_only_groups_without_retention(session, local_prices, logs):
    log_group(logs, "/app/sin-retencion", message_bytes=100)
    log_group(logs, "/app/con-retencion", message_bytes=100, retention=14)

    found = {f.resource_id for f in scan(session, REGION, local_prices, args())}

    assert found == {"/app/sin-retencion"}


def test_savings_are_maximum_storage_cost_of_the_group():
    group = {"logGroupName": "/aws/lambda/api", "storedBytes": 50 * BYTES_PER_GIB, "creationTime": 1_700_000_000_000}

    finding = log_group_finding(group, REGION, 0.03, args())

    assert finding.monthly_savings_usd == pytest.approx(1.5)
    assert finding.savings_kind == "máximo"
    assert "50.00 GiB" in finding.detail


def test_suggested_command_uses_requested_retention_and_quotes_names():
    group = {"logGroupName": "/app/con espacio", "storedBytes": 0, "creationTime": 1_700_000_000_000}

    finding = log_group_finding(group, REGION, 0.03, args(retencion_dias=90))

    assert finding.suggested_commands == (
        f"aws logs put-retention-policy --region {REGION} --log-group-name '/app/con espacio' --retention-in-days 90",
    )


def test_infrequent_access_class_is_flagged_in_detail():
    group = {"logGroupName": "/ia", "storedBytes": 0, "creationTime": 0, "logGroupClass": "INFREQUENT_ACCESS"}

    assert "Infrequent Access" in log_group_finding(group, REGION, 0.03, args()).detail


def test_delivery_class_groups_are_skipped(session, local_prices, logs, monkeypatch):
    log_group(logs, "/delivery")
    original = log_retention._log_groups

    def with_delivery_class(client):
        return [{**g, "logGroupClass": "DELIVERY"} for g in original(client)]

    monkeypatch.setattr(log_retention, "_log_groups", with_delivery_class)

    assert scan(session, REGION, local_prices, args()) == []


def test_findings_are_sorted_by_savings(session, local_prices, logs):
    log_group(logs, "/small", message_bytes=10)
    log_group(logs, "/large", message_bytes=5000)

    names = [f.resource_id for f in scan(session, REGION, local_prices, args())]

    assert names == ["/large", "/small"]


def test_region_without_price_reports_groups_without_savings():
    group = {"logGroupName": "/x", "storedBytes": BYTES_PER_GIB, "creationTime": 0}
    assert log_group_finding(group, REGION, None, args()).monthly_savings_usd is None


def test_only_read_only_calls_declared_in_iam_actions(session, local_prices, logs, api_calls, policy_actions):
    log_group(logs, "/app")
    api_calls.clear()

    scan(session, REGION, local_prices, args())

    assert api_calls <= set(log_retention.IAM_ACTIONS)
    assert set(log_retention.IAM_ACTIONS) <= policy_actions


def test_retention_must_be_a_value_accepted_by_cloudwatch(capsys):
    with pytest.raises(SystemExit):
        log_retention.main(["--retencion-dias", "45"])
    err = capsys.readouterr().err
    assert "--retencion-dias" in err and "30" in err


def test_main_end_to_end_json(logs, capsys):
    log_group(logs, "/app/dev", message_bytes=1000)

    code = log_retention.main(["--region", REGION, "--precios-locales", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["hallazgos"][0]["recurso"] == "/app/dev"
    assert data["hallazgos"][0]["tipo_ahorro"] == "máximo"
