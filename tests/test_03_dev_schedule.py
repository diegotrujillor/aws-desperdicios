import argparse
import json

import boto3
import pytest

from aws_desperdicios.checks import dev_schedule
from aws_desperdicios.checks.dev_schedule import monthly_hours_off, rds_price_variant, scan

REGION = "us-east-1"
# 730 h/month * (168 - 60) / 168 hours off with the default 60 h/week schedule.
DEFAULT_HOURS_OFF = 730 * 108 / 168


def args(etiqueta=None, valores=dev_schedule.DEFAULT_TAG_VALUES, horas_semana=60, profile=None):
    return argparse.Namespace(etiqueta=etiqueta, valores=valores, horas_semana=horas_semana, profile=profile)


def tags(**pairs):
    return [{"Key": k, "Value": v} for k, v in pairs.items()]


@pytest.fixture
def ec2(aws):
    return boto3.client("ec2", region_name=REGION)


@pytest.fixture
def rds(aws):
    return boto3.client("rds", region_name=REGION)


def linux_image(ec2):
    return next(i["ImageId"] for i in ec2.describe_images(Owners=["amazon"])["Images"] if i.get("Platform") != "windows")


def instance(ec2, instance_tags, instance_type="t3.micro", image=None):
    spec = [{"ResourceType": "instance", "Tags": instance_tags}] if instance_tags else []
    created = ec2.run_instances(
        ImageId=image or linux_image(ec2), MinCount=1, MaxCount=1, InstanceType=instance_type, TagSpecifications=spec
    )
    return created["Instances"][0]["InstanceId"]


def database(rds, identifier, db_tags, engine="postgres", instance_class="db.t3.micro", **extra):
    rds.create_db_instance(
        DBInstanceIdentifier=identifier, DBInstanceClass=instance_class, Engine=engine,
        MasterUsername="admin1", MasterUserPassword="password123", AllocatedStorage=20, Tags=db_tags, **extra,
    )


def by_id(findings):
    return {f.resource_id: f for f in findings}


def test_monthly_hours_off_follows_aws_730_hour_month():
    assert monthly_hours_off(60) == pytest.approx(DEFAULT_HOURS_OFF)
    assert monthly_hours_off(168) == 0


def test_tagged_running_linux_instance_reports_exact_savings(session, local_prices, ec2):
    dev = instance(ec2, tags(Environment="Dev", Name="api-dev"))

    finding = by_id(scan(session, REGION, local_prices, args()))[dev]

    assert finding.monthly_savings_usd == pytest.approx(round(0.0104 * DEFAULT_HOURS_OFF, 2))
    assert finding.savings_kind == "exacto"
    assert "api-dev" in finding.detail and "Environment=Dev" in finding.detail
    assert finding.suggested_commands == (f"aws ec2 stop-instances --region {REGION} --instance-ids {dev}",)


def test_untagged_production_and_stopped_instances_are_ignored(session, local_prices, ec2):
    untagged = instance(ec2, None)
    prod = instance(ec2, tags(Environment="prod"))
    stopped = instance(ec2, tags(Environment="dev"))
    ec2.stop_instances(InstanceIds=[stopped])

    found = by_id(scan(session, REGION, local_prices, args()))

    assert not {untagged, prod, stopped} & set(found)


def test_custom_tag_key_and_values(session, local_prices, ec2):
    sandbox = instance(ec2, tags(Equipo="laboratorio"))

    found = by_id(scan(session, REGION, local_prices, args(etiqueta=["equipo"], valores=("Laboratorio",))))

    assert sandbox in found


def test_non_linux_instance_is_reported_without_price(session, local_prices, ec2):
    windows = next(i["ImageId"] for i in ec2.describe_images(Owners=["amazon"])["Images"] if i.get("Platform") == "windows")
    win = instance(ec2, tags(Environment="qa"), image=windows)

    finding = by_id(scan(session, REGION, local_prices, args()))[win]

    assert finding.monthly_savings_usd is None
    assert "Windows" in finding.detail


