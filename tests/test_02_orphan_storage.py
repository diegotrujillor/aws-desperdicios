import argparse
import json

import boto3
import pytest

from aws_desperdicios.checks import orphan_storage
from aws_desperdicios.checks.orphan_storage import BACKUP_DESCRIPTION_PREFIX, scan

REGION = "us-east-1"


def args(dias=0, profile=None):
    return argparse.Namespace(dias=dias, profile=profile)


@pytest.fixture
def ec2(aws):
    return boto3.client("ec2", region_name=REGION)


def volume(ec2, size=10, volume_type="gp2", **extra):
    return ec2.create_volume(Size=size, AvailabilityZone=f"{REGION}a", VolumeType=volume_type, **extra)["VolumeId"]


def by_id(findings):
    return {f.resource_id: f for f in findings}


def test_unattached_volume_has_exact_monthly_cost(session, local_prices, ec2):
    orphan = volume(ec2, size=100, volume_type="gp3", Iops=6000, Throughput=250)

    finding = by_id(scan(session, REGION, local_prices, args()))[orphan]

    # 100 GiB * 0.08 + 3,000 extra IOPS * 0.005 + 125 extra MiB/s * 0.04
    assert finding.monthly_savings_usd == pytest.approx(28.0)
    assert finding.savings_kind == "exacto"
    assert finding.suggested_commands == (f"aws ec2 delete-volume --region {REGION} --volume-id {orphan}",)


def test_attached_volumes_are_not_reported(session, local_prices, ec2):
    image_id = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    instance = ec2.run_instances(ImageId=image_id, MinCount=1, MaxCount=1)["Instances"][0]
    attached = volume(ec2)
    ec2.attach_volume(VolumeId=attached, InstanceId=instance["InstanceId"], Device="/dev/sdf")

    findings = by_id(scan(session, REGION, local_prices, args(dias=90)))

    assert attached not in findings


def test_old_snapshot_reports_maximum_savings_by_volume_size(session, local_prices, ec2):
    source = volume(ec2, size=200)
    snapshot = ec2.create_snapshot(VolumeId=source)["SnapshotId"]

    finding = by_id(scan(session, REGION, local_prices, args(dias=0)))[snapshot]

    assert finding.monthly_savings_usd == pytest.approx(200 * 0.05)
    assert finding.savings_kind == "máximo"
    assert finding.suggested_commands == (f"aws ec2 delete-snapshot --region {REGION} --snapshot-id {snapshot}",)


def test_recent_snapshots_are_ignored(session, local_prices, ec2):
    snapshot = ec2.create_snapshot(VolumeId=volume(ec2))["SnapshotId"]

    assert snapshot not in by_id(scan(session, REGION, local_prices, args(dias=90)))


def test_snapshot_of_deleted_volume_is_flagged_in_detail(session, local_prices, ec2):
    source = volume(ec2)
    snapshot = ec2.create_snapshot(VolumeId=source)["SnapshotId"]
    ec2.delete_volume(VolumeId=source)

    assert "ya no existe" in by_id(scan(session, REGION, local_prices, args()))[snapshot].detail


def test_snapshot_used_by_ami_is_reported_without_savings_or_command(session, local_prices, ec2):
    image = ec2.register_image(Name="ami-de-prueba", RootDeviceName="/dev/xvda")["ImageId"]
    # moto ignores BlockDeviceMappings on register_image and creates its own root snapshot.
    mapping = ec2.describe_images(ImageIds=[image])["Images"][0]["BlockDeviceMappings"][0]
    snapshot = mapping["Ebs"]["SnapshotId"]

    finding = by_id(scan(session, REGION, local_prices, args()))[snapshot]

    assert finding.monthly_savings_usd is None
    assert finding.suggested_commands == ()
    assert image in finding.detail


def test_aws_backup_snapshot_is_reported_without_command(session, local_prices, ec2):
    snapshot = ec2.create_snapshot(VolumeId=volume(ec2), Description=f"{BACKUP_DESCRIPTION_PREFIX} job 1")["SnapshotId"]

    finding = by_id(scan(session, REGION, local_prices, args()))[snapshot]

    assert finding.monthly_savings_usd is None
    assert "AWS Backup" in finding.detail
    assert finding.suggested_commands == ()


def test_only_read_only_calls_declared_in_iam_actions(session, local_prices, ec2, api_calls, policy_actions):
    ec2.create_snapshot(VolumeId=volume(ec2))
    api_calls.clear()

    scan(session, REGION, local_prices, args())

    assert api_calls <= set(orphan_storage.IAM_ACTIONS)
    assert set(orphan_storage.IAM_ACTIONS) <= policy_actions


def test_negative_days_are_rejected(capsys):
    with pytest.raises(SystemExit):
        orphan_storage.main(["--dias", "-1"])
    assert "--dias" in capsys.readouterr().err


def test_main_end_to_end_json(ec2, capsys):
    volume(ec2, size=50)

    code = orphan_storage.main(["--region", REGION, "--precios-locales", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["total_ahorro_mensual_usd"] == pytest.approx(5.0)
