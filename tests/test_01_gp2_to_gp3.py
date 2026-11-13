import argparse
import json

import boto3
import pytest

from aws_desperdicios.checks import gp2_to_gp3
from aws_desperdicios.checks.gp2_to_gp3 import gp2_performance, gp3_equivalent, scan
from aws_desperdicios.pricing import PriceCatalog


def args(profile=None):
    return argparse.Namespace(profile=profile)


def create_volume(region, size, volume_type="gp2", attach=False):
    ec2 = boto3.client("ec2", region_name=region)
    volume = ec2.create_volume(Size=size, AvailabilityZone=f"{region}a", VolumeType=volume_type)
    if attach:
        image_id = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
        instance = ec2.run_instances(ImageId=image_id, MinCount=1, MaxCount=1)["Instances"][0]
        ec2.attach_volume(VolumeId=volume["VolumeId"], InstanceId=instance["InstanceId"], Device="/dev/sdf")
    return volume["VolumeId"]


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (1, (100, 128)),  # IOPS floor of 100
        (100, (300, 128)),
        (170, (510, 128)),
        (171, (513, 250)),  # above 170 GiB gp2 can reach 250 MiB/s
        (1000, (3000, 250)),
        (6000, (16000, 250)),  # IOPS cap of 16,000
    ],
)
def test_gp2_performance_follows_aws_documented_limits(size, expected):
    assert gp2_performance(size) == expected


@pytest.mark.parametrize(
    ("size", "expected"),
    [(100, (3000, 128)), (1000, (3000, 250)), (6000, (16000, 250))],
)
def test_gp3_equivalent_never_reduces_performance(size, expected):
    assert gp3_equivalent(size) == expected


def test_reports_exact_savings_for_each_gp2_volume(session, local_prices):
    small = create_volume("us-east-1", 100)
    large = create_volume("us-east-1", 1000, attach=True)
    gp3_volume = create_volume("us-east-1", 500, volume_type="gp3")

    findings = {f.resource_id: f for f in scan(session, "us-east-1", local_prices, args())}

    # The instance created for the attachment adds its own gp2 root volume, which is also reported.
    assert {small, large} <= set(findings)
    assert gp3_volume not in findings
    # 100 GiB: gp2 10.00 vs gp3 8.00 + 3 extra MiB/s * 0.04 = 8.12
    assert findings[small].monthly_savings_usd == pytest.approx(1.88)
    # 1000 GiB: gp2 100.00 vs gp3 80.00 + 125 extra MiB/s * 0.04 = 85.00
    assert findings[large].monthly_savings_usd == pytest.approx(15.0)
    assert all(f.savings_kind == "exacto" for f in findings.values())
    assert "sin adjuntar" in findings[small].detail
    assert "en uso" in findings[large].detail


def test_large_volumes_include_extra_iops_cost(session, local_prices):
    volume = create_volume("us-east-1", 6000)

    [finding] = scan(session, "us-east-1", local_prices, args())

    # gp2 600.00 vs gp3 480.00 + 13,000 IOPS * 0.005 + 125 MiB/s * 0.04 = 550.00
    assert finding.resource_id == volume
    assert finding.monthly_savings_usd == pytest.approx(50.0)


def test_suggested_command_preserves_performance_and_profile(session, local_prices):
    volume = create_volume("sa-east-1", 100)

    [finding] = scan(session, "sa-east-1", local_prices, args(profile="prod"))

    assert finding.suggested_commands == (
        f"aws ec2 modify-volume --profile prod --region sa-east-1 --volume-id {volume} "
        "--volume-type gp3 --iops 3000 --throughput 128",
    )


def test_region_without_price_reports_volume_without_savings(session, local_prices):
    create_volume("eu-west-1", 100)

    [finding] = scan(session, "eu-west-1", local_prices, args())

    assert finding.monthly_savings_usd is None


def test_only_read_only_calls_declared_in_iam_actions(session, local_prices, api_calls, policy_actions):
    create_volume("us-east-1", 100)
    api_calls.clear()

    scan(session, "us-east-1", local_prices, args())

    assert api_calls <= set(gp2_to_gp3.IAM_ACTIONS)
    assert set(gp2_to_gp3.IAM_ACTIONS) <= policy_actions


def test_main_end_to_end_json(aws, capsys):
    create_volume("us-east-1", 1000)

    code = gp2_to_gp3.main(["--region", "us-east-1", "--precios-locales", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["total_ahorro_mensual_usd"] == 15.0
    assert any("gp2" in note for note in data["notas"])


def test_volume_is_skipped_when_gp3_would_not_be_cheaper(session):
    table = {
        "fuentes": {"X": {"publicacion": "2026-01-01T00:00:00Z"}},
        "precios": {
            "us-east-1": {
                "ebs_gb_mes": {"gp2": {"usd": 0.05, "fuente": "X"}, "gp3": {"usd": 0.08, "fuente": "X"}},
                "ebs_iops_mes": {"gp3": {"usd": 0.005, "fuente": "X"}},
                "ebs_gp3_mibps_mes": {"usd": 0.04, "fuente": "X"},
            }
        },
    }
    create_volume("us-east-1", 100)

    assert scan(session, "us-east-1", PriceCatalog(None, table), args()) == []