def test_auto_scaling_instance_gets_no_stop_command():
    asg_instance = {
        "InstanceId": "i-asg",
        "InstanceType": "t3.micro",
        "PlatformDetails": "Linux/UNIX",
        "Placement": {"Tenancy": "default"},
        "Tags": tags(Environment="dev", **{"aws:autoscaling:groupName": "web-dev"}),
    }

    finding = dev_schedule.ec2_finding(asg_instance, REGION, None, args(), "Environment=dev")

    assert finding.suggested_commands == ()
    assert "web-dev" in finding.detail


def test_tagged_rds_instance_reports_savings_and_stop_command(session, local_prices, rds):
    database(rds, "pg-dev", tags(Environment="development"))

    finding = by_id(scan(session, REGION, local_prices, args()))["pg-dev"]

    assert finding.monthly_savings_usd == pytest.approx(round(0.018 * DEFAULT_HOURS_OFF, 2))
    assert finding.suggested_commands == (
        f"aws rds stop-db-instance --region {REGION} --db-instance-identifier pg-dev",
    )


def test_aurora_instance_suggests_stopping_the_cluster(session, local_prices, rds):
    rds.create_db_cluster(
        DBClusterIdentifier="aurora-qa", Engine="aurora-postgresql", MasterUsername="admin1", MasterUserPassword="password123"
    )
    database(rds, "aurora-qa-1", tags(env="QA"), engine="aurora-postgresql", instance_class="db.r6g.large",
             DBClusterIdentifier="aurora-qa")

    finding = by_id(scan(session, REGION, local_prices, args(etiqueta=["env"])))["aurora-qa-1"]

    assert finding.monthly_savings_usd == pytest.approx(round(0.26 * DEFAULT_HOURS_OFF, 2))
    assert finding.suggested_commands == (
        f"aws rds stop-db-cluster --region {REGION} --db-cluster-identifier aurora-qa",
    )


@pytest.mark.parametrize(
    ("db", "expected"),
    [
        ({"Engine": "postgres", "DBInstanceClass": "db.t3.micro", "MultiAZ": True},
         "PostgreSQL|Multi-AZ|db.t3.micro|EBS Only"),
        ({"Engine": "aurora-mysql", "DBInstanceClass": "db.r6g.large", "StorageType": "aurora-iopt1"},
         "Aurora MySQL|Single-AZ|db.r6g.large|Aurora IO Optimization Mode"),
        ({"Engine": "sqlserver-se", "DBInstanceClass": "db.m5.large"}, None),
    ],
)
def test_rds_price_variant(db, expected):
    assert rds_price_variant(db) == expected


def test_read_replica_is_reported_without_savings_or_command():
    replica = {
        "DBInstanceIdentifier": "pg-replica",
        "DBInstanceClass": "db.t3.micro",
        "Engine": "postgres",
        "ReadReplicaSourceDBInstanceIdentifier": "pg-dev",
    }

    finding = dev_schedule.rds_finding(replica, REGION, None, args(), "Environment=dev")

    assert finding.monthly_savings_usd is None
    assert finding.suggested_commands == ()
    assert "réplica" in finding.detail


def test_only_read_only_calls_declared_in_iam_actions(session, local_prices, ec2, rds, api_calls, policy_actions):
    instance(ec2, tags(Environment="dev"))
    database(rds, "pg-dev", tags(Environment="dev"))
    api_calls.clear()

    scan(session, REGION, local_prices, args())

    assert api_calls <= set(dev_schedule.IAM_ACTIONS)
    assert set(dev_schedule.IAM_ACTIONS) <= policy_actions


@pytest.mark.parametrize("hours", ["-1", "169", "abc"])
def test_weekly_hours_must_be_between_0_and_168(hours, capsys):
    with pytest.raises(SystemExit):
        dev_schedule.main(["--horas-semana", hours])
    assert "--horas-semana" in capsys.readouterr().err


def test_main_end_to_end_json(ec2, capsys):
    instance(ec2, tags(Environment="staging"))

    code = dev_schedule.main(["--region", REGION, "--precios-locales", "--json", "--horas-semana", "84"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    # 730 h * (168 - 84) / 168 = 365 h off per month
    assert data["total_ahorro_mensual_usd"] == pytest.approx(round(0.0104 * 365, 2))
    assert any("84 h" in note for note in data["notas"])
