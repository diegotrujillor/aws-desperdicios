import argparse
import json
from datetime import UTC, datetime, timedelta

import boto3
import pytest

from aws_desperdicios.checks import nat_endpoints
from aws_desperdicios.checks.nat_endpoints import BYTES_PER_GIB, DAYS_PER_MONTH, scan

REGION = "us-east-1"
S3 = f"com.amazonaws.{REGION}.s3"
DYNAMODB = f"com.amazonaws.{REGION}.dynamodb"


def args(dias=30, profile=None):
    return argparse.Namespace(dias=dias, profile=profile)


@pytest.fixture
def ec2(aws):
    return boto3.client("ec2", region_name=REGION)


@pytest.fixture
def network(ec2):
    """VPC with a NAT Gateway and a private route table sending 0.0.0.0/0 through it."""
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    allocation = ec2.allocate_address(Domain="vpc")["AllocationId"]
    nat = ec2.create_nat_gateway(SubnetId=subnet, AllocationId=allocation)["NatGateway"]["NatGatewayId"]
    route_table = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=route_table, DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat)
    return {"vpc": vpc, "nat": nat, "route_table": route_table}


def gateway_endpoint(ec2, vpc, service, route_tables):
    return ec2.create_vpc_endpoint(
        VpcId=vpc, ServiceName=service, VpcEndpointType="Gateway", RouteTableIds=route_tables
    )["VpcEndpoint"]["VpcEndpointId"]


def put_bytes(nat, metric, gib):
    boto3.client("cloudwatch", region_name=REGION).put_metric_data(
        Namespace="AWS/NATGateway",
        MetricData=[
            {
                "MetricName": metric,
                "Dimensions": [{"Name": "NatGatewayId", "Value": nat}],
                "Value": gib * BYTES_PER_GIB,
                "Timestamp": datetime.now(UTC) - timedelta(days=1),
            }
        ],
    )


def test_nat_without_endpoints_reports_maximum_savings_and_both_commands(session, local_prices, ec2, network):
    put_bytes(network["nat"], "BytesInFromDestination", 100)
    put_bytes(network["nat"], "BytesInFromSource", 20)

    [finding] = scan(session, REGION, local_prices, args())

    monthly_gib = 120 / 30 * DAYS_PER_MONTH
    assert finding.resource_id == network["nat"]
    assert finding.monthly_savings_usd == pytest.approx(round(monthly_gib * 0.045, 2))
    assert finding.savings_kind == "máximo"
    rt, vpc = network["route_table"], network["vpc"]
    assert finding.suggested_commands == (
        f"aws ec2 create-vpc-endpoint --region {REGION} --vpc-id {vpc} --vpc-endpoint-type Gateway "
        f"--service-name {S3} --route-table-ids {rt}",
        f"aws ec2 create-vpc-endpoint --region {REGION} --vpc-id {vpc} --vpc-endpoint-type Gateway "
        f"--service-name {DYNAMODB} --route-table-ids {rt}",
    )


def test_only_missing_service_is_suggested(session, local_prices, ec2, network):
    gateway_endpoint(ec2, network["vpc"], S3, [network["route_table"]])

    [finding] = scan(session, REGION, local_prices, args())

    assert len(finding.suggested_commands) == 1
    assert DYNAMODB in finding.suggested_commands[0]
    assert "DynamoDB" in finding.detail and "S3" not in finding.detail.split("sin endpoint")[-1]


def test_existing_endpoint_missing_the_route_table_is_extended(session, local_prices, ec2, network):
    other_table = ec2.create_route_table(VpcId=network["vpc"])["RouteTable"]["RouteTableId"]
    endpoint = gateway_endpoint(ec2, network["vpc"], S3, [other_table])
    gateway_endpoint(ec2, network["vpc"], DYNAMODB, [network["route_table"]])

    [finding] = scan(session, REGION, local_prices, args())

    assert finding.suggested_commands == (
        f"aws ec2 modify-vpc-endpoint --region {REGION} --vpc-endpoint-id {endpoint} "
        f"--add-route-table-ids {network['route_table']}",
    )


def test_nat_with_both_endpoints_associated_is_not_reported(session, local_prices, ec2, network):
    gateway_endpoint(ec2, network["vpc"], S3, [network["route_table"]])
    gateway_endpoint(ec2, network["vpc"], DYNAMODB, [network["route_table"]])

    assert scan(session, REGION, local_prices, args()) == []


def test_nat_without_traffic_reports_zero_savings(session, local_prices, network):
    [finding] = scan(session, REGION, local_prices, args())
    assert finding.monthly_savings_usd == 0.0


def test_region_without_price_reports_without_savings(session, local_prices, aws):
    eu = boto3.client("ec2", region_name="eu-west-1")
    vpc = eu.create_vpc(CidrBlock="10.1.0.0/16")["Vpc"]["VpcId"]
    subnet = eu.create_subnet(VpcId=vpc, CidrBlock="10.1.1.0/24")["Subnet"]["SubnetId"]
    nat = eu.create_nat_gateway(SubnetId=subnet, AllocationId=eu.allocate_address(Domain="vpc")["AllocationId"])
    table = eu.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    eu.create_route(RouteTableId=table, DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat["NatGateway"]["NatGatewayId"])

    [finding] = scan(session, "eu-west-1", local_prices, args())

    assert finding.monthly_savings_usd is None


def test_region_without_nat_gateways_makes_no_other_calls(session, local_prices, aws, api_calls):
    assert scan(session, REGION, local_prices, args()) == []
    assert api_calls == {"ec2:DescribeNatGateways"}


def test_only_read_only_calls_declared_in_iam_actions(session, local_prices, network, api_calls, policy_actions):
    api_calls.clear()

    scan(session, REGION, local_prices, args())

    assert api_calls <= set(nat_endpoints.IAM_ACTIONS)
    assert set(nat_endpoints.IAM_ACTIONS) <= policy_actions


@pytest.mark.parametrize("days", ["0", "456"])
def test_metric_days_are_validated(days, capsys):
    with pytest.raises(SystemExit):
        nat_endpoints.main(["--dias", days])
    assert "--dias" in capsys.readouterr().err


def test_main_end_to_end_json(network, capsys):
    put_bytes(network["nat"], "BytesInFromDestination", 30)

    code = nat_endpoints.main(["--region", REGION, "--precios-locales", "--json", "--dias", "30"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["hallazgos"][0]["recurso"] == network["nat"]
    assert data["total_ahorro_mensual_usd"] == pytest.approx(round(30 / 30 * DAYS_PER_MONTH * 0.045, 2))
